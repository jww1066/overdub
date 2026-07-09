"""Synthetic validation of the offline NLMS echo canceller.

Mirrors the gcc_phat step-1 pattern: prove the implementation correct on
synthetic signals with a known echo path before any real capture is judged
with it. The scenarios model the product case: a band-limited (500-4000 Hz)
reference, a sparse multipath echo path, mic noise, and an uncorrelated
near-end "vocal" sitting at the measured realistic ratio.
"""

from __future__ import annotations

import numpy as np
import pytest

from overdub_analysis.echo_cancel import (
    clip_mask,
    mute_spans,
    nlms,
    suppression_db,
    suppression_profile,
    tail_energy_fraction,
)
from overdub_analysis.vocal_inject import bandpass, inband_rms

RATE = 16000
LO, HI = 500.0, 4000.0
# Sparse echo path: direct arrival at 40 samples plus two early reflections.
PATH_TAPS = {40: 1.0, 52: -0.5, 75: 0.25}
NUM_TAPS = 256


def _band_noise(seconds: float, seed: int, rate: int = RATE) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(int(seconds * rate))
    return bandpass(x, LO, HI, rate)


def _echo_of(x: np.ndarray) -> np.ndarray:
    h = np.zeros(max(PATH_TAPS) + 1)
    for delay, gain in PATH_TAPS.items():
        h[delay] = gain
    return np.convolve(x, h)[: x.size]


def _scale_to_inband_db(x: np.ndarray, target: np.ndarray, db: float) -> np.ndarray:
    """Scale ``x`` so its in-band RMS sits ``db`` relative to ``target``'s."""
    return x * (10.0 ** (db / 20.0)) * (
        inband_rms(target, RATE, LO, HI) / inband_rms(x, RATE, LO, HI)
    )


def test_nlms_cancels_known_echo_path():
    ref = _band_noise(4.0, seed=1)
    bleed = _echo_of(ref)
    noise = _scale_to_inband_db(_band_noise(4.0, seed=2), bleed, -40.0)
    capture = bleed + noise

    r = nlms(ref, capture, num_taps=NUM_TAPS)

    # Judge over the converged region (skip the filter-span fill at the start).
    sl = slice(NUM_TAPS, None)
    sup = suppression_db(bleed[sl], (bleed - r.echo_estimate)[sl], RATE, LO, HI)
    assert sup >= 20.0, f"in-band bleed suppression only {sup:.1f} dB"


def test_impulse_response_recovered_with_white_excitation():
    """Exact tap recovery needs full-band excitation.

    A band-limited reference only determines the path inside its band (NLMS
    converges to a minimum-norm equivalent there -- suppression is unaffected,
    tap values are not), so the tap-identification check uses white noise.
    """
    rng = np.random.default_rng(1)
    ref = rng.standard_normal(4 * RATE)
    capture = _echo_of(ref)

    r = nlms(ref, capture, num_taps=NUM_TAPS)
    for delay, gain in PATH_TAPS.items():
        assert r.impulse_response[delay] == pytest.approx(gain, abs=0.05)


def test_uncorrelated_near_end_passes_through_and_bleed_still_suppressed():
    """The realistic product case: vocal 12 dB below the bleed in-band."""
    ref = _band_noise(4.0, seed=3)
    bleed = _echo_of(ref)
    vocal = _scale_to_inband_db(_band_noise(4.0, seed=4), bleed, -12.0)
    capture = bleed + vocal

    r = nlms(ref, capture, num_taps=NUM_TAPS)
    sl = slice(NUM_TAPS, None)

    # Bleed component suppressed at least to the listening-test target.
    sup = suppression_db(bleed[sl], (bleed - r.echo_estimate)[sl], RATE, LO, HI)
    assert sup >= 12.0, f"bleed suppression under near-end signal only {sup:.1f} dB"

    # The vocal passes through arithmetically untouched: the residual is
    # exactly vocal + surviving bleed, because the echo estimate is built from
    # the reference alone. (How CLOSE the residual is to the vocal is set by
    # the suppression above -- at 12 dB suppression and a -12 dB vocal the
    # surviving bleed sits ~level with the vocal by arithmetic.)
    assert np.allclose(r.residual, vocal + (bleed - r.echo_estimate))


def test_second_pass_removes_adaptation_transient():
    ref = _band_noise(4.0, seed=5)
    capture = _echo_of(ref)

    one = nlms(ref, capture, num_taps=NUM_TAPS, passes=1)
    two = nlms(ref, capture, num_taps=NUM_TAPS, passes=2)

    # Over the first second -- where pass 1 is still converging -- the
    # carried-over weights must do strictly better.
    first_s = slice(0, RATE)
    sup_one = suppression_db(capture[first_s], one.residual[first_s], RATE, LO, HI)
    sup_two = suppression_db(capture[first_s], two.residual[first_s], RATE, LO, HI)
    assert sup_two > sup_one + 3.0, (
        f"pass 2 ({sup_two:.1f} dB) should beat pass 1 ({sup_one:.1f} dB) early on"
    )


