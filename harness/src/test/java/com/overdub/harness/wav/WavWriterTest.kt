package com.overdub.harness.wav

import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class WavWriterTest {

    private fun ascii(bytes: ByteArray, offset: Int, length: Int): String =
        String(bytes, offset, length, Charsets.US_ASCII)

    @Test
    fun `header fields are correct for a known sample buffer`() {
        val samples = shortArrayOf(0, 100, -100, Short.MAX_VALUE, Short.MIN_VALUE)
        val format = WavFormat(sampleRate = 48000, bitDepth = 16, channelCount = 1)

        val wav = writeWav(samples, format)
        val buf = ByteBuffer.wrap(wav).order(ByteOrder.LITTLE_ENDIAN)

        val expectedDataSize = samples.size * 2
        assertEquals(44 + expectedDataSize, wav.size)

        assertEquals("RIFF", ascii(wav, 0, 4))
        assertEquals(36 + expectedDataSize, buf.getInt(4))
        assertEquals("WAVE", ascii(wav, 8, 4))

        assertEquals("fmt ", ascii(wav, 12, 4))
        assertEquals(16, buf.getInt(16)) // Subchunk1Size
        assertEquals(1, buf.getShort(20).toInt()) // PCM
        assertEquals(1, buf.getShort(22).toInt()) // channel count
        assertEquals(48000, buf.getInt(24)) // sample rate
        assertEquals(48000 * 1 * 2, buf.getInt(28)) // byte rate
        assertEquals(2, buf.getShort(32).toInt()) // block align
        assertEquals(16, buf.getShort(34).toInt()) // bits per sample

        assertEquals("data", ascii(wav, 36, 4))
        assertEquals(expectedDataSize, buf.getInt(40))

        for (i in samples.indices) {
            assertEquals(samples[i], buf.getShort(44 + i * 2))
        }
    }

    @Test
    fun `data chunk size matches actual sample count for stereo`() {
        val samples = ShortArray(2000) { (it - 1000).toShort() }
        val format = WavFormat(sampleRate = 44100, bitDepth = 16, channelCount = 2)

        val wav = writeWav(samples, format)
        val buf = ByteBuffer.wrap(wav).order(ByteOrder.LITTLE_ENDIAN)

        val expectedDataSize = samples.size * 2
        assertEquals(expectedDataSize, buf.getInt(40))
        assertEquals(2, buf.getShort(22).toInt())
        assertEquals(4, buf.getShort(32).toInt()) // blockAlign = channels * bytesPerSample
        assertEquals(44100 * 4, buf.getInt(28)) // byteRate
    }

    @Test
    fun `empty sample buffer still produces a valid header`() {
        val wav = writeWav(ShortArray(0), WavFormat(sampleRate = 16000, bitDepth = 16, channelCount = 1))
        assertEquals(44, wav.size)
        val buf = ByteBuffer.wrap(wav).order(ByteOrder.LITTLE_ENDIAN)
        assertEquals(36, buf.getInt(4))
        assertEquals(0, buf.getInt(40))
    }

    @Test
    fun `rejects unsupported bit depth`() {
        assertThrows(IllegalArgumentException::class.java) {
            writeWav(shortArrayOf(0), WavFormat(sampleRate = 48000, bitDepth = 24, channelCount = 1))
        }
    }

    @Test
    fun `float header fields are correct for a known sample buffer`() {
        // Values beyond int16 full scale on purpose: the float path exists to preserve exactly the
        // headroom an int16 write would clip (the capture-headroom probe).
        val samples = floatArrayOf(0.0f, 0.5f, -0.5f, 1.25f, -1.25f)
        val format = WavFormat(sampleRate = 48000, bitDepth = 32, channelCount = 1)

        val wav = writeWavFloat(samples, format)
        val buf = ByteBuffer.wrap(wav).order(ByteOrder.LITTLE_ENDIAN)

        val expectedDataSize = samples.size * 4
        // RIFF(12) + fmt chunk(8+18) + fact chunk(8+4) + data header(8) = 58 bytes before data.
        assertEquals(58 + expectedDataSize, wav.size)

        assertEquals("RIFF", ascii(wav, 0, 4))
        assertEquals(wav.size - 8, buf.getInt(4))
        assertEquals("WAVE", ascii(wav, 8, 4))

        assertEquals("fmt ", ascii(wav, 12, 4))
        assertEquals(18, buf.getInt(16)) // Subchunk1Size incl. cbSize
        assertEquals(3, buf.getShort(20).toInt()) // IEEE float
        assertEquals(1, buf.getShort(22).toInt()) // channel count
        assertEquals(48000, buf.getInt(24)) // sample rate
        assertEquals(48000 * 4, buf.getInt(28)) // byte rate
        assertEquals(4, buf.getShort(32).toInt()) // block align
        assertEquals(32, buf.getShort(34).toInt()) // bits per sample
        assertEquals(0, buf.getShort(36).toInt()) // cbSize

        assertEquals("fact", ascii(wav, 38, 4))
        assertEquals(4, buf.getInt(42))
        assertEquals(samples.size, buf.getInt(46)) // sample frames (mono)

        assertEquals("data", ascii(wav, 50, 4))
        assertEquals(expectedDataSize, buf.getInt(54))

        for (i in samples.indices) {
            assertEquals(samples[i], buf.getFloat(58 + i * 4), 0.0f)
        }
    }

    @Test
    fun `float writer rejects non-32-bit depth`() {
        assertThrows(IllegalArgumentException::class.java) {
            writeWavFloat(floatArrayOf(0f), WavFormat(sampleRate = 48000, bitDepth = 16, channelCount = 1))
        }
    }
}
