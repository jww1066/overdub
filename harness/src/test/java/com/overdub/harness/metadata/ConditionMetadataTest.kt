package com.overdub.harness.metadata

import com.overdub.harness.timestamp.StreamTimestamps
import org.junit.Assert.assertEquals
import org.junit.Test

class ConditionMetadataTest {

    private fun sample() = ConditionMetadata(
        conditionId = "conversational_armslength_faceup_none",
        playbackVolume = 0.6,
        distanceCm = 50,
        orientation = "face-up",
        obstruction = "none",
        outputRoute = "speaker",
        inputRoute = "builtin_mic",
        inputPreset = "voice_recognition",
        sampleRate = 48000,
        xrunCount = 0,
        deviceModel = "Pixel 10",
        streamVolumeIndex = 25,
        timestamp = 1751000000000L,
        outputTimestampFrames = 480_000L,
        outputTimestampNanos = 10_000_000_000L,
        inputTimestampFrames = 475_200L,
        inputTimestampNanos = 10_000_000_000L,
        streamOffsetFrames = -4800.0,
        streamOffsetMs = -100.0,
        reflectorGeometry = "wall",
    )

    @Test
    fun `round-trips through JSON with all fields present`() {
        val original = sample()
        val decoded = conditionMetadataFromJson(original.toJson())
        assertEquals(original, decoded)
    }

    @Test
    fun `round-trips with optional fields missing`() {
        val original = sample().copy(
            xrunCount = null,
            deviceModel = null,
            outputTimestampFrames = null,
            outputTimestampNanos = null,
            inputTimestampFrames = null,
            inputTimestampNanos = null,
            streamOffsetFrames = null,
            streamOffsetMs = null,
            reflectorGeometry = null,
        )
        val json = original.toJson()
        val decoded = conditionMetadataFromJson(json)
        assertEquals(original, decoded)
        assertEquals(null, decoded.xrunCount)
        assertEquals(null, decoded.deviceModel)
        assertEquals(null, decoded.streamOffsetMs)
        assertEquals(null, decoded.reflectorGeometry)
    }

    @Test
    fun `legacy sidecar without reflector_geometry decodes as unknown`() {
        // The 2026-07-05 sweep's sidecars predate the field (item 9); they must decode with
        // reflectorGeometry == null (unknown), not fail or invent a geometry.
        val legacyJson = sample().copy(reflectorGeometry = null).toJson()
        assertEquals(false, legacyJson.contains("reflector_geometry"))
        assertEquals(null, conditionMetadataFromJson(legacyJson).reflectorGeometry)
    }

    @Test
    fun `legacy sidecar without input_route decodes as unknown`() {
        // Sidecars written before the electrical-loopback rig's input-route field existed must
        // decode with inputRoute == "unknown" (the same honesty convention as reflector_geometry),
        // not silently claim builtin_mic for a run that never recorded it.
        val legacyJson = """
            {"condition_id":"c","playback_volume":0.6,"distance_cm":50,"orientation":"o",
             "obstruction":"n","output_route":"speaker","input_preset":"voice_recognition",
             "sample_rate":48000,"timestamp":1}
        """.trimIndent()
        assertEquals(false, legacyJson.contains("input_route"))
        assertEquals("unknown", conditionMetadataFromJson(legacyJson).inputRoute)
    }

    @Test
    fun `round-trips with an unusual condition id string`() {
        val original = sample().copy(
            conditionId = "quiet_pocketed_face-down_\"weird\"_ünïcode_id 123",
        )
        val decoded = conditionMetadataFromJson(original.toJson())
        assertEquals(original, decoded)
    }

    @Test
    fun `serialized JSON uses expected snake_case field names`() {
        val json = sample().toJson()
        assertEquals(true, json.contains("\"condition_id\""))
        assertEquals(true, json.contains("\"playback_volume\""))
        assertEquals(true, json.contains("\"distance_cm\""))
        assertEquals(true, json.contains("\"output_route\""))
        assertEquals(true, json.contains("\"input_route\""))
        assertEquals(true, json.contains("\"input_preset\""))
        assertEquals(true, json.contains("\"sample_rate\""))
        assertEquals(true, json.contains("\"xrun_count\""))
        assertEquals(true, json.contains("\"device_model\""))
        assertEquals(true, json.contains("\"stream_offset_frames\""))
        assertEquals(true, json.contains("\"stream_offset_ms\""))
        assertEquals(true, json.contains("\"output_timestamp_frames\""))
        assertEquals(true, json.contains("\"input_timestamp_nanos\""))
        assertEquals(true, json.contains("\"reflector_geometry\""))
    }

    @Test
    fun `round-trips a multi-read timestamp_samples series`() {
        // item 13 (b): the periodic getTimestamp series must survive a JSON round-trip element-for-
        // element, including ordering (the offline line-fit depends on the series being in capture
        // order, and kotlinx.serialization preserves list order).
        val series = listOf(
            StreamTimestamps(100_000L, 1_000_000_000L, 99_000L, 1_000_000_500L),
            StreamTimestamps(172_000L, 2_500_000_000L, 171_000L, 2_500_000_400L),
            StreamTimestamps(244_000L, 4_000_000_000L, 243_000L, 4_000_000_300L),
        )
        val original = sample().copy(timestampSamples = series)
        val decoded = conditionMetadataFromJson(original.toJson())
        assertEquals(original, decoded)
        assertEquals(3, decoded.timestampSamples?.size)
        assertEquals(172_000L, decoded.timestampSamples?.get(1)?.outputFrames)
    }

    @Test
    fun `timestamp_samples defaults to null and is omitted when absent`() {
        // Legacy sidecars (pre-item-13 (b)) decode with timestampSamples == null, and a sidecar that
        // never had the field round-trips to a JSON string without it (so old analysis tools that
        // don't know the field aren't perturbed).
        val legacy = sample().copy(timestampSamples = null)
        val json = legacy.toJson()
        assertEquals(false, json.contains("\"timestamp_samples\""))
        assertEquals(null, conditionMetadataFromJson(json).timestampSamples)
    }
}
