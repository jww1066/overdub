package com.overdub.harness.metadata

import kotlinx.serialization.Serializable
import kotlinx.serialization.SerialName
import kotlinx.serialization.json.Json

/**
 * JSON sidecar written next to each capture's WAV file, per test2-step2-plan.md Components §2.
 * [xrunCount] and [deviceModel] are nullable: a capture can be written before either is known
 * (XRun count is only available after the streams close; device model query can fail on some
 * OEMs), and a missing value here must not be indistinguishable from a real zero/empty string.
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
    @SerialName("timestamp") val timestamp: Long,
)

private val json = Json { ignoreUnknownKeys = true }

fun ConditionMetadata.toJson(): String = json.encodeToString(ConditionMetadata.serializer(), this)

fun conditionMetadataFromJson(text: String): ConditionMetadata =
    json.decodeFromString(ConditionMetadata.serializer(), text)
