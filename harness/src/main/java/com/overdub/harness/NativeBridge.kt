package com.overdub.harness

/**
 * JNI entry points into the C++ [FullDuplexEngine][native_engine.cpp] (test2-step2-plan.md Stage 2
 * step 2). The native side owns the real-time-critical audio path (Oboe full-duplex stream,
 * lock-free ring buffer, XRun counting); the WAV/JSON/RMS work stays on the Kotlin side and is
 * orchestrated by [com.overdub.harness.capture.CaptureEngine], which is the intended caller of this
 * object rather than callers invoking these lifecycle functions directly.
 *
 * A single native engine instance backs these calls, so a capture must run to completion
 * (open -> setPlayback -> start -> ... -> stop -> close) before the next one starts.
 *
 * Not yet verified on a physical device -- see CaptureEngine and test2-step2-plan.md "Next steps".
 */
object NativeBridge {
    init {
        System.loadLibrary("overdub_harness")
    }

    /** Oboe [InputPreset::VoiceRecognition] (Components §2: defeats OEM AGC/NS). */
    const val INPUT_PRESET_VOICE_RECOGNITION = 6

    /** Oboe [InputPreset::Unprocessed] (the capture-headroom probe's alternate HAL gain path). */
    const val INPUT_PRESET_UNPROCESSED = 9

    /** oboe::Result::OK, the success value returned by [nativeOpen] / [nativeStart]. */
    const val RESULT_OK = 0

    /** Retained linkage smoke check from Stage 2 step 1; returns "OK" when Oboe is callable. */
    external fun nativeCheckOboeLinked(): String

    /**
     * Opens the full-duplex streams. [outputDeviceId]/[inputDeviceId] force a route when >= 0 (the
     * Oboe analogue of setPreferredDevice); pass -1 to leave it unspecified. [captureFloat] opens
     * the INPUT stream as Float instead of I16 (the capture-headroom diagnostic; playback stays
     * I16 either way) — captured data must then be read via [nativeGetCapturedFloatSamples], not
     * [nativeGetCapturedSamples]. Returns an oboe::Result ([RESULT_OK] on success).
     */
    external fun nativeOpen(
        sampleRate: Int,
        channelCount: Int,
        inputPreset: Int,
        outputDeviceId: Int,
        inputDeviceId: Int,
        captureFloat: Boolean,
    ): Int

    /** Loads the reference track and sets the playback gain fraction (0.0–1.0). */
    external fun nativeSetPlayback(samples: ShortArray, gain: Float)

    /** Starts playback + capture; returns an oboe::Result ([RESULT_OK] on success). */
    external fun nativeStart(): Int

    /** Stops the streams, drains the ring, and latches the XRun count. */
    external fun nativeStop()

    /** Closes the streams and releases the native engine. */
    external fun nativeClose()

    /** True once the whole reference track has been clocked out. */
    external fun nativeIsPlaybackComplete(): Boolean

    /** The accumulated captured 16-bit PCM (valid after [nativeStop]; I16 mode only). */
    external fun nativeGetCapturedSamples(): ShortArray

    /** The accumulated captured float PCM, full scale ±1.0 (valid after [nativeStop]; Float mode only). */
    external fun nativeGetCapturedFloatSamples(): FloatArray

    /** Max XRun count across both streams (latched at stop); -1 if unavailable. */
    external fun nativeGetXRunCount(): Int

    /** Frames dropped because the ring overflowed; should be 0, non-zero means a contaminated run. */
    external fun nativeGetDroppedFrameCount(): Long

    /** Actual output-stream device id, for resolving/verifying the route Kotlin-side. */
    external fun nativeGetOutputDeviceId(): Int

    /** Actual input-stream device id. */
    external fun nativeGetInputDeviceId(): Int

    /** Actual negotiated output sample rate (may differ from the requested rate). */
    external fun nativeGetActualSampleRate(): Int

    /**
     * True if both streams' [getTimestamp()][nativeGetOutputTimestampFrames] reads succeeded while
     * RUNNING (latched at [nativeStop]). False when getTimestamp is unavailable/unsupported on the
     * device -- callers then omit the stream-offset fields from metadata rather than logging a
     * bogus value (see test2-step2-plan.md item 10; getTimestamp accuracy is itself device-dependent).
     */
    external fun nativeHasStreamTimestamps(): Boolean

    /** Output-stream timestamp frame position (valid only when [nativeHasStreamTimestamps]). */
    external fun nativeGetOutputTimestampFrames(): Long

    /** Output-stream timestamp nanoTime on CLOCK_MONOTONIC (valid only when [nativeHasStreamTimestamps]). */
    external fun nativeGetOutputTimestampNanos(): Long

    /** Input-stream timestamp frame position (valid only when [nativeHasStreamTimestamps]). */
    external fun nativeGetInputTimestampFrames(): Long

    /** Input-stream timestamp nanoTime on CLOCK_MONOTONIC (valid only when [nativeHasStreamTimestamps]). */
    external fun nativeGetInputTimestampNanos(): Long

    /**
     * Multi-read timestamp series (test2-step2-plan.md item 13 (b)): a flat array
     * `[out_frames0, out_nanos0, in_frames0, in_nanos0, out_frames1, ...]` of periodic `getTimestamp`
     * reads taken across the session by the drain thread. Empty when `getTimestamp` is unsupported or
     * the session was too short for a read; non-empty is the population the offline analysis fits a
     * per-stream frame-vs-time line to, detecting a single-read glitch as an off-line point. Independent
     * of the single latched [nativeHasStreamTimestamps] read, which is kept for back-compat.
     */
    external fun nativeGetTimestampSamples(): LongArray
}
