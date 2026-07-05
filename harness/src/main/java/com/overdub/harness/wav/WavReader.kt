package com.overdub.harness.wav

import java.nio.ByteBuffer
import java.nio.ByteOrder

// Mirrors WavWriter.kt's file-private constant (both are file-scoped, so each file declares its own).
private const val PCM_AUDIO_FORMAT = 1

/** A decoded 16-bit PCM WAV: its [format] and interleaved [samples]. */
data class WavAudio(
    val format: WavFormat,
    val samples: ShortArray,
) {
    // ShortArray needs structural equals/hashCode to be value-comparable (data class uses identity).
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is WavAudio) return false
        return format == other.format && samples.contentEquals(other.samples)
    }

    override fun hashCode(): Int = 31 * format.hashCode() + samples.contentHashCode()
}

/**
 * Decodes a canonical 16-bit PCM WAV (the format [writeWav] produces and the harness's reference
 * track asset uses) into its samples. Pure function (bytes in, [WavAudio] out) so it's testable on a
 * plain JVM, mirroring [writeWav].
 *
 * Walks the RIFF chunk list to find `fmt `/`data` rather than assuming the fixed 44-byte layout, so
 * a file carrying extra chunks (e.g. a `LIST`/`INFO` block some encoders add) still decodes.
 */
fun readWav(bytes: ByteArray): WavAudio {
    require(bytes.size >= 12) { "Too short to be a WAV file: ${bytes.size} bytes" }
    val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)

    require(readTag(buffer) == "RIFF") { "Not a RIFF file" }
    buffer.int // overall RIFF chunk size (unused)
    require(readTag(buffer) == "WAVE") { "Not a WAVE file" }

    var sampleRate = 0
    var channelCount = 0
    var bitDepth = 0
    var dataOffset = -1
    var dataSize = 0

    while (buffer.remaining() >= 8) {
        val chunkId = readTag(buffer)
        val chunkSize = buffer.int
        when (chunkId) {
            "fmt " -> {
                val audioFormat = buffer.short.toInt()
                require(audioFormat == PCM_AUDIO_FORMAT) { "Only PCM WAV is supported, got format $audioFormat" }
                channelCount = buffer.short.toInt()
                sampleRate = buffer.int
                buffer.int // byte rate (derivable, unused)
                buffer.short // block align (derivable, unused)
                bitDepth = buffer.short.toInt()
                // Skip any extra fmt bytes beyond the 16-byte PCM core.
                val consumed = 16
                if (chunkSize > consumed) buffer.position(buffer.position() + (chunkSize - consumed))
            }
            "data" -> {
                dataOffset = buffer.position()
                dataSize = chunkSize
                buffer.position(buffer.position() + chunkSize)
            }
            else -> buffer.position(buffer.position() + chunkSize)
        }
        // Chunks are word-aligned: an odd size carries a trailing pad byte.
        if (chunkSize % 2 == 1 && buffer.remaining() >= 1) buffer.position(buffer.position() + 1)
    }

    require(dataOffset >= 0) { "No data chunk found" }
    require(bitDepth == 16) { "Only 16-bit PCM is supported, got $bitDepth" }

    val sampleCount = dataSize / (bitDepth / 8)
    val samples = ShortArray(sampleCount)
    val sampleView = ByteBuffer.wrap(bytes, dataOffset, dataSize).order(ByteOrder.LITTLE_ENDIAN)
    for (i in 0 until sampleCount) {
        samples[i] = sampleView.short
    }

    return WavAudio(WavFormat(sampleRate, bitDepth, channelCount), samples)
}

private fun readTag(buffer: ByteBuffer): String {
    val tag = ByteArray(4)
    buffer.get(tag)
    return String(tag, Charsets.US_ASCII)
}
