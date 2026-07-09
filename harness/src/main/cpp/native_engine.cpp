#include "native_engine.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <ctime>

#include <android/log.h>

#define LOG_TAG "OverdubHarness"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGW(...) __android_log_print(ANDROID_LOG_WARN, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

namespace overdub {

using oboe::AudioFormat;
using oboe::AudioStreamBuilder;
using oboe::DataCallbackResult;
using oboe::Direction;
using oboe::PerformanceMode;
using oboe::Result;
using oboe::SharingMode;

// Cap a single input read so the fixed scratch buffer is never overrun; larger bursts are read
// across successive callbacks. Chosen well above any realistic LowLatency burst size.
static constexpr int32_t kMaxFramesPerRead = 8192;

// Buffer capacity as a multiple of the burst size (see open()): trades a few ms of latency for
// warmup-XRun headroom, which this capture harness prefers.
static constexpr int32_t kBufferBursts = 4;

FullDuplexEngine::FullDuplexEngine() : mRing(kRingCapacity) {}

FullDuplexEngine::~FullDuplexEngine() {
    stop();
    close();
}

int FullDuplexEngine::open(int32_t sampleRate, int32_t channelCount, int32_t inputPreset,
                           int32_t outputDeviceId, int32_t inputDeviceId) {
    mChannelCount = channelCount;
    mInputScratch.assign(static_cast<size_t>(kMaxFramesPerRead) * channelCount, 0);

    // --- Input stream (opened first so the callback can read from it immediately) ---
    AudioStreamBuilder inputBuilder;
    inputBuilder.setDirection(Direction::Input)
        ->setPerformanceMode(PerformanceMode::LowLatency)
        ->setSharingMode(SharingMode::Exclusive)
        ->setFormat(AudioFormat::I16)
        ->setChannelCount(channelCount)
        ->setSampleRate(sampleRate)
        ->setInputPreset(static_cast<oboe::InputPreset>(inputPreset));
    if (inputDeviceId >= 0) {
        inputBuilder.setDeviceId(inputDeviceId);
    }
    Result r = inputBuilder.openStream(mInputStream);
    if (r != Result::OK) {
        LOGE("input openStream failed: %s", oboe::convertToText(r));
        return static_cast<int>(r);
    }

    // --- Output stream (owns the data callback that also pulls the input) ---
    AudioStreamBuilder outputBuilder;
    outputBuilder.setDirection(Direction::Output)
        ->setPerformanceMode(PerformanceMode::LowLatency)
        ->setSharingMode(SharingMode::Exclusive)
        ->setFormat(AudioFormat::I16)
        ->setChannelCount(channelCount)
        ->setSampleRate(sampleRate)
        ->setUsage(oboe::Usage::Media)
        ->setDataCallback(this);
    if (outputDeviceId >= 0) {
        outputBuilder.setDeviceId(outputDeviceId);
    }
    r = outputBuilder.openStream(mOutputStream);
    if (r != Result::OK) {
        LOGE("output openStream failed: %s", oboe::convertToText(r));
        mInputStream->close();
        mInputStream.reset();
        return static_cast<int>(r);
    }

    mActualSampleRate = mOutputStream->getSampleRate();
    mOutputDeviceId = mOutputStream->getDeviceId();
    mInputDeviceId = mInputStream->getDeviceId();

    // AAudio LowLatency opens the buffer at a single burst -- the lowest-latency, most
    // underrun-prone size -- which produces warmup XRuns on a cold start. This harness values a
    // clean, XRun-free capture over minimal latency (GCC-PHAT recovers the offset regardless of a
    // few extra ms of buffering), so grow both buffers to several bursts, per Oboe's buffer-tuning
    // guidance, to absorb warmup jitter.
    int32_t outBurst = mOutputStream->getFramesPerBurst();
    int32_t inBurst = mInputStream->getFramesPerBurst();
    auto outCap = mOutputStream->setBufferSizeInFrames(outBurst * kBufferBursts);
    // Max out the input buffer: on the capture side extra buffering costs nothing GCC-PHAT cares
    // about (the offset is recovered by correlation, not by a low-latency read), and the headroom
    // absorbs any residual startup jitter before the output callback's first drain.
    auto inCap = mInputStream->setBufferSizeInFrames(mInputStream->getBufferCapacityInFrames());
    LOGI("opened full-duplex: rate=%d ch=%d outDev=%d inDev=%d outBurst=%d inBurst=%d "
         "outCap=%d inCap=%d",
         mActualSampleRate, mChannelCount, mOutputDeviceId, mInputDeviceId, outBurst, inBurst,
         outCap ? outCap.value() : -1, inCap ? inCap.value() : -1);
    return static_cast<int>(Result::OK);
}

void FullDuplexEngine::setPlayback(const int16_t *samples, size_t count, float gain) {
    mPlayback.assign(samples, samples + count);
    mPlaybackCursor = 0;
    mGain = gain;
    mPlaybackComplete.store(false, std::memory_order_relaxed);
}

int FullDuplexEngine::start() {
    if (!mOutputStream || !mInputStream) {
        LOGE("start() called before a successful open()");
        return static_cast<int>(Result::ErrorClosed);
    }

    // Reset capture state for this run.
    mRingWrite.store(0, std::memory_order_relaxed);
    mRingRead.store(0, std::memory_order_relaxed);
    mDroppedFrames.store(0, std::memory_order_relaxed);
    {
        std::lock_guard<std::mutex> lock(mAccumMutex);
        mAccumulator.clear();
    }

    mInputStarted.store(false, std::memory_order_relaxed);
    mDrainRunning.store(true, std::memory_order_relaxed);
    {
        // Reset the multi-read series for this run (item 13 (b)).
        std::lock_guard<std::mutex> lock(mTsMutex);
        mTimestampSamples.clear();
    }
    mDrainThread = std::thread(&FullDuplexEngine::drainLoop, this);

    // Start the OUTPUT first so its data callback (the input drainer) is already running before the
    // input stream begins producing data -- otherwise the input buffer backs up during the startup
    // gap and overruns (observed as input-side warmup XRuns). The callback skips input reads until
    // mInputStarted flips true, so it never touches a not-yet-started input stream.
    Result r = mOutputStream->requestStart();
    if (r != Result::OK) {
        LOGE("output requestStart failed: %s", oboe::convertToText(r));
        mDrainRunning.store(false, std::memory_order_relaxed);
        if (mDrainThread.joinable()) mDrainThread.join();
        return static_cast<int>(r);
    }
    r = mInputStream->requestStart();
    if (r != Result::OK) {
        LOGE("input requestStart failed: %s", oboe::convertToText(r));
        mOutputStream->requestStop();
        mDrainRunning.store(false, std::memory_order_relaxed);
        if (mDrainThread.joinable()) mDrainThread.join();
        return static_cast<int>(r);
    }
    mInputStarted.store(true, std::memory_order_release);
    return static_cast<int>(Result::OK);
}

void FullDuplexEngine::stop() {
    // Read hardware timestamps while both streams are still RUNNING (item 10) -- must happen before
    // requestStop() below. Latched once, so a repeat stop() (streams already stopped) is a no-op.
    if (!mHasTimestamps.load(std::memory_order_relaxed)) {
        readStreamTimestamps();
    }

    // Stop the callback reading input before the input stream is torn down.
    mInputStarted.store(false, std::memory_order_release);
    if (mOutputStream) mOutputStream->requestStop();
    if (mInputStream) mInputStream->requestStop();

    if (mDrainRunning.exchange(false, std::memory_order_relaxed)) {
        if (mDrainThread.joinable()) mDrainThread.join();
    }

    // Latch XRun counts (Components 2 / same bar as Test 1: a non-zero count contaminates the file,
    // so it must reach the metadata rather than be silently dropped). Log each stream separately so
    // a diagnosis can tell an output underrun from an input overrun.
    int32_t outXruns = -1;
    int32_t inXruns = -1;
    if (mOutputStream) {
        auto res = mOutputStream->getXRunCount();
        if (res) outXruns = res.value();
    }
    if (mInputStream) {
        auto res = mInputStream->getXRunCount();
        if (res) inXruns = res.value();
    }
    mXRunCount = std::max(outXruns, inXruns);
    LOGI("xruns: output=%d input=%d", outXruns, inXruns);

    int64_t dropped = mDroppedFrames.load(std::memory_order_relaxed);
    if (dropped > 0) {
        LOGW("ring overflow: dropped %lld captured samples (drain thread fell behind)",
             static_cast<long long>(dropped));
    }
    LOGI("stopped: xruns=%d dropped=%lld", mXRunCount, static_cast<long long>(dropped));
}

void FullDuplexEngine::close() {
    if (mOutputStream) {
        mOutputStream->close();
        mOutputStream.reset();
    }
    if (mInputStream) {
        mInputStream->close();
        mInputStream.reset();
    }
}

void FullDuplexEngine::readStreamTimestamps() {
    if (!mOutputStream || !mInputStream) return;

    // getTimestamp() is only valid while the stream is RUNNING; it returns an error otherwise. Read
    // both against the same CLOCK_MONOTONIC the derived-offset math assumes. Each pair is internally
    // consistent (framePosition happened at nanoTime), so the few microseconds between the two calls
    // don't matter -- the Kotlin side combines them algebraically at a common reference, not by
    // assuming the two reads are simultaneous.
    auto outTs = mOutputStream->getTimestamp(CLOCK_MONOTONIC);
    auto inTs = mInputStream->getTimestamp(CLOCK_MONOTONIC);
    if (!outTs || !inTs) {
        LOGW("getTimestamp unavailable (out=%s in=%s) -- stream offset will be absent from metadata",
             oboe::convertToText(outTs.error()), oboe::convertToText(inTs.error()));
        return;
    }

    mOutputTsFrames = outTs.value().position;
    mOutputTsNanos = outTs.value().timestamp;
    mInputTsFrames = inTs.value().position;
    mInputTsNanos = inTs.value().timestamp;
    mHasTimestamps.store(true, std::memory_order_relaxed);
    LOGI("stream timestamps: out=(%lld frames, %lld ns) in=(%lld frames, %lld ns)",
         static_cast<long long>(mOutputTsFrames), static_cast<long long>(mOutputTsNanos),
         static_cast<long long>(mInputTsFrames), static_cast<long long>(mInputTsNanos));
}

bool FullDuplexEngine::readStreamTimestampSample() {
    if (!mOutputStream || !mInputStream) return false;
    auto outTs = mOutputStream->getTimestamp(CLOCK_MONOTONIC);
    auto inTs = mInputStream->getTimestamp(CLOCK_MONOTONIC);
    if (!outTs || !inTs) {
        // A transient failure (e.g. the streams are stopping) is expected near session end; the
        // drain loop just skips it and tries again next period. Only a sustained failure (every
        // read fails -> empty series) signals getTimestamp is unsupported, which the Kotlin side
        // records as a null timestamp_samples list (same honesty rule as the single-read fields).
        return false;
    }
    {
        std::lock_guard<std::mutex> lock(mTsMutex);
        mTimestampSamples.push_back({
            outTs.value().position,
            outTs.value().timestamp,
            inTs.value().position,
            inTs.value().timestamp,
        });
    }
    return true;
}

std::vector<int64_t> FullDuplexEngine::timestampSamplesFlat() {
    std::lock_guard<std::mutex> lock(mTsMutex);
    std::vector<int64_t> flat;
    flat.reserve(mTimestampSamples.size() * 4);
    for (const auto &s : mTimestampSamples) {
        flat.push_back(s.outFrames);
        flat.push_back(s.outNanos);
        flat.push_back(s.inFrames);
        flat.push_back(s.inNanos);
    }
    return flat;
}

size_t FullDuplexEngine::capturedSampleCount() {
    std::lock_guard<std::mutex> lock(mAccumMutex);
    return mAccumulator.size();
}

size_t FullDuplexEngine::copyCapturedSamples(int16_t *dst, size_t maxCount) {
    std::lock_guard<std::mutex> lock(mAccumMutex);
    size_t n = std::min(maxCount, mAccumulator.size());
    std::memcpy(dst, mAccumulator.data(), n * sizeof(int16_t));
    return n;
}

oboe::DataCallbackResult FullDuplexEngine::onAudioReady(oboe::AudioStream * /* oboeStream */,
                                                        void *audioData, int32_t numFrames) {
    auto *out = static_cast<int16_t *>(audioData);
    const int32_t ch = mChannelCount;

    // Drain ALL currently-available input each callback (non-blocking, timeout 0), not just one
    // output burst's worth. Reading only numFrames lets the input buffer back up and overrun during
    // warmup (observed as input-side XRuns); looping until read() returns short empties whatever the
    // input has queued so it never overruns. Bounded by available data, allocation-free (reuses the
    // scratch buffer), so it stays callback-safe.
    if (mInputStream && mInputStarted.load(std::memory_order_acquire)) {
        while (true) {
            auto res = mInputStream->read(mInputScratch.data(), kMaxFramesPerRead, 0);
            if (!res || res.value() <= 0) break;
            int32_t framesRead = res.value();
            size_t offered = static_cast<size_t>(framesRead) * ch;
            size_t pushed = ringPush(mInputScratch.data(), offered);
            if (pushed < offered) {
                mDroppedFrames.fetch_add(static_cast<int64_t>(offered - pushed),
                                         std::memory_order_relaxed);
            }
            if (framesRead < kMaxFramesPerRead) break;  // drained everything available
        }
    }

    // Clock out the (mono) reference track, gain-scaled, replicated across output channels. Silence
    // once exhausted so the capture tail can keep running until Kotlin stops it.
    size_t cursor = mPlaybackCursor;
    const size_t total = mPlayback.size();
    for (int32_t f = 0; f < numFrames; ++f) {
        int16_t s = 0;
        if (cursor < total) {
            int32_t v = static_cast<int32_t>(std::lrintf(mPlayback[cursor] * mGain));
            if (v > 32767) v = 32767;
            if (v < -32768) v = -32768;
            s = static_cast<int16_t>(v);
            ++cursor;
        }
        for (int32_t c = 0; c < ch; ++c) {
            out[f * ch + c] = s;
        }
    }
    mPlaybackCursor = cursor;
    if (cursor >= total && total > 0) {
        mPlaybackComplete.store(true, std::memory_order_relaxed);
    }

    return DataCallbackResult::Continue;
}

size_t FullDuplexEngine::ringPush(const int16_t *src, size_t count) {
    const uint64_t w = mRingWrite.load(std::memory_order_relaxed);
    const uint64_t r = mRingRead.load(std::memory_order_acquire);
    const size_t freeSpace = kRingCapacity - static_cast<size_t>(w - r);
    const size_t n = std::min(count, freeSpace);
    for (size_t i = 0; i < n; ++i) {
        mRing[(w + i) & kRingMask] = src[i];
    }
    mRingWrite.store(w + n, std::memory_order_release);
    return n;
}

size_t FullDuplexEngine::ringPop(int16_t *dst, size_t maxCount) {
    const uint64_t r = mRingRead.load(std::memory_order_relaxed);
    const uint64_t w = mRingWrite.load(std::memory_order_acquire);
    const size_t avail = static_cast<size_t>(w - r);
    const size_t n = std::min(maxCount, avail);
    for (size_t i = 0; i < n; ++i) {
        dst[i] = mRing[(r + i) & kRingMask];
    }
    mRingRead.store(r + n, std::memory_order_release);
    return n;
}

void FullDuplexEngine::drainLoop() {
    std::vector<int16_t> temp(4096);
    auto drainOnce = [&]() -> size_t {
        size_t n = ringPop(temp.data(), temp.size());
        if (n > 0) {
            std::lock_guard<std::mutex> lock(mAccumMutex);
            mAccumulator.insert(mAccumulator.end(), temp.begin(), temp.begin() + n);
        }
        return n;
    };

    // Multi-read timestamp sampling (item 13 (b)): the drain thread is a normal thread, not the
    // audio callback, so getTimestamp is safe here. Spread reads across the session at a fixed
    // cadence so each stream's frame-vs-time line is populated; the offline analysis detects a
    // single-read glitch as an off-line point on that line. Waiting until the streams have actually
    // started (mInputStarted) avoids a guaranteed-failing read during the startup window.
    using clock = std::chrono::steady_clock;
    auto nextTsRead = clock::now() + std::chrono::milliseconds(kTimestampPeriodMs);

    while (mDrainRunning.load(std::memory_order_relaxed)) {
        if (drainOnce() == 0) {
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
        }
        if (mInputStarted.load(std::memory_order_acquire)) {
            auto now = clock::now();
            if (now >= nextTsRead) {
                readStreamTimestampSample();
                nextTsRead = now + std::chrono::milliseconds(kTimestampPeriodMs);
            }
        }
    }
    // Final drain: empty whatever the callback pushed between the last loop iteration and stop().
    while (drainOnce() > 0) {
    }
}

}  // namespace overdub
