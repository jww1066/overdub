#ifndef OVERDUB_HARNESS_NATIVE_ENGINE_H
#define OVERDUB_HARNESS_NATIVE_ENGINE_H

#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>

#include <oboe/Oboe.h>

namespace overdub {

// Full-duplex Oboe engine for the Test 2 bleed-capture harness (test2-step2-plan.md Components 2).
//
// Plays a preloaded reference track through the output stream while synchronously capturing the
// input stream from that same output data callback (Oboe's recommended full-duplex pattern), so the
// harness reproduces the "single continuous stream, no independently-scheduled players" principle
// Test 1 validates rather than introducing its own scheduling seam.
//
// Real-time discipline (CLAUDE.md "Main-thread discipline" / the callback must stay non-blocking and
// allocation-free): the audio callback only touches lock-free state -- a plain playback cursor it
// alone owns, and a single-producer/single-consumer ring buffer it alone writes. It performs no
// allocation, no locking, and no file I/O. A dedicated drain thread moves captured frames out of the
// ring into an unbounded accumulator. The WAV/JSON/RMS work is done on the Kotlin side of the JNI
// bridge (reusing WavWriter/ConditionMetadata/Rms), never here.
//
// Not yet exercised on a physical device: no device has been connected to this repo, so none of the
// on-device behavior below (stream open in LowLatency/Exclusive, XRun counting, actual capture) has
// been verified -- only that it compiles and links. See test2-step2-plan.md "Next steps" items 2-4.
class FullDuplexEngine : public oboe::AudioStreamDataCallback {
public:
    FullDuplexEngine();
    ~FullDuplexEngine() override;

    // Opens both streams (LowLatency, Exclusive, the given channel count and sample rate). The
    // output stream is always I16 (the reference asset's format); the input stream is I16 by
    // default, or Float when captureFloat is set -- the capture-headroom diagnostic
    // (design-summary.md "clip census" / capture-headroom): if the int16 rail observed on kick
    // transients is a digital conversion/gain artifact, a Float input stream captures the same
    // signal un-railed; if the analog front-end saturates, Float rails too and no format helps.
    // The input stream uses the given InputPreset (VoiceRecognition per Components 2, to defeat OEM
    // AGC/NS that would mask the SNR degradation the sweep exists to map). outputDeviceId /
    // inputDeviceId force a specific route when >= 0 (the Oboe equivalent of setPreferredDevice --
    // Kotlin resolves the built-in speaker/mic ids); pass -1 to leave the route unspecified.
    // Returns an oboe::Result cast to int (oboe::Result::OK == 0 on success).
    int open(int32_t sampleRate, int32_t channelCount, int32_t inputPreset,
             int32_t outputDeviceId, int32_t inputDeviceId, bool captureFloat);

    // Copies the reference track into the playback buffer and sets the playback gain fraction
    // (0.0-1.0, applied per-sample in the callback -- the Oboe analogue of AudioTrack.setVolume()
    // named in Components 2). Must be called before start().
    void setPlayback(const int16_t *samples, size_t count, float gain);

    // Starts both streams and launches the drain thread. Returns an oboe::Result cast to int.
    int start();

    // Stops both streams, joins the drain thread (final-draining the ring), and latches the XRun
    // counts. Safe to call more than once.
    void stop();

    // Closes both streams. Call after stop().
    void close();

    // True once the whole reference track has been clocked out of the callback.
    bool isPlaybackComplete() const { return mPlaybackComplete.load(std::memory_order_relaxed); }

    // Number of captured samples accumulated so far (valid after stop(); counts whichever of the
    // int16/float accumulators the open() mode filled).
    size_t capturedSampleCount();

    // Copies up to maxCount accumulated int16 samples into dst; returns the number copied.
    // Valid only when open() was called with captureFloat == false.
    size_t copyCapturedSamples(int16_t *dst, size_t maxCount);

    // Float-mode variant of copyCapturedSamples(); valid only when captureFloat == true.
    size_t copyCapturedSamplesFloat(float *dst, size_t maxCount);

    // True when open() put the input stream in Float mode.
    bool isCaptureFloat() const { return mCaptureFloat; }

    // Max XRun count across both streams (latched at stop()); -1 if unavailable.
    int32_t xRunCount() const { return mXRunCount; }

    // Frames the callback had to drop because the ring was full (should stay 0; non-zero means the
    // drain thread fell behind and the capture is contaminated). Diagnostic only.
    int64_t droppedFrameCount() const { return mDroppedFrames.load(std::memory_order_relaxed); }

    int32_t outputDeviceId() const { return mOutputDeviceId; }
    int32_t inputDeviceId() const { return mInputDeviceId; }
    int32_t actualSampleRate() const { return mActualSampleRate; }

    // Hardware stream timestamps (test2-step2-plan.md item 10), latched once while both streams are
    // RUNNING (read in stop() before requestStop). Each is a (framePosition, nanoTime) pair on a
    // common CLOCK_MONOTONIC with DAC/ADC latency folded in, so the output/input frame relationship
    // recovers the per-session start misalignment the two independently-started streams add on top of
    // the acoustic round-trip. hasStreamTimestamps() is false if getTimestamp() failed/was
    // unsupported; even when it succeeds, platform-reported latency has anecdotal device-specific
    // inaccuracy (a single ~100 ms discrepancy reported on a moto g(20)), so a loopback stays the
    // independent honesty check. The derived-offset arithmetic lives Kotlin-side so it is
    // JVM-unit-testable.
    bool hasStreamTimestamps() const { return mHasTimestamps.load(std::memory_order_relaxed); }
    int64_t outputTimestampFrames() const { return mOutputTsFrames; }
    int64_t outputTimestampNanos() const { return mOutputTsNanos; }
    int64_t inputTimestampFrames() const { return mInputTsFrames; }
    int64_t inputTimestampNanos() const { return mInputTsNanos; }

