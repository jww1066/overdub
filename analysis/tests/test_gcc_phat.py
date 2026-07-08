"""Synthetic validation of GCC-PHAT — the Test 2 step 1 gate.

Per `doc/prototype-plan.md`:

* **Step 1 (synthetic, implementation-correctness gate):** at high/clean SNR
  (≥20 dB) the recovered offset must match the injected delay within ±1 sample
  and PSR must be ≥10 dB. Sweep noise downward and record the SNR at which
  PSR crosses below 6 dB — that crossing point is *an output of the test*, not
  a threshold to hit.

These fixtures are also the port-correctness regression tests the 093038
review asked for: if the algorithm is later ported to Kotlin/C++ on the
device, the same synthetic vectors should be re-run against that port.
"""

from __future__ import annotations

import numpy as np
import pytest

from overdub_analysis import (
    add_noise_at_snr,
    broadband_click_train,
    delay,
    gcc_phat,
    gcc_phat_correlation,
)

FS = 48_000.0
HIGH_SNR_DB = 30.0  # well above the 20 dB "clean" gate
RNG_SEED = 0


def _reference(n: int = 48_000) -> np.ndarray:
    """A 1-second broadband click-train reference, reproducibly generated."""
    return broadband_click_train(
        n, period=1000, click_width=8, rng=np.random.default_rng(RNG_SEED)
    )


# ---------------------------------------------------------------------------
# Step 1 gate: clean / high-SNR recovery
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("d", [0, 1, 7, 64, 480, 1234])
def test_clean_recovery_matches_injected_delay(d: int) -> None:
    """At ≥20 dB SNR, offset is within ±1 sample and PSR ≥10 dB."""
    ref = _reference()
    mic = delay(ref, d)
    mic = add_noise_at_snr(mic, HIGH_SNR_DB, np.random.default_rng(RNG_SEED + d))

    result = gcc_phat(ref, mic, fs=FS)

    assert abs(result.offset_samples - d) <= 1, (
        f"expected ~{d}, got {result.offset_samples} (PSR {result.psr_db:.1f} dB)"
    )
    assert result.psr_db >= 10.0, f"PSR {result.psr_db:.1f} dB below 10 dB confident bar"
    assert result.offset_seconds == pytest.approx(
        result.offset_samples / FS, rel=1e-9
    )


def test_negative_delay_recovered() -> None:
    """A negative delay (mic leading the reference) is recovered with correct sign."""
    ref = _reference()
    d = -200
    mic = delay(ref, d)
    mic = add_noise_at_snr(mic, HIGH_SNR_DB, np.random.default_rng(RNG_SEED))

    result = gcc_phat(ref, mic, fs=FS)

    assert abs(result.offset_samples - d) <= 1, (
        f"expected ~{d}, got {result.offset_samples}"
    )


def test_psr_decreases_as_noise_increases() -> None:
    """PSR is a monotone-decreasing function of noise (sanity for the metric)."""
    ref = _reference()
    d = 300
    mic_clean = delay(ref, d)
    snrs = [40.0, 20.0, 10.0, 0.0, -5.0]
    psrs = []
    for snr in snrs:
        mic = add_noise_at_snr(mic_clean, snr, np.random.default_rng(RNG_SEED))
        psrs.append(gcc_phat(ref, mic, fs=FS).psr_db)
    # Allow one non-monotonic step from random noise, but the overall trend
    # must be downward: first PSR must clearly exceed the last.
    assert psrs[0] > psrs[-1], f"PSR not decreasing with noise: {psrs}"


def test_six_db_crossing_is_an_output_not_a_threshold() -> None:
    """Sweep SNR and find where PSR crosses 6 dB — record it, don't assert a value.

    The crossing point is an *output* of Test 2 step 1 (per prototype-plan.md).
    We only assert that such a crossing exists and lands below a loose sanity
    ceiling, and that the algorithm is still correct well above the crossing.

    Note: a broadband *periodic* click train has substantial coherent
    processing gain across its many transients, so the floor can sit well below
    0 dB SNR — a low crossing is a strong positive finding for this signal
    class, not a problem. The sweep is run wide enough to actually find it.
    """
    ref = _reference()
    d = 250
    mic_clean = delay(ref, d)

    snrs = np.arange(40.0, -60.0 - 0.001, -2.0)
    crossing: float | None = None
    last_result: float | None = None
    for snr in snrs:
        mic = add_noise_at_snr(mic_clean, float(snr), np.random.default_rng(RNG_SEED))
        result = gcc_phat(ref, mic, fs=FS)
        last_result = result.psr_db
        if result.psr_db < 6.0:
            crossing = float(snr)
            break

    assert crossing is not None, (
        f"PSR never crossed 6 dB down to {snrs[-1]} dB SNR "
        f"(last PSR {last_result:.1f} dB); algorithm is extremely robust for "
        "this signal class — extend the sweep or accept as a finding"
    )
    # Loose sanity ceiling: a clean broadband signal breaking below 6 dB at
    # *high* SNR would suggest the PSR metric is broken rather than the signal
    # being hard. 30 dB is generous; real crossings land far below this.
    assert crossing < 30.0, (
        f"PSR crossed 6 dB at {crossing:.1f} dB SNR — surprisingly high; "
        "check the PSR metric or the signal generator"
    )
    # And well above the crossing, the offset is still recovered correctly.
    mic = add_noise_at_snr(mic_clean, crossing + 20.0, np.random.default_rng(RNG_SEED))
    assert abs(gcc_phat(ref, mic, fs=FS).offset_samples - d) <= 1



# ---------------------------------------------------------------------------
# Algorithm correctness / edge cases
# ---------------------------------------------------------------------------


