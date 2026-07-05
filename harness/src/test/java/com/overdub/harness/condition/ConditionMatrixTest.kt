package com.overdub.harness.condition

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ConditionMatrixTest {

    @Test
    fun `produces exactly 36 entries`() {
        assertEquals(36, generateConditionMatrix().size)
    }

    @Test
    fun `has no duplicate condition ids`() {
        val ids = generateConditionMatrix().map { it.conditionId }
        assertEquals(ids.size, ids.toSet().size)
    }

    @Test
    fun `covers the full cross-product with no duplicate combinations`() {
        val matrix = generateConditionMatrix()
        val combos = matrix.map { it.volume to it.distance to it.orientation to it.obstruction }
        assertEquals(combos.size, combos.toSet().size)

        for (volume in Volume.entries) {
            for (distance in Distance.entries) {
                for (orientation in Orientation.entries) {
                    for (obstruction in Obstruction.entries) {
                        assertTrue(
                            "missing combination $volume/$distance/$orientation/$obstruction",
                            matrix.any {
                                it.volume == volume && it.distance == distance &&
                                    it.orientation == orientation && it.obstruction == obstruction
                            },
                        )
                    }
                }
            }
        }
    }

    @Test
    fun `exactly one condition is the baseline`() {
        val baselines = generateConditionMatrix().filter { it.isBaseline }
        assertEquals(1, baselines.size)
        assertEquals(BASELINE_CONDITION, baselines.single())
    }

    @Test
    fun `baseline condition matches the fixed realistic values`() {
        assertEquals(Volume.CONVERSATIONAL, BASELINE_CONDITION.volume)
        assertEquals(Distance.ARMS_LENGTH, BASELINE_CONDITION.distance)
        assertEquals(Orientation.FACE_UP, BASELINE_CONDITION.orientation)
        assertEquals(Obstruction.NONE, BASELINE_CONDITION.obstruction)
    }

    @Test
    fun `conditionFromId round-trips every cell's id back to that cell`() {
        for (condition in generateConditionMatrix()) {
            assertEquals(condition, conditionFromId(condition.conditionId))
        }
    }

    @Test
    fun `conditionFromId resolves the baseline id to the baseline condition`() {
        assertEquals(BASELINE_CONDITION, conditionFromId(BASELINE_CONDITION.conditionId))
    }

    @Test
    fun `conditionFromId returns null for an id not in the matrix`() {
        assertNull(conditionFromId("bogus_id"))
        // Well-formed shape but non-existent axis values must not resolve either.
        assertNull(conditionFromId("whisper_near_faceup_none"))
        assertNull(conditionFromId(""))
    }
}
