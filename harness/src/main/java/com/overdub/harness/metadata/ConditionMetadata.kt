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
)

private val json = Json { ignoreUnknownKeys = true }

fun ConditionMetadata.toJson(): String = json.encodeToString(ConditionMetadata.serializer(), this)

fun conditionMetadataFromJson(text: String): ConditionMetadata =
    json.decodeFromString(ConditionMetadata.serializer(), text)
