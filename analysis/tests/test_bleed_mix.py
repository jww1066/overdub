"""Tests for the bleed-mix render math (design-summary.md echo-cancellation item).

What must be exactly right because the listening verdict rides on it: the
alignment shift puts capture content at the reference's sample positions (else
the render manufactures a misalignment artifact the product wouldn't have), the
stem gain lands the vocal at the stated level vs the reference (else the A/B
levels are a fiction), and the master gain is shared (else the renders are
silently loudness-matched).
"""

from __future__ import annotations

import numpy as np
import pytest

from overdub_analysis.bleed_mix import (
    loudness_match_gains,
    master_gain,
    shift_to_reference_clock,
    stem_gain_for_vocal_vs_ref,
)
from overdub_analysis.vocal_inject import inband_rms

RATE = 48000
LO, HI = 500.0, 4000.0


def _tone(freq: float, n: int, amp: float = 1.0) -> np.ndarray:
    t = np.arange(n) / RATE
    return amp * np.sin(2 * np.pi * freq * t)


def test_shift_zero_offset_is_identity_with_length_fitting():
    x = np.arange(10, dtype=np.float64)
    out = shift_to_reference_clock(x, 0, 6)
    assert np.array_equal(out, x[:6])
    out = shift_to_reference_clock(x, 0, 14)
    assert np.array_equal(out[:10], x)
    assert np.all(out[10:] == 0.0)


def test_shift_negative_offset_aligns_a_leading_capture():
    # The real Session A case: the capture LEADS the reference (tau ~ -80 ms),
    # i.e. reference[i] content appears at capture[i + tau]. Build exactly that
    # capture, shift it back, and demand sample-exact alignment.
    n = 4000
    reference = np.random.default_rng(0).standard_normal(n)
    tau = -300
    capture = np.zeros(n)
    capture[: n + tau] = reference[-tau:]  # capture[i + tau] == reference[i]
    aligned = shift_to_reference_clock(capture, tau, n)
    assert np.array_equal(aligned[-tau : n + tau], reference[-tau : n + tau])
    assert np.all(aligned[: -tau] == 0.0)  # shifted-in edge is zero, not wrapped


def test_shift_positive_offset_aligns_a_lagging_capture():
    n = 4000
    reference = np.random.default_rng(1).standard_normal(n)
    tau = 250
    capture = np.zeros(n)
    capture[tau:] = reference[: n - tau]  # capture lags: capture[i + tau] == reference[i]
    aligned = shift_to_reference_clock(capture, tau, n)
    assert np.array_equal(aligned[: n - 2 * tau], reference[: n - 2 * tau])


def test_shift_beyond_signal_length_is_all_zeros_not_a_wrap():
    # The negative-slice gotcha's home turf: an offset larger than the signal
    # must yield silence, never a resurrected slice from the wrong end.
    x = np.ones(100)
    assert np.all(shift_to_reference_clock(x, 500, 100) == 0.0)
    assert np.all(shift_to_reference_clock(x, -500, 100) == 0.0)


def test_stem_gain_lands_vocal_at_target_vs_reference():
    n = RATE * 2
    reference = _tone(1000.0, n, 8000.0)
    vocal = _tone(2000.0, n, 130.0)  # arbitrary captured level
    for target_db in (-6.0, 0.0, 3.0):
        g = stem_gain_for_vocal_vs_ref(reference, vocal, RATE, target_db, lo=LO, hi=HI)
        achieved = 20 * np.log10(
            inband_rms(g * vocal, RATE, LO, HI) / inband_rms(reference, RATE, LO, HI)
        )
        assert abs(achieved - target_db) < 0.1, (target_db, achieved)


def test_stem_gain_rejects_a_silent_vocal():
    with pytest.raises(ValueError):
        stem_gain_for_vocal_vs_ref(_tone(1000.0, RATE), np.zeros(RATE), RATE, 0.0, lo=LO, hi=HI)


def test_master_gain_is_shared_and_hits_the_peak_fraction():
    quiet = 0.1 * np.ones(100)
    loud = 4.0 * np.ones(100)
    g = master_gain([quiet, loud], peak_frac=0.9)
    assert abs(g * 4.0 - 0.9 * 32767.0) < 1e-6  # loudest render sits at the target peak
    assert g * 0.1 < 0.9 * 32767.0  # the quiet one keeps its relative level


def test_loudness_match_brings_all_renders_to_equal_rms():
    quiet = 0.1 * np.ones(1000)
    loud = 4.0 * np.ones(1000)
    gains, target = loudness_match_gains([quiet, loud])
    assert abs(target - 0.1) < 1e-9  # targets the quietest, does not upscale noise
    rms_q = float(np.sqrt(np.mean((gains[0] * quiet) ** 2)))
    rms_l = float(np.sqrt(np.mean((gains[1] * loud) ** 2)))
    assert abs(rms_q - rms_l) < 1e-6  # equal loudness
    assert gains[1] < gains[0]  # the loud render is attenuated, not the quiet one amplified


def test_loudness_match_zero_rms_stays_silent():
    gains, _ = loudness_match_gains([np.zeros(100), np.ones(100)])
    assert gains[0] == 0.0  # silent render is not amplified into noise
