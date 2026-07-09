"""Vocal-interference injection for the item-12 study (doc/test2-step2-plan.md).

Production correlates through a loud vocal sitting in the 500-4000 Hz analysis
band, not the quiet room the Session A sweep measured against. This module
mixes a dry close-mic vocal take into a click-bearing capture at a controlled
*vocal-to-bleed ratio measured in-band* (not broadband -- the vocal's energy is
concentrated in the analysis band, so the broadband ratio understates how loud
it is where the correlator looks), so a driver script can re-judge the click
gate and find where the vocal starts pulling the alignment off the bleed peak.

Two pieces of math worth being explicit about:

  * **In-band ratio.** Band-passing is linear, so scaling the (broadband) vocal
    by ``s`` scales its in-band RMS by ``s``. To hit a target in-band ratio ``R``
    (dB) against a capture whose in-band bleed RMS is ``B`` and a vocal whose
    in-band RMS is ``V``: ``s = 10^(R/20) * B / V``.

  * **Placement.** In production the performer monitors the reference on
    headphones (~0 latency) and performs in time, so the vocal reaches the mic
    at the reference's timing while the bleed is the reference delayed by the
    speaker->mic round-trip. Expressing both in the capture's sample clock: if
    the vocal lags the reference by ``tau_v`` (its whole-take GCC-PHAT peak) and
    the capture's click offsets the reference by ``tau_c`` (detected click onset
    minus the reference's click position), then ``mix[i] = capture[i] +
    s * vocal[i + (tau_v - tau_c)]``. This puts the vocal at its performed
    timing relative to the capture -- the in-time (worst) case for the
    correlator. ``tau_v`` is the performer's tempo alignment (approximate -- the
    whole-take peak is tempo-correlated but segment-unstable, per
    ``leak_detect``); the ratio, not the placement, is the primary variable.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, filtfilt

from overdub_analysis.gcc_phat import gcc_phat


def bandpass(x: np.ndarray, lo: float, hi: float, fs: int) -> np.ndarray:
    """Zero-phase Butterworth band-pass ``lo``-``hi`` Hz of a 1-D signal."""
    b, a = butter(4, [lo / (fs / 2), hi / (fs / 2)], btype="band")
    return filtfilt(b, a, x)


def inband_rms(x: np.ndarray, rate: int, lo: float, hi: float) -> float:
    """RMS of ``x`` after band-passing to ``lo``-``hi`` Hz (the analysis band)."""
    return float(np.sqrt(np.mean(bandpass(x, lo, hi, rate) ** 2)))


def vocal_placement_samples(
    reference_bp: np.ndarray,
    vocal_bp: np.ndarray,
    rate: int,
    capture_click_offset_samples: int,
) -> int:
    """Sample shift placing the vocal at its performed timing in the capture.

    ``capture_click_offset_samples`` is the capture's click ground-truth offset
    (``detect_click(capture).onset_sample - PRE_SILENCE_S * rate``), i.e. ``tau_c``.
    Returns ``tau_v - tau_c`` (see module docstring); ``mix[i] += s * vocal[i + shift]``.
    """
    tau_v = gcc_phat(reference_bp, vocal_bp, fs=rate).offset_samples
    return int(tau_v - capture_click_offset_samples)


def mix_at_inband_ratio(
    capture: np.ndarray,
    vocal: np.ndarray,
    rate: int,
    target_ratio_db: float,
    *,
    lo: float,
    hi: float,
    placement_samples: int,
) -> np.ndarray:
    """Mix ``vocal`` into ``capture`` at the target in-band vocal-to-bleed ratio.

    The capture's in-band bleed RMS is measured from ``capture``; the vocal is
    scaled so its in-band RMS in the mix hits ``10^(target_ratio_db/20) * bleed``,
    then placed at ``placement_samples`` (see module docstring). Returns the mix
    as float64 (NOT clipped to int16 -- clipping would add nonlinear distortion
    that could itself perturb the correlation; a caller that finds the mix
    exceeds int16 should treat that ratio as unrealizable on real hardware).
    """
    bleed = inband_rms(capture, rate, lo, hi)
    voice = inband_rms(vocal, rate, lo, hi)
    if voice <= 0.0:
        return capture.astype(np.float64).copy()
    scale = (10.0 ** (target_ratio_db / 20.0)) * bleed / voice
    mix = capture.astype(np.float64).copy()
    shift = placement_samples
    if shift >= 0:
        n = min(len(mix), len(vocal) - shift)
        if n > 0:
            mix[:n] += scale * vocal[shift : shift + n]
    else:
        n = min(len(mix) + shift, len(vocal))
        if n > 0:
            mix[-shift : -shift + n] += scale * vocal[:n]
    return mix
