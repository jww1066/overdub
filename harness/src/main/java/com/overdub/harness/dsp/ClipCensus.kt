package com.overdub.harness.dsp

import kotlin.math.abs

/**
 * On-device clip census for the capture-headroom probe (the ADC-rail finding,
 * doc/guides/offline-dsp.md "census raw captures"): logged per capture so the operator can judge an
 * arm from logcat without pulling the file first. The authoritative offline census (plateau runs,
 * near-FS bins) is `analysis/scripts/census_clipping.py`; this is the coarse go/no-go number.
 *
 * [peakAbs] is normalized to full scale 1.0 in both formats. [railedCount] counts samples at or
 * above int16 full scale — the same threshold in both formats (float FS 1.0 == 32768), so an
 * i16-vs-float arm comparison reads one number.
 */
data class ClipCensus(
    val peakAbs: Double,
    val railedCount: Int,
)

/** int16 full scale in a float capture's ±1.0 units. */
private const val INT16_FS_NORMALIZED = 32767.0 / 32768.0

fun clipCensus(samples: ShortArray): ClipCensus {
    var peak = 0
    var railed = 0
    for (sample in samples) {
        val a = if (sample >= 0) sample.toInt() else -sample.toInt() // 32768 for Short.MIN_VALUE
        if (a > peak) peak = a
        if (a >= 32767) railed++
    }
    return ClipCensus(peakAbs = peak / 32768.0, railedCount = railed)
}

fun clipCensus(samples: FloatArray): ClipCensus {
    var peak = 0.0
    var railed = 0
    for (sample in samples) {
        val a = abs(sample.toDouble())
        if (a > peak) peak = a
        if (a >= INT16_FS_NORMALIZED) railed++
    }
    return ClipCensus(peakAbs = peak, railedCount = railed)
}