def test_guard_delay_keeps_marginally_acausal_path_reachable():
    """An alignment error that makes the path acausal is fixed by a guard shift.

    The driver shifts the capture by (offset - guard); modelled here by the
    echo arriving 5 samples EARLIER than the reference (acausal), then the
    caller delaying the capture by a 16-sample guard.
    """
    ref = _band_noise(4.0, seed=6)
    echo_acausal = np.concatenate([_echo_of(ref)[5:], np.zeros(5)])  # leads by 5

    guard = 16
    capture_guarded = np.concatenate([np.zeros(guard), echo_acausal[:-guard]])
    r = nlms(ref, capture_guarded, num_taps=NUM_TAPS)
    sl = slice(NUM_TAPS, None)
    sup = suppression_db(capture_guarded[sl], r.residual[sl], RATE, LO, HI)
    assert sup >= 20.0, f"guarded acausal path only suppressed {sup:.1f} dB"


def test_tail_energy_flags_truncated_path():
    ref = _band_noise(4.0, seed=7)
    capture = _echo_of(ref)

    ok = nlms(ref, capture, num_taps=NUM_TAPS)
    assert tail_energy_fraction(ok.impulse_response) < 0.05

    # A filter shorter than the path's furthest tap (75) piles energy at its end.
    short = nlms(ref, capture, num_taps=64)
    assert tail_energy_fraction(short.impulse_response) > 0.05


def test_suppression_profile_shape_and_convergence():
    ref = _band_noise(3.0, seed=8)
    capture = _echo_of(ref)
    r = nlms(ref, capture, num_taps=NUM_TAPS, passes=2)

    prof = suppression_profile(capture, r.residual, RATE, LO, HI, window_s=1.0)
    assert [t for t, _ in prof] == [0.0, 1.0, 2.0]
    # Converged (multi-pass) run: every window clears the target comfortably.
    assert all(db >= 12.0 for _, db in prof)


def test_clip_mask_pads_and_merges():
    x = np.zeros(100)
    x[40] = 5.0
    x[44] = -5.0
    mask = clip_mask(x, threshold=5.0, pad=3)
    assert mask[37:48].all()  # both rails plus padding, merged into one span
    assert not mask[:37].any() and not mask[48:].any()
    assert not clip_mask(np.zeros(10), threshold=5.0).any()


def test_mute_spans_silences_span_and_preserves_rest():
    x = np.ones(1000)
    mask = np.zeros(1000, dtype=bool)
    mask[500:520] = True
    out = mute_spans(x, mask, fade=48)
    assert np.all(out[mask] == 0.0)  # masked samples fully muted
    assert np.all(out[:400] == 1.0) and np.all(out[-400:] == 1.0)  # far field untouched
    ramp = out[500 - 48 : 500]
    assert np.all(np.diff(ramp) <= 1e-12)  # smooth monotonic fade in
    # fade=0 degenerates to a hard gate; no-op mask returns a copy.
    hard = mute_spans(x, mask, fade=0)
    assert np.all(hard[mask] == 0.0) and np.all(hard[~mask] == 1.0)
    assert np.array_equal(mute_spans(x, np.zeros(1000, dtype=bool), fade=48), x)


def test_clip_aware_ec_removes_saturation_clicks():
    """The first-audition failure class: a railed capture leaves residual clicks.

    Clip the synthetic capture at ~2.5x its RMS (beat-transient railing), then
    check the full clip-aware treatment (freeze adaptation on railed spans +
    mute the residual across them) kills the click energy the baseline run
    leaves behind.
    """
    ref = _band_noise(4.0, seed=9)
    bleed = _echo_of(ref)
    rail = 2.5 * float(np.sqrt(np.mean(bleed**2)))
    capture = np.clip(bleed, -rail, rail)
    mask = clip_mask(capture, threshold=rail, pad=8)
    assert mask.any(), "test premise: the synthetic capture must actually rail"

    base = nlms(ref, capture, num_taps=NUM_TAPS)
    aware = nlms(ref, capture, num_taps=NUM_TAPS, adapt_mask=~mask)
    repaired = mute_spans(aware.residual, mask, fade=32)

    sl = slice(NUM_TAPS, None)
    # Residual energy concentrated at the railed spans (the clicks) is gone.
    base_click_peak = float(np.max(np.abs(base.residual[sl][mask[sl]])))
    repaired_click_peak = float(np.max(np.abs(repaired[sl][mask[sl]])))
    assert repaired_click_peak == 0.0
    assert base_click_peak > 10.0 * float(np.std(base.residual[sl]))
    # And overall suppression does not get worse for the treatment.
    sup_base = suppression_db(capture[sl], base.residual[sl], RATE, LO, HI)
    sup_rep = suppression_db(capture[sl], repaired[sl], RATE, LO, HI)
    assert sup_rep >= sup_base - 0.1


def test_input_validation():
    x = np.zeros(100)
    with pytest.raises(ValueError, match="lengths differ"):
        nlms(x, np.zeros(99), num_taps=8)
    with pytest.raises(ValueError, match="num_taps"):
        nlms(x, x, num_taps=0)
    with pytest.raises(ValueError, match="shorter than num_taps"):
        nlms(x, x, num_taps=101)
    with pytest.raises(ValueError, match="mu"):
        nlms(x, x, num_taps=8, mu=2.5)
    with pytest.raises(ValueError, match="passes"):
        nlms(x, x, num_taps=8, passes=0)
    with pytest.raises(ValueError, match="lengths differ"):
        suppression_profile(np.zeros(10), np.zeros(9), RATE, LO, HI)
