"""Tests for the vocal-injection mixing math (doc/test2-step2-plan.md item 12).

The two things that must be exactly right because the study's conclusions ride
on them: the achieved in-band ratio equals the target (else the sweep's dB axis
is a fiction), and the placement formula puts the vocal at the performed timing
(else the worst-case in-time alignment is missed and the test is too easy).
"""

from __future__ import annotations

import numpy as np

from overdub_analysis.gcc_phat import gcc_phat
from overdub_analysis.vocal_inject import (
    bandpass,
    inband_rms,
    mix_at_inband_ratio,
    vocal_placement_samples,
)

RATE = 48000
LO, HI = 500.0, 4000.0


def _tone(freq: float, n: int, amp: float = 1.0) -> np.ndarray:
    t = np.arange(n) / RATE
    return amp * np.sin(2 * np.pi * freq * t)


def test_inband_rms_isolates_the_analysis_band():
    n = RATE * 2
    in_band = _tone(1000.0, n, 1.0)  # 1 kHz, inside 500-4000
    out_of_band = _tone(100.0, n, 1.0)  # 100 Hz, outside
    assert inband_rms(in_band, RATE, LO, HI) > 0.6  # passes the band
    assert inband_rms(out_of_band, RATE, LO, HI) < 0.05  # rejected by the band


def test_mix_achieves_the_target_inband_ratio():
    # capture = 1 kHz bleed in-band; vocal = 2 kHz (also in-band, distinct so they
    # don't constructively interfere in the RMS). Both well above any filter edge.
    n = RATE * 4
    capture = _tone(1000.0, n, 1000.0)
    vocal = _tone(2000.0, n, 500.0)
    for target_db in (-18.0, -12.0, -6.0, 0.0, 6.0):
        mix = mix_at_inband_ratio(capture, vocal, RATE, target_db, lo=LO, hi=HI, placement_samples=0)
        # The vocal's in-band energy in the mix is what we scaled; recover it by
        # subtracting the (unchanged) bleed energy in quadrature -- the two tones
        # are orthogonal frequencies, so RMS(mix) ~= sqrt(bleed^2 + vocal_mix^2).
        bleed = inband_rms(capture, RATE, LO, HI)
        mix_total = inband_rms(mix, RATE, LO, HI)
        vocal_in_mix = np.sqrt(max(mix_total**2 - bleed**2, 0.0))
        achieved_db = 20 * np.log10(vocal_in_mix / bleed)
        assert abs(achieved_db - target_db) < 0.5, (target_db, achieved_db)


def test_zero_ratio_is_the_capture_plus_silent_vocal():
    n = RATE * 2
    capture = _tone(1000.0, n, 1000.0)
    vocal = _tone(2000.0, n, 500.0)
    mix = mix_at_inband_ratio(capture, vocal, RATE, -120.0, lo=LO, hi=HI, placement_samples=0)
    # -120 dB: the vocal is effectively inaudible; the mix is the capture.
    assert np.max(np.abs(mix - capture)) < 1.0


def test_placement_puts_vocal_at_performed_timing():
    # Build a reference, a "vocal" that is the reference delayed by a known tau_v
    # (a genuine waveform alignment, so the whole-take GCC peak is stable), and a
    # "capture" whose click offset is a known tau_c. The placement formula must
    # return tau_v - tau_c.
    n = RATE * 8
    rng = np.random.default_rng(0)
    reference = rng.standard_normal(n)
    tau_v = int(0.050 * RATE)  # vocal lags reference by 50 ms
    vocal = np.concatenate([np.zeros(tau_v), reference[: n - tau_v]])
    tau_c = int(-0.080 * RATE)  # capture leads reference by 80 ms (the real sign)
    ref_bp = bandpass(reference, LO, HI, RATE)
    voc_bp = bandpass(vocal, LO, HI, RATE)
    shift = vocal_placement_samples(ref_bp, voc_bp, RATE, tau_c)
    assert shift == tau_v - tau_c, (shift, tau_v - tau_c)
    # And gcc confirms the vocal's lag is tau_v (sanity on the convention).
    assert gcc_phat(ref_bp, voc_bp, fs=RATE).offset_samples == tau_v


def test_mix_placement_aligns_vocal_to_capture_reference_timing():
    # End-to-end on the placement: (mix - capture) is exactly the scaled vocal at
    # the placement shift, with zeros outside the overlap. Verify the arithmetic
    # directly rather than via GCC-PHAT (the zero tail outside the overlap makes a
    # PHAT peak fragile, and the capture-self peak would dominate a capture-vs-mix
    # correlation anyway). placement_samples itself is proven exact by the test above.
    n = RATE * 8
    rng = np.random.default_rng(1)
    reference = rng.standard_normal(n)
    tau_c = int(-0.080 * RATE)
    if tau_c < 0:
        capture = np.concatenate([reference[-tau_c:], np.zeros(-tau_c)])
    else:
        capture = np.concatenate([np.zeros(tau_c), reference[: n - tau_c]])
    tau_v = int(0.050 * RATE)
    vocal = np.concatenate([np.zeros(tau_v), reference[: n - tau_v]])
    ref_bp = bandpass(reference, LO, HI, RATE)
    voc_bp = bandpass(vocal, LO, HI, RATE)
    shift = vocal_placement_samples(ref_bp, voc_bp, RATE, tau_c)
    assert shift > 0  # tau_v - tau_c = 50 - (-80) = 130 ms
    mix = mix_at_inband_ratio(capture, vocal, RATE, 0.0, lo=LO, hi=HI, placement_samples=shift)
    diff = mix - capture.astype(np.float64)
    overlap = min(len(capture), len(vocal) - shift)
    # In the overlap, diff is the placed vocal (perfectly correlated with vocal[shift:]).
    assert np.corrcoef(diff[:overlap], vocal[shift : shift + overlap])[0, 1] > 0.999
    # Outside the overlap (the tail), nothing was added.
    assert np.max(np.abs(diff[overlap:])) < 1e-6
