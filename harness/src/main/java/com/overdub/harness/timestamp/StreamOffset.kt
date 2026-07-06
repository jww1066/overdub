package com.overdub.harness.timestamp

/**
 * The two hardware-timestamp reads (one per full-duplex stream), each a `(framePosition, nanoTime)`
 * pair from Oboe's `getTimestamp(CLOCK_MONOTONIC)` -- a common monotonic clock with the output DAC
 * latency / input ADC latency already folded in (it reports when a frame is actually *heard* /
 * actually *captured*, not when it was enqueued). See test2-step2-plan.md item 10 and
 * doc/guides/on-device-audio.md ("Measure the true alignment between the two full-duplex streams").
 */
data class StreamTimestamps(
    val outputFrames: Long,
    val outputNanos: Long,
    val inputFrames: Long,
    val inputNanos: Long,
)

/**
 * The harness's own per-session output<->input stream start misalignment, derived from a
 * [StreamTimestamps] pair. Expressed both in frames and in milliseconds. This is the term the
 * *product* (one continuous self-measured full-duplex session) does NOT carry but the sweep harness
 * (independently-started stream pair per cell) does; subtracting it from the GCC-PHAT offset offline
 * should leave only the tiny, roughly-constant acoustic flight time.
 */
data class StreamOffset(
    val frames: Double,
    val ms: Double,
)

private const val NANOS_PER_SECOND = 1_000_000_000.0

/**
 * Derives the output<->input stream start misalignment from the two [getTimestamp()][StreamTimestamps]
 * reads, in the **same sign convention as the GCC-PHAT offset** (positive == the captured mic frame
 * index lags the played reference frame index; `mic[n] ~= reference[n - offset]`).
 *
 * Each stream's timestamp is a linear frame<->time map at the shared sample rate `fs`: output frame
 * `k` is *heard* at `t_out + (k - p_out)/fs`, input frame `m` is *captured* at `t_in + (m - p_in)/fs`.
 * Equating the two for the same physical instant and solving for the index gap `(m - k)` that
 * GCC-PHAT recovers, the playback cursor `k` cancels and the gap is a constant:
 *
 * ```
 * offset_frames = (p_in - p_out) + (t_out - t_in) * fs / 1e9
 * ```
 *
 * The two reads need not be simultaneous: each `(framePosition, nanoTime)` pair is internally
 * consistent, so they are combined algebraically at a common reference rather than by assuming the
 * two `getTimestamp` calls happened at the same instant.
 */
fun computeStreamOffset(timestamps: StreamTimestamps, sampleRate: Int): StreamOffset {
    require(sampleRate > 0) { "sampleRate must be positive, was $sampleRate" }
    val framesFromPosition = (timestamps.inputFrames - timestamps.outputFrames).toDouble()
    val framesFromClock =
        (timestamps.outputNanos - timestamps.inputNanos).toDouble() * sampleRate / NANOS_PER_SECOND
    val frames = framesFromPosition + framesFromClock
    val ms = frames / sampleRate * 1000.0
    return StreamOffset(frames = frames, ms = ms)
}
