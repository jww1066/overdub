"""Tests for overdub_analysis.timestamp_multiread (test2-step2-plan.md item 13 (b))."""

from __future__ import annotations

import dataclasses

import pytest

from overdub_analysis.timestamp_multiread import (
    StreamRead,
    TimestampSample,
    analyze_run,
    classify_run,
    compute_stream_offset_ms,
    fit_line,
    flag_outliers,
    summarize_population,
    PopulationSummary,
    RunAnalysis,
    ResidualPoint,
)

FS = 48000
N0 = 7_000_000_000_000  # arbitrary monotonic base, ns


def _on_line(i: int, t_sec: float) -> StreamRead:
    """A read exactly on the 48k line at time t_sec (frame = FS * t_sec)."""
    return StreamRead(frames=int(FS * t_sec), nanos=int(N0 + t_sec * 1e9))


def _clean_samples(n: int, start_sec: float = 1.0, step_sec: float = 1.5) -> list[TimestampSample]:
    """n reads on both streams' lines; input lags output by a fixed 0.5 ms (clock) + frame gap."""
    out = []
    for i in range(n):
        t = start_sec + i * step_sec
        # output on the line; input 2400 frames behind + 0.0005s clock skew -> stable offset
        s = TimestampSample(
            output=_on_line(i, t),
            input=StreamRead(frames=int(FS * t) - 2400, nanos=int(N0 + t * 1e9) + 500_000),
        )
        out.append(s)
    return out


def test_fit_line_recovers_sample_rate_on_clean_reads():
    reads = [_on_line(i, 1.0 + i * 1.5) for i in range(8)]
    fit = fit_line(reads, FS)
    # Anchored slope is exactly the sample rate; the OLS diagnostic agrees on clean reads.
    assert fit.slope_frames_per_sec == pytest.approx(FS, rel=1e-9)
    assert fit.ols_slope_frames_per_sec == pytest.approx(FS, rel=1e-9)
    assert all(abs(r) < 1e-6 for r in fit.residuals_ms)
    assert fit.inlier_rms_ms < 1e-6


def test_fit_line_needs_two_reads():
    with pytest.raises(ValueError):
        fit_line([_on_line(0, 1.0)], FS)


def test_flag_outliers_isolates_a_single_glitch():
    # 8 clean residuals ~0, one +40 ms spike at index 4.
    res = [0.1, -0.1, 0.2, -0.2, 40.0, 0.1, -0.1, 0.2]
    assert flag_outliers(res) == (4,)


