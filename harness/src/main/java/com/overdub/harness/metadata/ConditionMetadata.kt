package com.overdub.harness.metadata

import kotlinx.serialization.Serializable
import kotlinx.serialization.SerialName
import kotlinx.serialization.json.Json

/**
 * JSON sidecar written next to each capture's WAV file, per test2-step2-plan.md Components §2.
 * [xrunCount], [deviceModel], and [streamVolumeIndex] are nullable: a capture can be written before
 * any of them is known (XRun count is only available after the streams close; device model query
 * can fail on some OEMs; the pinned stream-volume index is absent if pinning was skipped), and a
 * missing value here must not be indistinguishable from a real zero/empty string.
 *
 * [playbackVolume] is the programmatic gain fraction applied per-sample in the engine (Components
 * §2's AudioTrack.setVolume() analogue). [streamVolumeIndex] records the fixed STREAM_MUSIC index
 * the harness pins at startup, so `playback_volume` is reproducible in absolute terms rather than
 * only relative to whatever the OS volume slider happened to be at.
 *
 * The stream-timestamp fields (test2-step2-plan.md item 10) are all nullable together: they are
 * present only when `getTimestamp()` succeeded on both streams (device-dependent). [streamOffsetMs]
 * is the derived per-session output<->input start misalignment; subtracting it from this cell's
 * GCC-PHAT offset offline decomposes the 61-151 ms cross-cell spread into harness start-jitter
 * (removable) vs real alignment error. The raw `*TimestampFrames`/`*TimestampNanos` pairs are logged
 * so the derivation is auditable and re-derivable, not just the collapsed scalar.
 */
@Serializable
data class ConditionMetadata(
    @SerialName("condition_id") val conditionId: String,
    @SerialName("playback_volume") val playbackVolume: Double,
    @SerialName("distance_cm") val distanceCm: Int,
    @SerialName("orientation") val orientation: String,
    @SerialName("obstruction") val obstruction: String,
    @SerialName("output_route") val outputRoute: String,
    @SerialName("input_preset") val inputPreset: String,
    @SerialName("sample_rate") val sampleRate: Int,
    @SerialName("xrun_count") val xrunCount: Int? = null,
    @SerialName("device_model") val deviceModel: String? = null,
    @SerialName("stream_volume_index") val streamVolumeIndex: Int? = null,
    @SerialName("timestamp") val timestamp: Long,
    @SerialName("output_timestamp_frames") val outputTimestampFrames: Long? = null,
    @SerialName("output_timestamp_nanos") val outputTimestampNanos: Long? = null,
    @SerialName("input_timestamp_frames") val inputTimestampFrames: Long? = null,
    @SerialName("input_timestamp_nanos") val inputTimestampNanos: Long? = null,
    @SerialName("stream_offset_frames") val streamOffsetFrames: Double? = null,
    @SerialName("stream_offset_ms") val streamOffsetMs: Double? = null,
)

private val json = Json { ignoreUnknownKeys = true }

fun ConditionMetadata.toJson(): String = json.encodeToString(ConditionMetadata.serializer(), this)

fun conditionMetadataFromJson(text: String): ConditionMetadata =
    json.decodeFromString(ConditionMetadata.serializer(), text)
