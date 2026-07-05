"""GCC-PHAT time-delay estimation.

Implements Generalized Cross-Correlation with Phase Transform (GCC-PHAT),
Knapp & Carter 1976, used by Test 2 step 1 (`doc/prototype-plan.md`) to
validate that the alignment algorithm recovers a clean, usable peak before
any real-bleed capture is judged against it.

Convention
----------
``gcc_phat(reference, mic, fs)`` returns the delay of ``mic`` relative to
``reference`` in samples and seconds:

    mic[n] ≈ reference[n - d]   ⟹   offset_samples == d   (d > 0: mic lags)

So a positive offset means the mic signal is the reference delayed later in
time, which is the physically expected case for the overdub app (the bleed of
the reference track arrives at the mic some round-trip latency after the
speaker emits it).

Peak-to-sidelobe ratio (PSR) is reported in dB as

    PSR_dB = 20 * log10(peak_magnitude / largest_sidelobe_magnitude)

where the sidelobe is the largest GCC magnitude outside an exclusion window of
half-width ``psr_exclusion`` samples around the main peak. PSR is the
"trustworthiness" metric the prototype-plan thresholds gate on (≥6 dB minimum,
≥10 dB confident).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["GccPhatResult", "gcc_phat"]


@dataclass(frozen=True)
class GccPhatResult:
    """Outcome of a GCC-PHAT alignment run.

    Attributes
    ----------
    offset_samples :
        Estimated delay of ``mic`` relative to ``reference``, in samples.
        Positive means ``mic`` lags ``reference`` (see module docstring).
    offset_seconds :
        ``offset_samples / fs``. ``None`` if ``fs`` was not provided.
    psr_db :
        Peak-to-sidelobe ratio in dB. ``np.inf`` if no sidelobe exists
        (e.g. a degenerate all-zero signal outside the peak).
    lag_index :
        Raw index of the peak in the (unshifted) GCC vector, kept for
        diagnostics; callers should normally use ``offset_samples``.
    """

    offset_samples: int
    offset_seconds: float | None
    psr_db: float
    lag_index: int


def _cross_spectrum_phat(
    x: np.ndarray, y: np.ndarray, nfft: int, eps: float
) -> np.ndarray:
    """PHAT-weighted cross-spectrum, returned as a time-domain GCC vector.

    The cross-spectrum is ``X * conj(Y)``; PHAT weighting divides it by its
    own magnitude, discarding amplitude information and retaining only phase,
    which is what sharpens the correlation peak for broadband signals.
    """
    X = np.fft.fft(x, n=nfft)
    Y = np.fft.fft(y, n=nfft)
    cross = X * np.conj(Y)
    weighted = cross / (np.abs(cross) + eps)
    return np.real(np.fft.ifft(weighted))


def gcc_phat(
    reference: np.ndarray,
    mic: np.ndarray,
    fs: float | None = None,
    *,
    eps: float = 1e-12,
    psr_exclusion: int = 2,
) -> GccPhatResult:
    """Estimate the time delay of ``mic`` relative to ``reference`` via GCC-PHAT.

    Parameters
    ----------
    reference, mic :
        1-D real-valued signals of equal or differing length. Both are treated
        as zero-padded to ``nfft`` internally.
    fs :
        Sample rate in Hz, used only to convert the offset to seconds. If
        ``None``, ``offset_seconds`` is ``None``.
    eps :
        Numerical floor under the cross-spectrum magnitude before division, to
        avoid division by zero on silent bands.
    psr_exclusion :
        Half-width (in samples) of the window around the main peak excluded
        from sidelobe level computation. Must be ≥ 0.

    Returns
    -------
    GccPhatResult
    """
    x = np.asarray(reference, dtype=np.float64).ravel()
    y = np.asarray(mic, dtype=np.float64).ravel()
    if x.size == 0 or y.size == 0:
        raise ValueError("reference and mic must be non-empty")
    if psr_exclusion < 0:
        raise ValueError("psr_exclusion must be >= 0")

    # FFT length: next power of two ≥ full cross-correlation length, so the
    # circular correlation is equivalent to a linear one (no wrap-around).
    nfft = 1 << int(np.ceil(np.log2(x.size + y.size - 1)))

    gcc = _cross_spectrum_phat(x, y, nfft, eps)

    lag_index = int(np.argmax(gcc))
    peak = float(gcc[lag_index])

    # Map the raw [0, nfft) index to a signed lag. Indices above nfft//2
    # represent negative lags under the periodic FFT convention. With the
    # cross-spectrum X*conj(Y), gcc[m] = Σ_n x[n]·y[n−m], which peaks at
    # m = −d when mic[n] = reference[n−d]; the sign flip below recovers d.
    if lag_index > nfft // 2:
        signed_lag = lag_index - nfft
    else:
        signed_lag = lag_index
    offset_samples = -signed_lag

    offset_seconds = (
        None if fs is None else offset_samples / float(fs)
    )

    psr_db = _psr_db(gcc, peak, lag_index, psr_exclusion, nfft)

    return GccPhatResult(
        offset_samples=offset_samples,
        offset_seconds=offset_seconds,
        psr_db=psr_db,
        lag_index=lag_index,
    )


def _psr_db(
    gcc: np.ndarray, peak: float, peak_idx: int, exclusion: int, nfft: int
) -> float:
    """Peak-to-sidelobe ratio in dB, excluding ±``exclusion`` around the peak."""
    if exclusion >= nfft // 2:
        # The exclusion window covers the whole vector — no sidelobes to speak of.
        return float("inf")

    lo = max(0, peak_idx - exclusion)
    hi = min(nfft, peak_idx + exclusion + 1)
    mask = np.ones(nfft, dtype=bool)
    mask[lo:hi] = False
    sidelobes = np.abs(gcc[mask])
    if sidelobes.size == 0 or sidelobes.max() <= 0:
        return float("inf")
    return float(20.0 * np.log10(peak / sidelobes.max()))
