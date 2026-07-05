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

    /** oboe::Result::OK, the success value returned by [nativeOpen] / [nativeStart]. */
    const val RESULT_OK = 0

    /** Retained linkage smoke check from Stage 2 step 1; returns "OK" when Oboe is callable. */
    external fun nativeCheckOboeLinked(): String

    /**
     * Opens the full-duplex streams. [outputDeviceId]/[inputDeviceId] force a route when >= 0 (the
     * Oboe analogue of setPreferredDevice); pass -1 to leave it unspecified. Returns an oboe::Result
     * ([RESULT_OK] on success).
     */
    external fun nativeOpen(
        sampleRate: Int,
        channelCount: Int,
        inputPreset: Int,
        outputDeviceId: Int,
        inputDeviceId: Int,
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

    /** The accumulated captured 16-bit PCM (valid after [nativeStop]). */
    external fun nativeGetCapturedSamples(): ShortArray

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
}