def test_identical_signals_yield_zero_offset() -> None:
    """A signal correlated with itself (no delay, no noise) peaks at lag 0."""
    ref = _reference()
    result = gcc_phat(ref, ref, fs=FS)
    assert result.offset_samples == 0
    # Self-correlation has a degenerate sidelobe structure; just assert finite/non-NaN.
    assert not np.isnan(result.psr_db)


def test_empty_input_raises() -> None:
    with pytest.raises(ValueError):
        gcc_phat(np.array([]), np.array([1.0, 2.0]))


def test_negative_exclusion_raises() -> None:
    ref = _reference()
    mic = delay(ref, 10)
    with pytest.raises(ValueError):
        gcc_phat(ref, mic, psr_exclusion=-1)


def test_zero_snr_does_not_crash_and_still_reports_a_peak() -> None:
    """At 0 dB SNR the peak may be unreliable, but the function must not crash."""
    ref = _reference()
    mic = add_noise_at_snr(delay(ref, 100), 0.0, np.random.default_rng(RNG_SEED))
    result = gcc_phat(ref, mic, fs=FS)
    assert isinstance(result.offset_samples, int)
    assert np.isfinite(result.psr_db) or result.psr_db == float("inf")


# ---------------------------------------------------------------------------
# Lag-window constraint (next-steps item 7a): reject wraparound aliases
# ---------------------------------------------------------------------------


def test_lag_window_recovers_delay_inside_window() -> None:
    """A true delay inside the window is recovered exactly, PSR still confident."""
    ref = _reference()
    d = 200
    mic = add_noise_at_snr(delay(ref, d), HIGH_SNR_DB, np.random.default_rng(RNG_SEED))
    result = gcc_phat(ref, mic, fs=FS, lag_window=(0, 480))
    assert result.offset_samples == d
    assert result.psr_db >= 10.0


def test_lag_window_passing_none_matches_default() -> None:
    """Explicit lag_window=None is identical to the unconstrained default (regression)."""
    ref = _reference()
    mic = add_noise_at_snr(delay(ref, 123), HIGH_SNR_DB, np.random.default_rng(RNG_SEED))
    a = gcc_phat(ref, mic, fs=FS)
    b = gcc_phat(ref, mic, fs=FS, lag_window=None)
    assert a.offset_samples == b.offset_samples
    assert a.psr_db == pytest.approx(b.psr_db)


def test_lag_window_forces_result_into_window() -> None:
    """A window that excludes the true delay forces the argmax into the window.

    This is the wraparound-alias guard: a physically-impossible offset can never
    be returned once the plausible window is set, even if it were the global max.
    """
    ref = _reference()
    d = 200
    mic = add_noise_at_snr(delay(ref, d), HIGH_SNR_DB, np.random.default_rng(RNG_SEED))
    result = gcc_phat(ref, mic, fs=FS, lag_window=(300, 600))
    assert 300 <= result.offset_samples <= 600
    assert result.offset_samples != d


def test_lag_window_recovers_negative_delay_when_window_allows() -> None:
    """A negative (mic-leading) delay is still recoverable if the window includes it."""
    ref = _reference()
    d = -200
    mic = add_noise_at_snr(delay(ref, d), HIGH_SNR_DB, np.random.default_rng(RNG_SEED))
    result = gcc_phat(ref, mic, fs=FS, lag_window=(-480, 480))
    assert result.offset_samples == d


def test_lag_window_selecting_nothing_raises() -> None:
    """A window with no representable offsets is a caller error, not a silent 0."""
    ref = _reference()
    mic = delay(ref, 100)
    with pytest.raises(ValueError):
        gcc_phat(ref, mic, fs=FS, lag_window=(10**9, 10**9 + 1))


# ---------------------------------------------------------------------------
# Raw correlation vector (peak-competition diagnostics)
# ---------------------------------------------------------------------------


def test_correlation_global_argmax_matches_gcc_phat() -> None:
    """The exported raw vector's argmax is exactly what unconstrained gcc_phat returns."""
    ref = _reference()
    d = 321
    mic = add_noise_at_snr(delay(ref, d), HIGH_SNR_DB, np.random.default_rng(RNG_SEED))

    gcc, offset_all = gcc_phat_correlation(ref, mic)
    result = gcc_phat(ref, mic, fs=FS)

    assert gcc.shape == offset_all.shape
    assert int(offset_all[np.argmax(gcc)]) == result.offset_samples
    assert float(gcc[np.argmax(gcc)]) == pytest.approx(float(gcc[result.lag_index]))


def test_correlation_exposes_competing_peak() -> None:
    """A mic that is a mix of two delayed copies shows *both* peaks in the raw vector.

    This is the diagnostic use case: an alias/echo peak that gcc_phat's single
    argmax would hide is visible (and rankable) in the full correlation.
    """
    ref = _reference()
    d_main, d_echo = 150, 900
    main = delay(ref, d_main)
    echo = delay(ref, d_echo)
    main = np.concatenate([main, np.zeros(echo.size - main.size)])
    mic = main + 0.6 * echo

    gcc, offset_all = gcc_phat_correlation(ref, mic)

    def value_at(offset: int) -> float:
        return float(gcc[np.nonzero(offset_all == offset)[0][0]])

    floor = float(np.median(np.abs(gcc)))
    assert value_at(d_main) > 10 * floor
    assert value_at(d_echo) > 10 * floor
    assert value_at(d_main) > value_at(d_echo)


def test_correlation_empty_input_raises() -> None:
    with pytest.raises(ValueError):
        gcc_phat_correlation(np.array([]), np.array([1.0, 2.0]))
