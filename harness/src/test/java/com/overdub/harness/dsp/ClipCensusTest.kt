package com.overdub.harness.dsp

import org.junit.Assert.assertEquals
import org.junit.Test

class ClipCensusTest {

    @Test
    fun `int16 census counts both rails and normalizes the peak`() {
        val samples = shortArrayOf(0, 100, -100, 32767, -32768, 32766, -32767)
        val census = clipCensus(samples)
        // 32767, -32768 and -32767 are at/above int16 FS; 32766 is not.
        assertEquals(3, census.railedCount)
        assertEquals(32768.0 / 32768.0, census.peakAbs, 1e-9)
    }

    @Test
    fun `int16 census on a clean buffer reports zero railed`() {
        val samples = ShortArray(1000) { ((it % 200) - 100).toShort() }
        val census = clipCensus(samples)
        assertEquals(0, census.railedCount)
        assertEquals(100 / 32768.0, census.peakAbs, 1e-9)
    }

    @Test
    fun `float census uses the int16 FS threshold so arms compare one number`() {
        // 0.99997 (>= 32767/32768) rails; 0.9999 does not; 1.25 is the recovered-headroom case
        // the float capture path exists to observe, and it both rails and sets the peak.
        val samples = floatArrayOf(0.0f, 0.5f, -0.9999f, 0.99997f, -1.25f)
        val census = clipCensus(samples)
        assertEquals(2, census.railedCount)
        assertEquals(1.25, census.peakAbs, 1e-6)
    }

    @Test
    fun `empty buffers census to zero`() {
        assertEquals(ClipCensus(0.0, 0), clipCensus(ShortArray(0)))
        assertEquals(ClipCensus(0.0, 0), clipCensus(FloatArray(0)))
    }
}
