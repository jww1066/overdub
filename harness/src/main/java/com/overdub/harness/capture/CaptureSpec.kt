package com.overdub.harness.capture

import com.overdub.harness.condition.Condition

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
)

fun Condition.toCaptureSpec(): CaptureSpec = CaptureSpec(
    captureId = conditionId,
    playbackGain = volume.gainFraction,
    distanceCm = distance.approxCm,
    orientation = orientation.label,
    obstruction = obstruction.label,
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
