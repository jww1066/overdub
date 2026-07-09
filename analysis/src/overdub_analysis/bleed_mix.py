"""Bleed-mix listening-test math (design-summary.md "Echo cancellation for v1").

The vocal-injection study (doc/test2-sweep-results.md, item 12) measured that a
speaker-route overdub capture carries reference bleed ~12 dB *above* the vocal
in the analysis band (realistic vocal-to-bleed ratio -12.2 dB) -- so the stem a
downstream listener hears is bleed-dominated. Whether that aligned bleed reads
as benign on-beat "room" or objectionable comb-filter coloration in a real mix
is a listening question no automated metric answers; its outcome decides
whether offline on-device NLMS echo cancellation is v1 work (decided
2026-07-09, next analysis item).

This module holds the small, exactly-right-or-the-render-lies pieces of the
render pipeline; `analysis/scripts/render_bleed_mix.py` is the driver that
composes them with the existing click gate (`calibration_click`), correlator
(`gcc_phat`), and stem-construction math (`vocal_inject`).

Sign convention (matches ``gcc_phat`` and ``detect_click``): a capture's
offset ``tau`` is positive when the capture *lags* the reference, so
``capture[i + tau]`` is the sample simultaneous with ``reference[i]``.
"""

from __future__ import annotations

import numpy as np

from overdub_analysis.vocal_inject import inband_rms

__all__ = [
    "shift_to_reference_clock",
    "stem_gain_for_vocal_vs_ref",
    "master_gain",
    "loudness_match_gains",
]


def shift_to_reference_clock(
    x: np.ndarray, offset_samples: int, out_len: int
) -> np.ndarray:
    """Return ``x`` re-indexed to the reference clock: ``out[i] = x[i + offset]``.

    ``offset_samples`` is the signal's measured offset vs the reference
    (positive = ``x`` lags), so the result is aligned sample-for-sample with a
    ``out_len``-long reference. Regions with no source sample (the shifted-in
    edges, or an offset larger than the signal) are zero -- bounds are guarded
    explicitly rather than trusting Python's negative-index reinterpretation
    (the ``synth.delay`` negative-slice gotcha, doc/guides/offline-dsp.md).
    """
    x = np.asarray(x, dtype=np.float64).ravel()
    out = np.zeros(int(out_len), dtype=np.float64)
    src_lo = max(0, offset_samples)  # first readable source index
    dst_lo = max(0, -offset_samples)  # where it lands in the output
    n = min(len(x) - src_lo, len(out) - dst_lo)
    if n > 0:
        out[dst_lo : dst_lo + n] = x[src_lo : src_lo + n]
    return out


def stem_gain_for_vocal_vs_ref(
    reference: np.ndarray,
    vocal_component: np.ndarray,
    rate: int,
    target_db: float,
    *,
    lo: float,
    hi: float,
) -> float:
    """Single stem gain placing the stem's *vocal* at ``target_db`` vs the reference.

    The overdub stem is one file downstream, so a mixer can apply only ONE gain
    to it -- moving vocal and bleed together. The musically-meaningful anchor is
    the vocal ("bring the voice up to sit against the backing track"); the bleed
    then rides along at its captured level above the vocal. Returns ``g`` such
    that ``inband_rms(g * vocal_component) == 10^(target_db/20) *
    inband_rms(reference)``, both measured over the arrays as given (callers
    slice both to the same content region first, or the reference's silent
    lead-in dilutes its RMS).
    """
    ref_rms = inband_rms(reference, rate, lo, hi)
    voc_rms = inband_rms(vocal_component, rate, lo, hi)
    if voc_rms <= 0.0:
        raise ValueError("vocal component has no in-band energy; cannot anchor the stem gain")
    return (10.0 ** (target_db / 20.0)) * ref_rms / voc_rms


def master_gain(signals: list[np.ndarray], peak_frac: float = 0.9) -> float:
    """One shared gain normalizing a render *set* to ``peak_frac`` of int16 full scale.

    A single gain across every file keeps the A/B comparisons honest: per-file
    normalization would silently loudness-match renders whose whole point is
    that one carries more energy (bleed) than another. Use this when the
    *level* difference is the finding (the bleed's +12 dB dominance). For a
    coloration A/B -- "is the bleed objectionable at equal loudness" -- use
    :func:`loudness_match_gains` instead, and preserve the real levels in a
    manifest so the dominance stays documented.
    """
    peak = max((float(np.max(np.abs(s))) if len(s) else 0.0) for s in signals)
    if peak <= 0.0:
        raise ValueError("all renders are silent; nothing to normalize")
    return peak_frac * 32767.0 / peak


def loudness_match_gains(
    signals: list[np.ndarray], target_rms: float | None = None
) -> tuple[list[float], float]:
    """Per-render gains bringing every render to a common broadband RMS (loudness proxy).

    Returns ``(gains, target_rms)``. The target defaults to the *minimum* non-zero
    RMS in the set, so the loudest renders are attenuated to match the quietest
    rather than the quietest's noise floor being amplified -- a level-matched A/B
    that does not manufacture hiss by turning up a low-energy render. A render
    with zero RMS gets gain 0 (stays silent). Pair with a final peak-safety scale
    in the caller (these gains match loudness but do not prevent clipping).

    Use this when the A/B question is *coloration/timbre*, not level: the renders
    come out equal-loudness so the ear judges what differs (bleed coloration,
    hiss), not what's louder. The real level relationships (the bleed's in-band
    dominance) must be recorded separately -- they are intentionally flattened
    here, so the listening comparison is fair.
    """
    rms = [float(np.sqrt(np.mean(s**2))) if len(s) else 0.0 for s in signals]
    nonzero = [r for r in rms if r > 0.0]
    if not nonzero:
        raise ValueError("all renders are silent; nothing to loudness-match")
    target = float(target_rms) if target_rms is not None else min(nonzero)
    gains = [target / r if r > 0.0 else 0.0 for r in rms]
    return gains, target
