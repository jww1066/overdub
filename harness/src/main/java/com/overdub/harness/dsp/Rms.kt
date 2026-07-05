package com.overdub.harness.dsp

import kotlin.math.sqrt

/**
 * Root-mean-square of a signed 16-bit PCM buffer, used both as the on-device sanity gate
 * (test2-step2-plan.md Components §2) and the noise-floor check (Tier 1 test list).
 */
fun rms(samples: ShortArray): Double {
    if (samples.isEmpty()) return 0.0
    var sumSquares = 0.0
    for (sample in samples) {
        val s = sample.toDouble()
        sumSquares += s * s
    }
    return sqrt(sumSquares / samples.size)
}
