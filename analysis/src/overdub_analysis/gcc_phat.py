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

__all__ = ["GccPhatResult", "gcc_phat", "gcc_phat_correlation"]


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


def gcc_phat_correlation(
    reference: np.ndarray,
    mic: np.ndarray,
    *,
    eps: float = 1e-12,
) -> tuple[np.ndarray, np.ndarray]:
    """Full PHAT-weighted cross-correlation with the offset each index maps to.

    Returns ``(gcc, offset_all)``: ``gcc[i]`` is the correlation value whose
    recovered offset (same sign convention as ``gcc_phat``: positive = mic
    lags reference) is ``offset_all[i]``. This is the raw vector ``gcc_phat``
    takes its argmax over; it exists so diagnostics can inspect *competing*
    peaks — e.g. a beat-period alias of a rhythmic reference vs. the true
    alignment peak — rather than only seeing the single winner.
    """
    x = np.asarray(reference, dtype=np.float64).ravel()
    y = np.asarray(mic, dtype=np.float64).ravel()
    if x.size == 0 or y.size == 0:
        raise ValueError("reference and mic must be non-empty")

    # FFT length: next power of two ≥ full cross-correlation length, so the
    # circular correlation is equivalent to a linear one (no wrap-around).
    nfft = 1 << int(np.ceil(np.log2(x.size + y.size - 1)))

    gcc = _cross_spectrum_phat(x, y, nfft, eps)

    # Offset (samples) for every raw index, vectorized. Indices above nfft//2
    # represent negative lags under the periodic FFT convention. With the
    # cross-spectrum X*conj(Y), gcc[m] = Σ_n x[n]·y[n−m], which peaks at
    # m = −d when mic[n] = reference[n−d]; the sign flip recovers d.
    idx = np.arange(nfft)
    signed_lag_all = np.where(idx > nfft // 2, idx - nfft, idx)
    offset_all = -signed_lag_all
    return gcc, offset_all


def gcc_phat(
    reference: np.ndarray,
    mic: np.ndarray,
    fs: float | None = None,
    *,
    eps: float = 1e-12,
    psr_exclusion: int = 2,
    lag_window: tuple[int | None, int | None] | None = None,
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
    lag_window :
        Optional ``(min_offset, max_offset)`` bound, in **samples of offset**
        (same sign convention as ``offset_samples``: positive = mic lags), that
        restricts *both* the peak search and the sidelobe (PSR) search to
        physically plausible offsets. Either endpoint may be ``None`` for an
        open bound. ``None`` (the default) searches the whole correlation and
        preserves the original unconstrained behavior.

        This exists because an unconstrained argmax over the full circular
        correlation can win on a *wraparound alias* — a sharp peak at an offset
        near ±(signal length) — which is physically impossible for a
        speaker→mic round-trip yet still scores a high PSR. A real capture path
        has a bounded, positive latency (e.g. ``(0, int(0.3 * fs))`` for
        0–300 ms); constraining to it removes those aliases and makes PSR a
        trustworthy sidelobe ratio *within the plausible set* rather than
        against the whole vector.

    Returns
    -------
    GccPhatResult
    """
    if psr_exclusion < 0:
        raise ValueError("psr_exclusion must be >= 0")

    gcc, offset_all = gcc_phat_correlation(reference, mic, eps=eps)
    nfft = gcc.size

    if lag_window is not None:
        candidate_mask = _lag_window_mask(offset_all, lag_window)
        if not candidate_mask.any():
            raise ValueError(f"lag_window {lag_window} selects no samples in [{-(nfft // 2)}, {nfft // 2}]")
        # Restrict argmax to the plausible offsets.
        masked = np.where(candidate_mask, gcc, -np.inf)
        lag_index = int(np.argmax(masked))
    else:
        candidate_mask = None
        lag_index = int(np.argmax(gcc))

    peak = float(gcc[lag_index])
    offset_samples = int(offset_all[lag_index])
    offset_seconds = None if fs is None else offset_samples / float(fs)

    psr_db = _psr_db(gcc, peak, lag_index, psr_exclusion, nfft, candidate_mask)

    return GccPhatResult(
        offset_samples=offset_samples,
        offset_seconds=offset_seconds,
        psr_db=psr_db,
        lag_index=lag_index,
    )


def _lag_window_mask(
    offset_all: np.ndarray, lag_window: tuple[int | None, int | None]
) -> np.ndarray:
    """Boolean mask of indices whose recovered offset lies within ``lag_window``."""
    lo, hi = lag_window
    mask = np.ones(offset_all.shape, dtype=bool)
    if lo is not None:
        mask &= offset_all >= lo
    if hi is not None:
        mask &= offset_all <= hi
    return mask


def _psr_db(
    gcc: np.ndarray,
    peak: float,
    peak_idx: int,
    exclusion: int,
    nfft: int,
    candidate_mask: np.ndarray | None = None,
) -> float:
    """Peak-to-sidelobe ratio in dB, excluding ±``exclusion`` around the peak.

    When ``candidate_mask`` is given (a lag-window restriction), sidelobes are
    measured only within that window — the ratio is then against the largest
    competing peak in the *plausible* set, not against a wraparound alias
    outside it that no valid alignment could ever have chosen.
    """
    if exclusion >= nfft // 2:
        # The exclusion window covers the whole vector — no sidelobes to speak of.
        return float("inf")

    lo = max(0, peak_idx - exclusion)
    hi = min(nfft, peak_idx + exclusion + 1)
    mask = np.ones(nfft, dtype=bool) if candidate_mask is None else candidate_mask.copy()
    mask[lo:hi] = False
    sidelobes = np.abs(gcc[mask])
    if sidelobes.size == 0 or sidelobes.max() <= 0:
        return float("inf")
    return float(20.0 * np.log10(peak / sidelobes.max()))
