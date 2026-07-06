"""Unit tests for the offset-decomposition arithmetic (test2-step2-plan.md item 10).

No device data is needed: the tests construct records whose spread is *entirely* known start-jitter
plus a constant acoustic term, and assert the residual collapses to that constant -- the exact claim
the on-device re-run will later check against real timestamps.
"""

from __future__ import annotations

import math

import pytest

from overdub_analysis.offset_decompose import OffsetRecord, summarize


def test_residual_is_gcc_minus_stream():
    r = OffsetRecord("baseline", gcc_phat_offset_ms=97.0, stream_offset_ms=90.0)
    assert r.residual_ms == pytest.approx(7.0)


def test_residual_is_none_without_a_stream_offset():
    r = OffsetRecord("legacy", gcc_phat_offset_ms=110.0, stream_offset_ms=None)
    assert r.residual_ms is None


def test_start_jitter_collapses_the_spread():
    # Construct the item-10 hypothesis exactly: a constant 5 ms acoustic flight plus per-cell
    # start-jitter that dominates the raw spread. Subtracting the (known) jitter must leave only the
    # 5 ms constant, so residual std -> 0 while the raw GCC-PHAT std is large.
    jitter = [-30.0, -10.0, 0.0, 15.0, 40.0]
    acoustic = 5.0
    records = [
        OffsetRecord(f"cell{i}", gcc_phat_offset_ms=acoustic + j, stream_offset_ms=j)
        for i, j in enumerate(jitter)
    ]
    s = summarize(records)

    assert s.n_total == 5
    assert s.n_with_timestamps == 5
    assert s.gcc_phat_std_ms > 20.0  # the alarming raw spread
    assert s.residual_mean_ms == pytest.approx(acoustic)
    assert s.residual_std_ms == pytest.approx(0.0, abs=1e-9)


def test_real_misalignment_does_not_collapse():
    # If the stream offset does NOT explain the spread (residual stays wide), the summary must show
    # a residual std comparable to the raw std, not a collapse -- the "suspect real misalignment" arm.
    records = [
        OffsetRecord("a", gcc_phat_offset_ms=60.0, stream_offset_ms=1.0),
        OffsetRecord("b", gcc_phat_offset_ms=100.0, stream_offset_ms=2.0),
        OffsetRecord("c", gcc_phat_offset_ms=150.0, stream_offset_ms=1.5),
    ]
    s = summarize(records)
    assert s.residual_std_ms is not None
    assert s.residual_std_ms > 0.5 * s.gcc_phat_std_ms


def test_summary_with_mixed_and_missing_timestamps():
    records = [
        OffsetRecord("has", gcc_phat_offset_ms=97.0, stream_offset_ms=92.0),
        OffsetRecord("missing", gcc_phat_offset_ms=110.0, stream_offset_ms=None),
    ]
    s = summarize(records)
    assert s.n_total == 2
    assert s.n_with_timestamps == 1
    # residual std over a single record is defined as 0.0, not NaN/raise.
    assert s.residual_std_ms == 0.0
    assert s.residual_mean_ms == pytest.approx(5.0)
    assert math.isfinite(s.gcc_phat_std_ms)


def test_all_missing_timestamps_gives_none_residual():
    records = [
        OffsetRecord("a", gcc_phat_offset_ms=90.0, stream_offset_ms=None),
        OffsetRecord("b", gcc_phat_offset_ms=120.0, stream_offset_ms=None),
    ]
    s = summarize(records)
    assert s.n_with_timestamps == 0
    assert s.residual_mean_ms is None
    assert s.residual_std_ms is None


def test_summarize_rejects_empty():
    with pytest.raises(ValueError):
        summarize([])
