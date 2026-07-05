"""Synthetic signal helpers for Test 2 step 1 validation.

These exist purely to drive `gcc_phat` with known ground truth (a known
integer-sample delay and a controlled noise level) so the algorithm can be
verified independently of any physical phone-speaker-to-phone-mic setup, per
`doc/prototype-plan.md`'s "synthetic validation first" sequencing.

They are intentionally simple — broadband clicks/impulses are the easiest
case for GCC-PHAT, which is exactly what you want for an "is the code correct"
gate before mapping where real bleed degrades it.
"""

from __future__ import annotations

import numpy as np

__all__ = ["broadband_click_train", "delay", "add_noise_at_snr"]


def broadband_click_train(
    n: int, *, period: int = 1000, click_width: int = 8, rng: np.random.Generator
) -> np.ndarray:
    """Return a length-``n`` signal of periodic clicks suitable as a reference.

    A periodic click train is broadband (energy spread across frequencies, so
    the PHAT-weighted correlation has a sharp peak) and repetitive enough that
    a multi-second reference has many alignment opportunities, loosely mirroring
    a beatbox track's percussive content without pretending to model it.

    Parameters
    ----------
    n :
        Total length in samples.
    period :
        Samples between click onsets.
    click_width :
        Width of each click's exponential decay in samples; small enough to
        keep clicks broadband.
    rng :
        NumPy random generator used only for the per-click polarity jitter, so
        calls are reproducible given a seeded generator.
    """
    if period <= 0 or click_width <= 0:
        raise ValueError("period and click_width must be positive")
    sig = np.zeros(n, dtype=np.float64)
    decay = np.exp(-np.linspace(0.0, 6.0, click_width))
    starts = list(range(0, n - click_width, period))
    # Random polarity per click keeps the signal from being a perfectly
    # periodic comb — closer to real percussive material — without changing
    # the broadband spectrum that GCC-PHAT relies on.
    polarities = rng.choice([-1.0, 1.0], size=len(starts))
    for i, s in enumerate(starts):
        sig[s : s + click_width] += polarities[i] * decay
    # Normalize to a comfortable amplitude (-3 dBFS peak).
    peak = np.max(np.abs(sig))
    if peak > 0:
        sig *= 10.0 ** (-3.0 / 20.0) / peak
    return sig


def delay(signal: np.ndarray, d: int) -> np.ndarray:
    """Return ``signal`` shifted right by ``d`` samples, zero-padded.

    ``delay(s, d)[n] = s[n - d]`` where in-bounds, zero otherwise, so a
    positive ``d`` produces a signal that is ``d`` samples later — matching
    the convention ``gcc_phat`` reports. A negative ``d`` shifts left and
    pads the tail with zeros. Output length is ``len(s) + abs(d)``.
    """
    s = np.asarray(signal, dtype=np.float64).ravel()
    d = int(d)
    out = np.zeros(s.size + abs(d), dtype=np.float64)
    if d >= 0:
        out[d : d + s.size] = s
    else:
        # Left shift by |d|: the first s.size-|d| samples are s[|d|:]; rest zero.
        out[: s.size + d] = s[-d:]
    return out


def add_noise_at_snr(
    signal: np.ndarray, snr_db: float, rng: np.random.Generator
) -> np.ndarray:
    """Return ``signal`` plus white Gaussian noise scaled to a target SNR.

    SNR is signal-power / noise-power in dB, computed on the *full* signal
    length (including any silence), so the caller controls exactly what SNR
    means by what signal they pass in.
    """
    s = np.asarray(signal, dtype=np.float64).ravel()
    sig_power = float(np.mean(s**2))
    if sig_power <= 0:
        raise ValueError("signal has zero power; cannot set a meaningful SNR")
    noise_power = sig_power / (10.0 ** (snr_db / 10.0))
    noise = rng.standard_normal(s.size) * np.sqrt(noise_power)
    return s + noise
