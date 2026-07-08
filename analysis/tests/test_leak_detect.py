"""Tests for the leak-vs-performance discriminator (doc/test2-step2-plan.md item 12).

Two cases the vet script got wrong before this module existed, both asserted
here as regression guards:

  * the segment-vs-full-reference slice arithmetic -- a late segment's true lag
    must stay inside the FFT's representable range (the original whole-reference
    formulation raised "lag_window selects no samples");
  * edge-pinning -- a segment with no interior peak must NOT read as a
    machine-stable leak just because the windowed argmax returns a value at the
    boundary.
"""

from __future__ import annotations

import numpy as np

from overdub_analysis.leak_detect import classify_leak, segment_lags

RATE = 48000
SEG_S = 4.0
LAG_HW_S = 0.100
LEAK_SPREAD_MS = 2.0
WARN_DB = 6.0


def _bandpassed_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    # Broadband-ish noise is fine -- the discriminator only looks at lag geometry,
    # not spectral shape (PHAT re-whitens).
    return rng.standard_normal(n)


def test_below_threshold_peak_is_not_a_leak():
    rng = np.random.default_rng(0)
    ref = _bandpassed_noise(RATE * 16, rng)
    take = _bandpassed_noise(RATE * 16, rng)
    # Independent noise: no real peak. psr_db below the warn threshold.
    cls = classify_leak(
        ref, take, RATE,
        psr_db=0.0, offset_samples=0,
        leak_psr_warn_db=WARN_DB, segment_s=SEG_S, lag_hw_s=LAG_HW_S, leak_spread_ms=LEAK_SPREAD_MS,
    )
    assert cls.below_threshold
    assert not cls.leak
    assert cls.segment_lags == []


def test_machine_stable_peak_is_a_leak():
    rng = np.random.default_rng(1)
    ref = _bandpassed_noise(RATE * 16, rng)
    # A genuine leak: the reference itself, delayed by a fixed offset, added onto
    # independent vocal noise. Every segment then has an interior peak at the
    # SAME lag (machine-stable) -> leak.
    offset = int(0.115 * RATE)  # +115 ms, like the real take 1's whole-take peak
    take = _bandpassed_noise(RATE * 16, rng) + 0.3 * np.concatenate(
        [np.zeros(offset), ref[: RATE * 16 - offset]]
    )
    lags = segment_lags(ref, take, RATE, offset, segment_s=SEG_S, lag_hw_s=LAG_HW_S)
    # All segments find an interior peak near +115 ms.
    assert all(not s.edge_pinned for s in lags), [s.lag_ms for s in lags]
    spreads = [s.lag_ms for s in lags]
    assert max(spreads) - min(spreads) <= LEAK_SPREAD_MS, spreads
    cls = classify_leak(
        ref, take, RATE,
        psr_db=10.0, offset_samples=offset,
        leak_psr_warn_db=WARN_DB, segment_s=SEG_S, lag_hw_s=LAG_HW_S, leak_spread_ms=LEAK_SPREAD_MS,
    )
    assert cls.leak
    assert not cls.below_threshold


def test_jittered_peak_is_performance_not_leak():
    rng = np.random.default_rng(2)
    ref = _bandpassed_noise(RATE * 16, rng)
    # A performance: each segment correlates with a DIFFERENT slice of the
    # reference (jittered lag), so no single machine-stable lag across segments.
    seg = int(RATE * SEG_S)
    take = np.zeros(RATE * 16)
    jitter = [0.0, 0.040, -0.030, 0.020]  # syllable-to-syllable timing scatter, ms-scale -> tens of ms
    for i, j in enumerate(jitter):
        s = i * seg
        d = int((0.115 + j) * RATE)
        a0 = max(0, s - d)
        take[s : s + seg] += _bandpassed_noise(seg, rng) + 0.3 * ref[a0 : a0 + seg]
    lags = segment_lags(ref, take, RATE, int(0.115 * RATE), segment_s=SEG_S, lag_hw_s=LAG_HW_S)
    spreads = [s.lag_ms for s in lags if not s.edge_pinned]
    # Either some segments pin to the edge (no interior peak), or the interior
    # peaks disagree by more than the leak spread -- either rules out a leak.
    cls = classify_leak(
        ref, take, RATE,
        psr_db=10.0, offset_samples=int(0.115 * RATE),
        leak_psr_warn_db=WARN_DB, segment_s=SEG_S, lag_hw_s=LAG_HW_S, leak_spread_ms=LEAK_SPREAD_MS,
    )
    assert not cls.leak


def test_late_segment_lag_stays_in_range():
    """Regression: the 4th segment's true lag must not exceed the FFT half-range.

    The original whole-reference formulation raised 'lag_window selects no
    samples' because a late segment aligned to a late reference position put the
    expected local lag outside [-nfft//2, nfft//2]. The slice formulation keeps
    it in range.
    """
    rng = np.random.default_rng(3)
    ref = _bandpassed_noise(RATE * 16, rng)
    offset = int(0.115 * RATE)
    take = _bandpassed_noise(RATE * 16, rng) + 0.3 * np.concatenate(
        [np.zeros(offset), ref[: RATE * 16 - offset]]
    )
    # Must not raise.
    lags = segment_lags(ref, take, RATE, offset, segment_s=SEG_S, lag_hw_s=LAG_HW_S)
    assert len(lags) == 4