def test_flag_outliers_masked_spike_still_flags_via_mad_floor():
    # If the absolute threshold is set below the spike it flags; the MAD guard prevents a lone
    # spike from inflating spread enough to mask itself (median/MAD are robust to one outlier).
    res = [0.0, 0.0, 0.0, 0.0, 40.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert flag_outliers(res, abs_threshold_ms=5.0) == (4,)


def test_flag_outliers_below_threshold_does_not_flag():
    res = [0.1, -0.2, 0.0, 3.0, -0.1, 0.2]  # max 3 ms < 5 ms floor
    assert flag_outliers(res) == ()


def test_compute_stream_offset_matches_kotlin_convention():
    # (input - output) frames + (output - input) nanos * fs/1e9, in ms.
    s = TimestampSample(
        output=StreamRead(100_000, 2_000_000_000 + N0),
        input=StreamRead(95_200, 2_000_000_000 + N0),
    )
    # frame_delta = -4800 frames = -100 ms; clock_delta = 0. Sum = -100 ms.
    assert compute_stream_offset_ms(s, FS) == pytest.approx(-100.0, abs=1e-9)


def test_clean_run_classifies_clean():
    run = analyze_run("r0", _clean_samples(10), FS)
    assert run.classification == "clean"
    assert run.output_outlier_indices == ()
    assert run.input_outlier_indices == ()
    assert run.n_reads == 10


def test_single_read_glitch_classifies_and_median_ignores_it():
    samples = _clean_samples(10)
    # Corrupt one input read's framePosition by +40 ms (the Session A outlier shape).
    bad = samples[4]
    samples[4] = TimestampSample(
        output=bad.output,
        input=StreamRead(frames=bad.input.frames + int(FS * 40 / 1000), nanos=bad.input.nanos),
    )
    run = analyze_run("r1", samples, FS)
    assert run.classification == "single_read_glitch"
    assert run.input_outlier_indices == (4,)
    # The median stream offset is taken over all 10 reads, so one +40 ms outlier among 10 does
    # not move the median off the clean value (the whole point of median-of-k).
    clean_offsets = [compute_stream_offset_ms(s, FS) for s in _clean_samples(10)]
    assert run.median_stream_offset_ms == pytest.approx(statistics_median(clean_offsets), abs=0.01)


def test_session_level_state_for_many_outliers():
    samples = _clean_samples(10)
    # Corrupt three reads -> not isolated -> session-level state.
    for i in (3, 5, 7):
        b = samples[i]
        samples[i] = TimestampSample(
            output=StreamRead(b.output.frames + int(FS * 30 / 1000), b.output.nanos),
            input=b.input,
        )
    run = analyze_run("r2", samples, FS)
    assert run.classification == "session_level_state"


def test_slope_drift_is_session_level_state():
    # Reads on a 47000 fps line (not 48000) -- a systematic drift, not a glitch.
    n = 10
    samples = [
        TimestampSample(
            output=StreamRead(int(47000 * (1.0 + i * 1.5)), int(N0 + (1.0 + i * 1.5) * 1e9)),
            input=StreamRead(int(47000 * (1.0 + i * 1.5)) - 2400, int(N0 + (1.0 + i * 1.5) * 1e9) + 500_000),
        )
        for i in range(n)
    ]
    run = analyze_run("r3", samples, FS)
    assert run.classification == "session_level_state"
    assert "drift" in run.note


def test_too_few_reads_classifies_as_such():
    run = analyze_run("r4", _clean_samples(3), FS)
    assert run.classification == "too_few_reads"


def test_bilateral_glitch_is_single_read():
    samples = _clean_samples(10)
    b = samples[5]
    samples[5] = TimestampSample(
        output=StreamRead(b.output.frames + int(FS * 35 / 1000), b.output.nanos),
        input=StreamRead(b.input.frames + int(FS * 35 / 1000), b.input.nanos),
    )
    run = analyze_run("r5", samples, FS)
    assert run.classification == "single_read_glitch"
    assert run.note.startswith("bilateral")


def test_summarize_population_counts_and_median_resolution():
    clean = analyze_run("c", _clean_samples(10), FS)
    glitched_samples = _clean_samples(10)
    b = glitched_samples[4]
    glitched_samples[4] = TimestampSample(
        output=b.output,
        input=StreamRead(frames=b.input.frames + int(FS * 40 / 1000), nanos=b.input.nanos),
    )
    glitched = analyze_run("g", glitched_samples, FS)

    # Residuals: 5 clean runs at basis 0 + 1 glitched run whose SINGLE read is the +40 ms
    # outlier. The basis (median single_minus_click over 6 runs) is 0 (robust to the one
    # outlier); the glitched run deviates from it by 40 > 15 -> single-read-outlier run; its
    # MEDIAN agrees with the click (median_minus_click 0, within 15 of basis) -> resolved.
    clean_rp = ResidualPoint(
        label="c",
        single_read_offset_ms=-100.0,
        median_offset_ms=-100.0,
        click_offset_ms=-100.0,
        single_minus_click_ms=0.0,
        median_minus_click_ms=0.0,
    )
    residuals = [dataclasses.replace(clean_rp, label=f"c{i}") for i in range(5)] + [
        ResidualPoint(
            label="g",
            single_read_offset_ms=-60.0,  # the +40 ms outlier read
            median_offset_ms=-100.0,       # median ignores the outlier
            click_offset_ms=-100.0,
            single_minus_click_ms=40.0,
            median_minus_click_ms=0.0,
        ),
    ]
    runs = [clean] * 5 + [glitched]
    summary = summarize_population(runs, residuals, single_outlier_threshold_ms=15.0)
    assert summary.n_runs == 6
    assert summary.classification_counts == {"clean": 5, "single_read_glitch": 1}
    assert summary.runs_with_outlier == 1
    assert summary.basis_residual_ms == 0.0
    assert summary.median_resolves_outlier_total == 1
    assert summary.median_resolves_outlier_runs == 1


def statistics_median(values):
    import statistics
    return statistics.median(values)
