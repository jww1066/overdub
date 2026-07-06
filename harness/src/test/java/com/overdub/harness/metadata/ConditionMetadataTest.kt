package com.overdub.harness.metadata

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
        )
        val json = original.toJson()
        val decoded = conditionMetadataFromJson(json)
        assertEquals(original, decoded)
        assertEquals(null, decoded.xrunCount)
        assertEquals(null, decoded.deviceModel)
        assertEquals(null, decoded.streamOffsetMs)
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
        assertEquals(true, json.contains("\"input_preset\""))
        assertEquals(true, json.contains("\"sample_rate\""))
        assertEquals(true, json.contains("\"xrun_count\""))
        assertEquals(true, json.contains("\"device_model\""))
        assertEquals(true, json.contains("\"stream_offset_frames\""))
        assertEquals(true, json.contains("\"stream_offset_ms\""))
        assertEquals(true, json.contains("\"output_timestamp_frames\""))
        assertEquals(true, json.contains("\"input_timestamp_nanos\""))
    }
}
