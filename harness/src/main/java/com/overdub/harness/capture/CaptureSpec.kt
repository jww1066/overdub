package com.overdub.harness.capture

import com.overdub.harness.condition.Condition

/**
 * The input-stream preset a capture requests (a *request* — OEMs honor it inconsistently, which is
 * why the sidecar records the label). [VOICE_RECOGNITION] is the sweep's canonical preset
 * (Components §2: defeats OEM AGC/NS); [UNPROCESSED] is the capture-headroom probe's alternate HAL
 * gain path, designed for measurement with defined sensitivity/headroom where supported.
 * [nativeValue] mirrors oboe::InputPreset (which mirrors android.media.MediaRecorder.AudioSource).
 */
enum class CaptureInputPreset(val nativeValue: Int, val label: String) {
    VOICE_RECOGNITION(6, "voice_recognition"),
    UNPROCESSED(9, "unprocessed"),
}

/**
 * What one capture run actually varies, decoupled from the 36-cell sweep matrix: the identity used
 * for filenames/sidecar `condition_id`, the playback gain, and the physical-arrangement strings
 * recorded in the sidecar. Matrix cells map 1:1 via [toCaptureSpec]; non-matrix runs (the item-12
 * vocal take) supply their own spec so their metadata stays honest instead of masquerading as a
 * sweep cell. Pure Kotlin (Tier 1), no framework dependency.
 */
data class CaptureSpec(
    val captureId: String,
    val playbackGain: Double,
    val distanceCm: Int,
    val orientation: String,
    val obstruction: String,
    /**
     * When true, playback is forced to a connected headset (wired/USB) instead of the built-in
     * speaker — the product-realistic headphone-session shape (headset out + built-in mic in) for
     * the item-13 (c) headset-route timestamp study. Capture hard-fails if no headset is connected
     * rather than silently falling back to the speaker. Sweep cells and the vocal take keep the
     * default (built-in speaker forced).
     */
    val outputToHeadset: Boolean = false,
    /**
     * When true, the input stream is opened as Float instead of I16 and the capture is written as
     * a float32 WAV — the capture-headroom diagnostic (design-summary.md "clip census"): if the
     * int16 rail on kick transients is digital (conversion/gain), the float capture is un-railed;
     * if the analog front-end saturates, float rails too. Sweep cells keep I16 so sweep data stays
     * one format.
     */
    val captureFloat: Boolean = false,
    /** Input preset to request; sweep cells keep the canonical [CaptureInputPreset.VOICE_RECOGNITION]. */
    val inputPreset: CaptureInputPreset = CaptureInputPreset.VOICE_RECOGNITION,
    /**
     * When true, the input stream is forced to a connected USB input device instead of the
     * built-in mic — the electrical-loopback rig (prototype-plan.md Test 1 / Test 1a): a PassMark
     * TRRS loopback plug into a USB-C audio adapter wires the adapter's own output directly back
     * into its own input, so both ends of the full-duplex stream must be the USB device, not the
     * phone's speaker/mic. Capture hard-fails if no USB input device is present rather than
     * silently falling back to the built-in mic. Sweep cells, the vocal take, and the headset-route
     * study all keep the default (built-in mic input).
     */
    val inputFromUsb: Boolean = false,
)

fun Condition.toCaptureSpec(): CaptureSpec = CaptureSpec(
    captureId = conditionId,
    playbackGain = volume.gainFraction,
    distanceCm = distance.approxCm,
    orientation = orientation.label,
    obstruction = obstruction.label,
)

/**
 * Capture-headroom probe variant of a matrix cell (the diagnostic experiment for the ADC-rail
 * finding — `doc/guides/offline-dsp.md` "census raw captures"): same physical arrangement and
 * playback gain as the cell, but with the requested capture format/preset arm, and a `captureId`
 * that names the arm so probe files can never masquerade as sweep data.
 */
fun Condition.toHeadroomProbeSpec(
    captureFloat: Boolean,
    inputPreset: CaptureInputPreset,
): CaptureSpec = toCaptureSpec().copy(
    captureId = "headroom_${conditionId}_${if (captureFloat) "float32" else "i16"}_${inputPreset.label}",
    captureFloat = captureFloat,
    inputPreset = inputPreset,
)

/**
 * Record-only mode for the item-12 vocal-interference study: playback gain 0.0 (the output stream
 * runs but emits silence, so the input chain -- same mic, same `VoiceRecognition` preset -- is
 * identical to a sweep capture while nothing acoustic leaves the phone). The performer monitors the
 * reference on headphones from a *different* device and performs close-mic into this one.
 *
 * `distanceCm` here is approximate mouth-to-mic distance -- NOT the sweep's distance-to-reflector
 * axis; the distinct `captureId` is what tells a sidecar reader which semantics apply.
 */
val VOCAL_TAKE_SPEC = CaptureSpec(
    captureId = "vocal_take",
    playbackGain = 0.0,
    distanceCm = 10,
    orientation = "handheld",
    obstruction = "none",
)

/**
 * Headset-route mode for the item-13 (c) timestamp-variance study (prototype-plan.md Test 1a
 * "Interim timestamp-variance plan" step 3): the reference plays into a connected wired/USB
 * headset while the built-in mic records — the exact stream/route shape a product headphone
 * session uses. The mic hears only the room (no speaker bleed, so the calibration click cannot
 * anchor and a sub-floor RMS is EXPECTED); the data of interest is purely the per-stream
 * `getTimestamp` statistics on this route. `distanceCm` is meaningless here (0); the distinct
 * `captureId` tells sidecar readers which semantics apply, same convention as [VOCAL_TAKE_SPEC].
 */
val HEADSET_ROUTE_SPEC = CaptureSpec(
    captureId = "headset_route",
    playbackGain = 0.6,
    distanceCm = 0,
    orientation = "faceup",
    obstruction = "none",
    outputToHeadset = true,
)

/**
 * Electrical-loopback mode for Test 1 / Test 1a (prototype-plan.md "Hardware status"): the
 * reference plays into the USB adapter and is read back on the *same* adapter's input line
 * through a PassMark TRRS loopback plug, with no acoustic path at all — the instrument for the
 * continuous-buffer scheduling-seam question (Test 1) and the ground truth for the AAudio
 * self-reported-latency question (Test 1a) on the one route with no calibration-click fallback.
 * `distanceCm`/`orientation`/`obstruction` are meaningless here (the phone doesn't move between
 * reps); the distinct `captureId` tells sidecar readers which semantics apply, same convention as
 * [HEADSET_ROUTE_SPEC].
 */
val LOOPBACK_SPEC = CaptureSpec(
    captureId = "loopback",
    playbackGain = 0.6,
    distanceCm = 0,
    orientation = "n/a",
    obstruction = "none",
    outputToHeadset = true,
    inputFromUsb = true,
)