    // Multi-read timestamp series (test2-step2-plan.md item 13 (b)): the drain thread reads
    // getTimestamp() on both streams periodically while RUNNING, so a single-read glitch shows up
    // as an off-line point on a stream's frame-vs-time line without needing any cross-run referent
    // (the instrument item 13 (a)'s single-read decomposition showed was needed). Returned as a
    // flat array [out_frames0, out_nanos0, in_frames0, in_nanos0, out_frames1, ...] for trivial JNI
    // marshalling; empty when getTimestamp is unsupported or the session was too short for a read.
    // Independent of the single latched stop() read above, which is kept for back-compat with the
    // item-10 analysis scripts.
    std::vector<int64_t> timestampSamplesFlat();

    // oboe::AudioStreamDataCallback
    oboe::DataCallbackResult onAudioReady(oboe::AudioStream *oboeStream, void *audioData,
                                          int32_t numFrames) override;

private:
    // --- Lock-free SPSC ring buffer (producer: audio callback; consumer: drain thread) ---
    // Templated over the sample type: exactly one of mRing/mRingF is active per engine instance
    // (open() decides), and both share the same write/read counters, so the I16 path stays
    // bit-identical to the pre-float-mode code.
    template <typename T>
    size_t ringPush(std::vector<T> &ring, const T *src, size_t count);
    template <typename T>
    size_t ringPop(std::vector<T> &ring, T *dst, size_t maxCount);

    void drainLoop();

    // Reads getTimestamp() on both streams (once, latched via mHasTimestamps). No-op unless both
    // reads succeed, so a repeat stop() -- when the streams are no longer RUNNING and getTimestamp
    // would fail -- can't clobber a good earlier read.
    void readStreamTimestamps();

    // One periodic multi-read sample (item 13 (b)): reads both streams and, on success, appends a
    // TimestampSample under mTsMutex. Returns true if both reads succeeded. Called from the drain
    // thread, which is a normal thread (not the audio callback), so getTimestamp is safe here.
    bool readStreamTimestampSample();


    static constexpr size_t kRingCapacity = 1u << 16;  // 65536 samples (~1.3s mono at 48k)
    static constexpr size_t kRingMask = kRingCapacity - 1;
    std::vector<int16_t> mRing;
    std::vector<float> mRingF;  // allocated in open() only when captureFloat
    std::atomic<uint64_t> mRingWrite{0};
    std::atomic<uint64_t> mRingRead{0};
    std::atomic<int64_t> mDroppedFrames{0};

    std::shared_ptr<oboe::AudioStream> mOutputStream;
    std::shared_ptr<oboe::AudioStream> mInputStream;

    int32_t mChannelCount = 1;
    int32_t mActualSampleRate = 0;
    int32_t mOutputDeviceId = -1;
    int32_t mInputDeviceId = -1;
    int32_t mXRunCount = -1;

    // Playback buffer + cursor. mPlayback is set before start() and only read afterwards; the cursor
    // is touched only by the callback thread.
    std::vector<int16_t> mPlayback;
    size_t mPlaybackCursor = 0;
    float mGain = 1.0f;
    std::atomic<bool> mPlaybackComplete{false};

    // Gates input reads in the callback: false until start() has actually started the input stream,
    // so the output callback (which starts first, so the drainer is live before input data arrives)
    // doesn't read a not-yet-started input stream during the startup window.
    std::atomic<bool> mInputStarted{false};

    // Scratch buffer the callback reads the input stream into (sized in open(), never in the
    // callback, so the callback stays allocation-free). One per capture format; only the one
    // matching mCaptureFloat is sized.
    std::vector<int16_t> mInputScratch;
    std::vector<float> mInputScratchF;

    // Capture accumulator, filled by the drain thread, read by Kotlin after stop(). Same
    // one-of-two rule as the scratch buffers.
    std::mutex mAccumMutex;
    std::vector<int16_t> mAccumulator;
    std::vector<float> mAccumulatorF;

    // Input-stream sample format chosen at open() (see open()'s captureFloat doc).
    bool mCaptureFloat = false;

    std::thread mDrainThread;
    std::atomic<bool> mDrainRunning{false};

    // Latched hardware timestamps (see hasStreamTimestamps() / readStreamTimestamps()).
    int64_t mOutputTsFrames = -1;
    int64_t mOutputTsNanos = -1;
    int64_t mInputTsFrames = -1;
    int64_t mInputTsNanos = -1;
    std::atomic<bool> mHasTimestamps{false};

    // Multi-read series (item 13 (b)): one entry per successful periodic read of both streams.
    // Guarded by mTsMutex (written from the drain thread, read from the Kotlin thread after stop()).
    struct TimestampSample {
        int64_t outFrames;
        int64_t outNanos;
        int64_t inFrames;
        int64_t inNanos;
    };
    std::mutex mTsMutex;
    std::vector<TimestampSample> mTimestampSamples;

    // Spacing between multi-read samples (item 13 (b) targets ~10 reads across a ~16s capture).
    static constexpr int kTimestampPeriodMs = 1500;
};

}  // namespace overdub

#endif  // OVERDUB_HARNESS_NATIVE_ENGINE_H
