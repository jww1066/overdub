"""Decompose the GCC-PHAT sweep offset into harness start-jitter vs real alignment error.

test2-step2-plan.md item 10 / doc/guides/offline-dsp.md ("run-to-run spread can be a measurement
artifact"). The band-limited GCC-PHAT sweep recovered per-cell offsets spanning 61-151 ms
(std 17.5 ms, larger than the whole 15 ms drift budget). But each sweep cell is an
*independently-started* output+input Oboe stream pair, so its GCC-PHAT offset is:

    gcc_phat_offset = acoustic_round_trip (~constant on one device)
                    + stream_start_misalignment (per-session harness jitter)

The harness now logs the second term directly, derived from each stream's ``getTimestamp()``
(``stream_offset_ms`` in the JSON sidecar, same sign convention as the GCC-PHAT offset). Subtracting
it leaves the residual:

    residual = gcc_phat_offset - stream_offset

If the 61-151 ms spread was harness start-jitter, the residual collapses to a small, roughly-constant
acoustic term (residual std << gcc-phat std). If it stays wide, the misalignment is real and the
timestamps did not explain it. This module holds the pure arithmetic so it is unit-testable; the CLI
that reads the sweep CSV + JSON sidecars is ``scripts/decompose_offset.py``.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class OffsetRecord:
    """One sweep cell: its GCC-PHAT offset, and the harness stream offset if timestamps were logged.

    ``stream_offset_ms`` is ``None`` for captures taken before item 10 shipped (or on a device where
    ``getTimestamp()`` was unavailable) -- those still count toward the total but carry no residual.
    """

    condition_id: str
    gcc_phat_offset_ms: float
    stream_offset_ms: float | None

    @property
    def residual_ms(self) -> float | None:
        """gcc_phat_offset - stream_offset, i.e. the term left after removing harness start-jitter."""
        if self.stream_offset_ms is None:
            return None
        return self.gcc_phat_offset_ms - self.stream_offset_ms


@dataclass(frozen=True)
class ResidualSummary:
    """Aggregate spread of the raw GCC-PHAT offsets vs the timestamp-corrected residuals.

    The headline is ``residual_std`` vs ``gcc_phat_std``: a large drop means the cross-cell offset
    spread was harness measurement jitter (benign, removed by the timestamps), not the estimator
    disagreeing about alignment. ``residual_*`` are ``None`` when no cell carried a stream offset.
    """

    n_total: int
    n_with_timestamps: int
    gcc_phat_mean_ms: float
    gcc_phat_std_ms: float
    residual_mean_ms: float | None
    residual_std_ms: float | None


def summarize(records: list[OffsetRecord]) -> ResidualSummary:
    """Compute the offset/residual spread over a set of sweep cells.

    ``gcc_phat_*`` cover every record; ``residual_*`` cover only those with a logged stream offset.
    Uses population std (``pstdev``) so a single record yields 0.0 rather than raising.
    """
    if not records:
        raise ValueError("summarize() needs at least one record")

    gcc = [r.gcc_phat_offset_ms for r in records]
    residuals = [r.residual_ms for r in records if r.residual_ms is not None]

    return ResidualSummary(
        n_total=len(records),
        n_with_timestamps=len(residuals),
        gcc_phat_mean_ms=statistics.fmean(gcc),
        gcc_phat_std_ms=statistics.pstdev(gcc) if len(gcc) > 1 else 0.0,
        residual_mean_ms=statistics.fmean(residuals) if residuals else None,
        residual_std_ms=(statistics.pstdev(residuals) if len(residuals) > 1 else 0.0)
        if residuals
        else None,
    )
