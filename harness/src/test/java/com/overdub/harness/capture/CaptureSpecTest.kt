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
