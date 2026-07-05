package com.overdub.harness.wav

import java.nio.ByteBuffer
import java.nio.ByteOrder

/** PCM format description for a WAV file. Only 16-bit PCM is supported. */
data class WavFormat(
    val sampleRate: Int,
    val bitDepth: Int,
    val channelCount: Int,
)

private const val PCM_AUDIO_FORMAT = 1
private const val RIFF_HEADER_SIZE = 44

/**
 * Encodes interleaved 16-bit PCM samples as a canonical 44-byte-header WAV file.
 * Pure function (no I/O, no Android framework dependency) so it's testable on a plain JVM.
 */
fun writeWav(samples: ShortArray, format: WavFormat): ByteArray {
    require(format.bitDepth == 16) { "Only 16-bit PCM is supported, got ${format.bitDepth}" }
    require(format.sampleRate > 0) { "sampleRate must be positive" }
    require(format.channelCount > 0) { "channelCount must be positive" }

    val bytesPerSample = format.bitDepth / 8
    val blockAlign = format.channelCount * bytesPerSample
    val byteRate = format.sampleRate * blockAlign
    val dataSize = samples.size * bytesPerSample
    val riffChunkSize = 36 + dataSize

    val buffer = ByteBuffer.allocate(RIFF_HEADER_SIZE + dataSize).order(ByteOrder.LITTLE_ENDIAN)

    buffer.put("RIFF".toByteArray(Charsets.US_ASCII))
    buffer.putInt(riffChunkSize)
    buffer.put("WAVE".toByteArray(Charsets.US_ASCII))

    buffer.put("fmt ".toByteArray(Charsets.US_ASCII))
    buffer.putInt(16) // Subchunk1Size for PCM
    buffer.putShort(PCM_AUDIO_FORMAT.toShort())
    buffer.putShort(format.channelCount.toShort())
    buffer.putInt(format.sampleRate)
    buffer.putInt(byteRate)
    buffer.putShort(blockAlign.toShort())
    buffer.putShort(format.bitDepth.toShort())

    buffer.put("data".toByteArray(Charsets.US_ASCII))
    buffer.putInt(dataSize)
    for (sample in samples) {
        buffer.putShort(sample)
    }

    return buffer.array()
}
