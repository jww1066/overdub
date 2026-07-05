package com.overdub.harness.dsp

import kotlin.math.PI
import kotlin.math.sin
import kotlin.math.sqrt
import org.junit.Assert.assertEquals
import org.junit.Test

class RmsTest {

    @Test
    fun `silence has zero RMS`() {
        val samples = ShortArray(1000) { 0 }
        assertEquals(0.0, rms(samples), 1e-9)
    }

    @Test
    fun `empty buffer has zero RMS`() {
        assertEquals(0.0, rms(ShortArray(0)), 1e-9)
    }

    @Test
    fun `full-scale sine wave matches amplitude over sqrt2`() {
        val amplitude = Short.MAX_VALUE.toDouble()
        val sampleCount = 48000 // whole cycles at 48kHz, 100Hz tone
        val frequencyHz = 100.0
        val sampleRate = 48000.0
        val samples = ShortArray(sampleCount) { i ->
            (amplitude * sin(2 * PI * frequencyHz * i / sampleRate)).toInt().toShort()
        }

        val expected = amplitude / sqrt(2.0)
        // tolerance accounts for Short rounding, not an exact analytic match
        assertEquals(expected, rms(samples), expected * 0.01)
    }

    @Test
    fun `constant-value buffer returns that value as its noise floor`() {
        val floor: Short = 500
        val samples = ShortArray(2000) { floor }
        assertEquals(floor.toDouble(), rms(samples), 1e-9)
    }

    @Test
    fun `negative constant-value buffer returns absolute value`() {
        val floor: Short = -500
        val samples = ShortArray(2000) { floor }
        assertEquals(500.0, rms(samples), 1e-9)
    }
}
