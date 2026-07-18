package com.overdub.harness.capture

import com.overdub.harness.condition.BASELINE_CONDITION
import com.overdub.harness.condition.generateConditionMatrix
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CaptureSpecTest {

    @Test
    fun `baseline condition maps to an equivalent spec`() {
        val spec = BASELINE_CONDITION.toCaptureSpec()
        assertEquals(BASELINE_CONDITION.conditionId, spec.captureId)
        assertEquals(BASELINE_CONDITION.volume.gainFraction, spec.playbackGain, 0.0)
        assertEquals(BASELINE_CONDITION.distance.approxCm, spec.distanceCm)
        assertEquals(BASELINE_CONDITION.orientation.label, spec.orientation)
        assertEquals(BASELINE_CONDITION.obstruction.label, spec.obstruction)
    }

    @Test
    fun `every matrix cell round-trips its identity and gain through the spec`() {
        generateConditionMatrix().forEach { condition ->
            val spec = condition.toCaptureSpec()
            assertEquals(condition.conditionId, spec.captureId)
            assertEquals(condition.volume.gainFraction, spec.playbackGain, 0.0)
        }
    }

    @Test
    fun `matrix cells and the vocal take keep the forced speaker route`() {
        // outputToHeadset must stay false everywhere except the explicit headset-route spec — a
        // sweep cell silently routing to a headset would invalidate its bleed data.
        generateConditionMatrix().forEach { assertTrue(!it.toCaptureSpec().outputToHeadset) }
        assertTrue(!VOCAL_TAKE_SPEC.outputToHeadset)
    }

    @Test
    fun `headset route spec targets the headset and is not a matrix cell`() {
        assertTrue(HEADSET_ROUTE_SPEC.outputToHeadset)
        assertEquals("headset_route", HEADSET_ROUTE_SPEC.captureId)
        val matrixIds = generateConditionMatrix().map { it.conditionId }.toSet()
        assertTrue("headset_route collides with a matrix cell id", HEADSET_ROUTE_SPEC.captureId !in matrixIds)
    }

    @Test
    fun `sweep cells stay i16 with the canonical voice-recognition preset`() {
        // Sweep data must remain one format/preset — a cell silently captured as float32 or
        // through a different HAL gain path would not be comparable with the rest of the matrix.
        generateConditionMatrix().forEach {
            val spec = it.toCaptureSpec()
            assertTrue(!spec.captureFloat)
            assertEquals(CaptureInputPreset.VOICE_RECOGNITION, spec.inputPreset)
        }
    }

    @Test
    fun `headroom probe spec keeps the cell's arrangement but names the arm`() {
        val spec = BASELINE_CONDITION.toHeadroomProbeSpec(
            captureFloat = true,
            inputPreset = CaptureInputPreset.UNPROCESSED,
        )
        // Same physical arrangement and gain as the cell (the probe varies only the capture path).
        assertEquals(BASELINE_CONDITION.volume.gainFraction, spec.playbackGain, 0.0)
        assertEquals(BASELINE_CONDITION.distance.approxCm, spec.distanceCm)
        assertEquals(BASELINE_CONDITION.orientation.label, spec.orientation)
        // The arm is named in the id, and the id can never collide with a matrix cell id, so probe
        // files cannot masquerade as sweep data.
        assertEquals("headroom_${BASELINE_CONDITION.conditionId}_float32_unprocessed", spec.captureId)
        assertTrue(spec.captureFloat)
        assertEquals(CaptureInputPreset.UNPROCESSED, spec.inputPreset)
        val matrixIds = generateConditionMatrix().map { it.conditionId }.toSet()
        assertTrue("probe id collides with a matrix cell id", spec.captureId !in matrixIds)

        val control = BASELINE_CONDITION.toHeadroomProbeSpec(
            captureFloat = false,
            inputPreset = CaptureInputPreset.VOICE_RECOGNITION,
        )
        assertEquals("headroom_${BASELINE_CONDITION.conditionId}_i16_voice_recognition", control.captureId)
        assertTrue(!control.captureFloat)
    }

    @Test
    fun `loopback spec targets USB in and out and is not a matrix cell`() {
        assertTrue(LOOPBACK_SPEC.outputToHeadset)
        assertTrue(LOOPBACK_SPEC.inputFromUsb)
        assertEquals("loopback", LOOPBACK_SPEC.captureId)
        val matrixIds = generateConditionMatrix().map { it.conditionId }.toSet()
        assertTrue("loopback collides with a matrix cell id", LOOPBACK_SPEC.captureId !in matrixIds)
    }

    @Test
    fun `matrix cells and the vocal take keep the built-in mic input`() {
        // inputFromUsb must stay false everywhere except the explicit loopback spec — a sweep cell
        // silently routing input to a USB device would invalidate its bleed data.
        generateConditionMatrix().forEach { assertTrue(!it.toCaptureSpec().inputFromUsb) }
        assertTrue(!VOCAL_TAKE_SPEC.inputFromUsb)
        assertTrue(!HEADSET_ROUTE_SPEC.inputFromUsb)
    }

    @Test
    fun `vocal take spec is record-only and not a matrix cell`() {
        // Gain must be exactly 0.0 -- any acoustic playback would contaminate the take with real
        // reference bleed, which is precisely what the injection study must control externally.
        assertEquals(0.0, VOCAL_TAKE_SPEC.playbackGain, 0.0)
        assertEquals("vocal_take", VOCAL_TAKE_SPEC.captureId)
        // The id must never collide with a sweep cell id, or its files/sidecars could be mistaken
        // for sweep data by id-keyed tooling.
        val matrixIds = generateConditionMatrix().map { it.conditionId }.toSet()
        assertTrue("vocal_take collides with a matrix cell id", VOCAL_TAKE_SPEC.captureId !in matrixIds)
    }
}
