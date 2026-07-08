"""Leak-vs-performance discrimination for vocal-take vetting (item 12).

A record-only vocal take (harness/scripts/run_vocal_take.sh) can correlate with
the reference at a sharp GCC-PHAT peak for two indistinguishable-by-PSR reasons:

  * a genuine playback leak -- the performer's monitored copy of the reference
    is acoustically reaching this phone's mic; or
  * the performance itself -- an in-time percussive/rap vocal locked to the beat
    produces a real correlated peak at the performance lag.

A peak alone cannot tell them apart. The discriminator here is lag stability
across take segments: a leak's lag is machine-stable (the two device clocks
drift well under 1 ms over a ~16 s take), while human performance timing jitters
by tens of ms syllable-to-syllable. A windowed argmax always returns *something*,
so a segment with no local maximum near the whole-take lag pins to the window
boundary -- only an interior peak is evidence, and only machine-stable interior
peaks across all segments indicate a leak.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from overdub_analysis.gcc_phat import gcc_phat


@dataclass(frozen=True)
class SegmentLag:
    """One segment's local lag relative to the whole-take alignment.

    ``edge_pinned`` is True when the windowed argmax landed at (or hard against)
    a lag-window boundary, meaning the segment has no interior peak near the
    whole-take lag -- not evidence of either a leak or a performance peak.
    """

    lag_ms: float
    edge_pinned: bool


@dataclass(frozen=True)
class LeakClassification:
    """Outcome of discriminating a suspicious whole-take correlation peak.

    ``leak`` is True only when every segment has an interior peak and those peaks
    agree within ``leak_spread_ms`` -- the machine-stable signature of a real
    playback leak. ``below_threshold`` means the whole-take peak was too weak to
    warrant discrimination (no leak concern). Otherwise ``leak`` is False: the
    correlation is the in-time performance / coincidental alignment, not
    contamination.
    """

    leak: bool
    below_threshold: bool
    segment_lags: list[SegmentLag]


def segment_lags(
    reference_bp: np.ndarray,
    take_bp: np.ndarray,
    rate: int,
    offset_samples: int,
    *,
    segment_s: float,
    lag_hw_s: float,
) -> list[SegmentLag]:
    """Per-segment local lags around the whole-take ``offset_samples`` peak.

    Each segment is correlated against the reference slice its content should
    align with (whole-reference-vs-segment would put late segments' true lag
    outside the FFT's representable range). The segment's expected local lag,
    in ``gcc_phat``'s mic-lags-positive convention, is ``offset_samples + a0 -
    start`` where ``a0`` is the slice start; the reported global lag is
    ``local_lag + start - a0``.
    """
    seg = int(rate * segment_s)
    pad = int(rate * lag_hw_s)
    out: list[SegmentLag] = []
    for start in range(0, len(take_bp) - seg + 1, seg):
        a0 = max(0, start - offset_samples - pad)
        ref_slice = reference_bp[a0 : start - offset_samples + seg + pad]
        expected_local = offset_samples + a0 - start
        rs = gcc_phat(
            ref_slice,
            take_bp[start : start + seg],
            fs=rate,
            lag_window=(expected_local - pad, expected_local + pad),
        )
        edge = abs(rs.offset_samples - (expected_local - pad)) <= 2 or abs(
            rs.offset_samples - (expected_local + pad)
        ) <= 2
        out.append(SegmentLag(lag_ms=(rs.offset_samples + start - a0) * 1000.0 / rate, edge_pinned=edge))
    return out


def classify_leak(
    reference_bp: np.ndarray,
    take_bp: np.ndarray,
    rate: int,
    *,
    psr_db: float,
    offset_samples: int,
    leak_psr_warn_db: float,
    segment_s: float,
    lag_hw_s: float,
    leak_spread_ms: float,
) -> LeakClassification:
    """Classify a whole-take correlation peak as a leak, a performance peak, or negligible."""
    if psr_db < leak_psr_warn_db:
        return LeakClassification(leak=False, below_threshold=True, segment_lags=[])
    lags = segment_lags(
        reference_bp, take_bp, rate, offset_samples, segment_s=segment_s, lag_hw_s=lag_hw_s
    )
    interior = [s.lag_ms for s in lags if not s.edge_pinned]
    leak = len(interior) == len(lags) and (max(interior) - min(interior)) <= leak_spread_ms
    return LeakClassification(leak=leak, below_threshold=False, segment_lags=lags)
