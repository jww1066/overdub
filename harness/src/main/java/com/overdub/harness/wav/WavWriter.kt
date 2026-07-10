package com.overdub.harness.wav

import java.nio.ByteBuffer
import java.nio.ByteOrder

/** PCM format description for a WAV file. 16-bit integer and 32-bit float PCM are supported. */
data class WavFormat(
    val sampleRate: Int,
    val bitDepth: Int,
    val channelCount: Int,
)

private const val PCM_AUDIO_FORMAT = 1
private const val IEEE_FLOAT_AUDIO_FORMAT = 3
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

/**
 * Encodes interleaved 32-bit IEEE-float PCM samples (full scale ±1.0) as a WAV file — the
 * capture-headroom probe's output format, preserving the Float input stream's samples exactly with
 * no int16 conversion in between. Non-PCM WAV requires the extended fmt chunk (cbSize) plus a
 * `fact` chunk, both written here so standard readers (scipy et al.) accept the file. Pure
 * function, same as [writeWav].
 */
fun writeWavFloat(samples: FloatArray, format: WavFormat): ByteArray {
    require(format.bitDepth == 32) { "Float WAV is 32-bit, got ${format.bitDepth}" }
    require(format.sampleRate > 0) { "sampleRate must be positive" }
    require(format.channelCount > 0) { "channelCount must be positive" }

    val bytesPerSample = format.bitDepth / 8
    val blockAlign = format.channelCount * bytesPerSample
    val byteRate = format.sampleRate * blockAlign
    val dataSize = samples.size * bytesPerSample
    // fmt (18 bytes incl. cbSize=0) + fact (4 bytes) + data, each with an 8-byte chunk header.
    val riffChunkSize = 4 + (8 + 18) + (8 + 4) + (8 + dataSize)

    val buffer = ByteBuffer.allocate(8 + riffChunkSize).order(ByteOrder.LITTLE_ENDIAN)

    buffer.put("RIFF".toByteArray(Charsets.US_ASCII))
    buffer.putInt(riffChunkSize)
    buffer.put("WAVE".toByteArray(Charsets.US_ASCII))

    buffer.put("fmt ".toByteArray(Charsets.US_ASCII))
    buffer.putInt(18) // Subchunk1Size for non-PCM: 16 + 2-byte cbSize
    buffer.putShort(IEEE_FLOAT_AUDIO_FORMAT.toShort())
    buffer.putShort(format.channelCount.toShort())
    buffer.putInt(format.sampleRate)
    buffer.putInt(byteRate)
    buffer.putShort(blockAlign.toShort())
    buffer.putShort(format.bitDepth.toShort())
    buffer.putShort(0) // cbSize: no format extension

    buffer.put("fact".toByteArray(Charsets.US_ASCII))
    buffer.putInt(4)
    buffer.putInt(samples.size / format.channelCount) // sample frames

    buffer.put("data".toByteArray(Charsets.US_ASCII))
    buffer.putInt(dataSize)
    for (sample in samples) {
        buffer.putFloat(sample)
    }

    return buffer.array()
}
