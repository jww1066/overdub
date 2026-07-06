package com.overdub.harness.timestamp

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class StreamOffsetTest {

    private val fs = 48000

    @Test
    fun `same nanoTime -- offset is the raw frame-position difference`() {
        // Both timestamps read at the same instant: the time term drops out and the offset is
        // (inputFrames - outputFrames). Input has captured 4800 fewer frames than output has heard,
        // so the mic index leads the reference index by 4800 frames == -100 ms.
        val ts = StreamTimestamps(
            outputFrames = 100_000,
            outputNanos = 2_000_000_000,
            inputFrames = 95_200,
            inputNanos = 2_000_000_000,
        )
        val offset = computeStreamOffset(ts, fs)
        assertEquals(-4800.0, offset.frames, 1e-9)
        assertEquals(-100.0, offset.ms, 1e-9)
    }

    @Test
    fun `same frame position -- offset comes entirely from the clock difference`() {
        // Both streams report frame 0, but the output's frame-0 was heard 100 ms after the input's
        // frame-0 was captured (outputNanos - inputNanos = 0.1 s), i.e. the mic ran ahead: +4800
        // frames == +100 ms in the mic-lags-positive convention.
        val ts = StreamTimestamps(
            outputFrames = 0,
            outputNanos = 100_000_000,
            inputFrames = 0,
            inputNanos = 0,
        )
        val offset = computeStreamOffset(ts, fs)
        assertEquals(4800.0, offset.frames, 1e-9)
        assertEquals(100.0, offset.ms, 1e-9)
    }

    @Test
    fun `frame-position and clock terms combine`() {
        // inputFrames - outputFrames = -1000 frames; clock term = (500_000 - 0) ns * 48000 / 1e9
        // = +24 frames. Sum = -976 frames.
        val ts = StreamTimestamps(
            outputFrames = 48_000,
            outputNanos = 500_000,
            inputFrames = 47_000,
            inputNanos = 0,
        )
        val offset = computeStreamOffset(ts, fs)
        assertEquals(-976.0, offset.frames, 1e-9)
        assertEquals(-976.0 / fs * 1000.0, offset.ms, 1e-9)
    }

    @Test
    fun `rejects a non-positive sample rate`() {
        val ts = StreamTimestamps(0, 0, 0, 0)
        assertThrows(IllegalArgumentException::class.java) { computeStreamOffset(ts, 0) }
        assertThrows(IllegalArgumentException::class.java) { computeStreamOffset(ts, -48000) }
    }
}
