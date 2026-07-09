"""Multi-read timestamp analysis: outlier rate, glitch-vs-session-state, median-of-k validity.

test2-step2-plan.md item 13 (b) / prototype-plan.md Test 1a "Interim timestamp-variance plan"
step 2. The harness now logs a periodic `getTimestamp` series per session
(`timestamp_samples` in the JSON sidecar); this module fits each stream's reads to a
frame-vs-time line, flags off-line points (single-read glitches), classifies each run, and --
the load-bearing output -- tests whether a median of the reads recovers the click ground truth
even on runs whose single latched read was the ~40 ms outlier.

Why a line fit, not cross-run referents: item 13 (a)
(`overdub_analysis.timestamp_decompose`) showed single-read sidecars *under-determine* a glitch
because the only cross-run referents (start-jitter, wall anchors) jitter by as much as the
anomaly. Repeated reads of one stream lie on a frame-vs-time line at the native sample rate, so a
single-read glitch is an off-line point visible *with no cross-run referent* -- the instrument
that sidesteps the under-determination.

Two linked verdicts:
  * **glitch-vs-session-state** (structural): a run with one isolated off-line point is a
    single-read glitch (median-of-k is a valid remedy); a run with many off-line points or a
    wrong slope is a session-level state (median-of-k does NOT help -- the whole session is bad).
    This is the assumption Test 3's median-of-5 knife-edge rests on, now directly measurable.
  * **median-of-k validity** (ground-truth): even cleaner than the structural read -- does the
    *median* stream offset agree with the independent calibration click on the run whose single
    read was the outlier? If yes, median-of-k is validated empirically, not just by Test 3's
    binomial arithmetic. Needs click offsets (optional); without them only the structural read
    runs.

All arithmetic is pure so it is unit-testable; the CLI that reads sidecars/WAVs/the click CSV is
``scripts/analyze_timestamp_multiread.py``. Values are milliseconds where dimensional.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

_NANOS_PER_SEC = 1_000_000_000.0
_MAD_SCALE = 1.4826


@dataclass(frozen=True)
class StreamRead:
    """One stream's ``(framePosition, nanoTime)`` from a single ``getTimestamp`` call."""

    frames: int
    nanos: int


@dataclass(frozen=True)
class TimestampSample:
    """One periodic read of both streams (one ``timestamp_samples`` entry)."""

    output: StreamRead
    input: StreamRead


@dataclass(frozen=True)
class LineFit:
    """Frame-vs-time fit for one stream's reads.

    A stream's ``framePosition`` advances at the sample rate *by physics* (each frame is 1/fs
    second), so ``slope_frames_per_sec`` is anchored at the sample rate -- not estimated -- and the
    only free parameter is ``intercept_frames`` (when frame 0 occurred), fit as the **median** of
    ``f_i - slope*t_i`` so a single glitch cannot tilt the line (an OLS fit would lean toward the
    outlier and smear its error onto clean reads, pushing them toward the flag threshold).
    ``residuals_ms`` is each read's deviation from that anchored line -- the quantity an
    off-line-point (glitch) inflates. ``ols_slope_frames_per_sec`` is the ordinary-least-squares
    slope kept as a *drift diagnostic*: if it departs from the sample rate, the stream's reported
    framePosition is not advancing at the claimed rate (a session-level state, not a single
    glitch). ``inlier_rms_ms`` is the RMS of all residuals (the stream's benign read noise; a
    single outlier inflates it, which is fine -- the per-read residuals, not this scalar, drive
    flagging).
    """

    slope_frames_per_sec: float
    intercept_frames: float
    residuals_ms: tuple[float, ...]
    ols_slope_frames_per_sec: float
    inlier_rms_ms: float


def fit_line(reads: list[StreamRead], sample_rate: int) -> LineFit:
    """Fit ``frames = sample_rate * (nanos/1e9) + intercept`` with a robust median intercept.

    The slope is anchored at ``sample_rate`` (see :class:`LineFit`); the intercept is the median of
    ``f_i - slope*t_i`` so one outlier cannot tilt the fit. The OLS slope is computed alongside as
    a drift diagnostic. Requires at least 2 reads.
    """
    if len(reads) < 2:
        raise ValueError("fit_line needs at least 2 reads")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")

    ts = [r.nanos / _NANOS_PER_SEC for r in reads]
    fs = [float(r.frames) for r in reads]
    slope = float(sample_rate)
    intercept = statistics.median([f - slope * t for t, f in zip(ts, fs)])
    residuals = [(f - (slope * t + intercept)) / sample_rate * 1000.0 for t, f in zip(ts, fs)]

    mean_t = statistics.fmean(ts)
    mean_f = statistics.fmean(fs)
    num = sum((t - mean_t) * (f - mean_f) for t, f in zip(ts, fs))
    den = sum((t - mean_t) ** 2 for t in ts)
    ols_slope = num / den if den != 0 else 0.0

    return LineFit(slope, intercept, tuple(residuals), ols_slope, _rms(residuals))


def flag_outliers(
    residuals_ms: list[float], abs_threshold_ms: float = 5.0, mad_factor: float = 3.0
) -> tuple[int, ...]:
    """Indices of residuals that are off-line points (single-read glitch candidates).

    Two-sided, like ``timestamp_decompose``: a residual is flagged when its absolute value exceeds
    *both* ``abs_threshold_ms`` and ``mad_factor`` x the scaled MAD of the residual set. The MAD
    guard stops a single huge outlier from inflating the spread so far that nothing flags (the
    masking problem), and the absolute floor stops sub-threshold jitter from flagging noise.
    """
    if len(residuals_ms) < 3:
        return ()
    med = statistics.median(residuals_ms)
    spread = _MAD_SCALE * statistics.median([abs(r - med) for r in residuals_ms])
    flagged = []
    for i, r in enumerate(residuals_ms):
        if abs(r) > abs_threshold_ms and abs(r) > mad_factor * spread:
            flagged.append(i)
    return tuple(flagged)


@dataclass(frozen=True)
class RunAnalysis:
    """One session's multi-read analysis."""

    label: str
    n_reads: int
    sample_rate: int
    output_fit: LineFit
    input_fit: LineFit
    output_outlier_indices: tuple[int, ...]
    input_outlier_indices: tuple[int, ...]
    stream_offsets_ms: tuple[float, ...]
    median_stream_offset_ms: float
    classification: str
    note: str


def compute_stream_offset_ms(sample: TimestampSample, sample_rate: int) -> float:
    """Per-sample stream offset, matching ``computeStreamOffset`` (StreamOffset.kt) in ms."""
    frame_delta = (sample.input.frames - sample.output.frames) / sample_rate * 1000.0
    clock_delta = (sample.output.nanos - sample.input.nanos) / 1e6
    return frame_delta + clock_delta


def classify_run(
    n_reads: int,
    output_outliers: tuple[int, ...],
    input_outliers: tuple[int, ...],
    output_fit: LineFit,
    input_fit: LineFit,
    sample_rate: int,
    slope_tolerance: float = 0.01,
) -> tuple[str, str]:
    """Structural glitch-vs-session-state classification + a human-readable note.

    Returns ``(classification, note)`` where classification is one of:
      * ``"too_few_reads"`` -- n < 4: a single glitch among 3 reads is not isolable.
      * ``"clean"`` -- no off-line points on either stream and both slopes track the sample rate.
      * ``"single_read_glitch"`` -- one stream has exactly one isolated outlier (the other clean):
        median-of-k is a valid remedy for this run.
      * ``"session_level_state"`` -- multiple outliers, outliers on both streams at *different*
        indices, or a slope off by > ``slope_tolerance`` (fractional): the whole session
        mis-reported, so a median does not help.
    """
    if n_reads < 4:
        return "too_few_reads", f"only {n_reads} reads -- cannot isolate a single glitch"

    out_bad = len(output_outliers)
    in_bad = len(input_outliers)
    total_bad = out_bad + in_bad

    out_slope_off = abs(output_fit.ols_slope_frames_per_sec - sample_rate) > slope_tolerance * sample_rate
    in_slope_off = abs(input_fit.ols_slope_frames_per_sec - sample_rate) > slope_tolerance * sample_rate

    if total_bad == 0 and not out_slope_off and not in_slope_off:
        return "clean", "all reads on both streams on the line"

    if out_slope_off or in_slope_off:
        return (
            "session_level_state",
            f"slope off (ols {output_fit.ols_slope_frames_per_sec:.0f}/"
            f"{input_fit.ols_slope_frames_per_sec:.0f} vs {sample_rate}/s) -- drift, not a glitch",
        )

    # Same-index outliers on both streams is a single bad getTimestamp call (both reads of it
    # glitched together) -- still a single-read glitch, just bilateral.
    same_index = set(output_outliers) & set(input_outliers)
    if same_index and out_bad <= 1 and in_bad <= 1:
        return "single_read_glitch", f"bilateral glitch at read index {sorted(same_index)}"

    if (out_bad == 1 and in_bad == 0) or (in_bad == 1 and out_bad == 0):
        idx = output_outliers[0] if out_bad == 1 else input_outliers[0]
        which = "output" if out_bad == 1 else "input"
        return "single_read_glitch", f"isolated {which} outlier at read index {idx}"

    return (
        "session_level_state",
        f"{total_bad} outliers (out={out_bad} in={in_bad}) -- not isolated, median does not help",
    )


def analyze_run(
    label: str,
    samples: list[TimestampSample],
    sample_rate: int,
    abs_threshold_ms: float = 5.0,
) -> RunAnalysis:
    """Fit both streams, flag outliers, classify, and compute the per-sample + median stream offset."""
    if len(samples) < 2:
        raise ValueError("analyze_run needs at least 2 samples to fit")
    out_reads = [s.output for s in samples]
    in_reads = [s.input for s in samples]
    out_fit = fit_line(out_reads, sample_rate)
    in_fit = fit_line(in_reads, sample_rate)
    out_outliers = flag_outliers(list(out_fit.residuals_ms), abs_threshold_ms=abs_threshold_ms)
    in_outliers = flag_outliers(list(in_fit.residuals_ms), abs_threshold_ms=abs_threshold_ms)
    offsets = tuple(compute_stream_offset_ms(s, sample_rate) for s in samples)
    median_offset = statistics.median(offsets)
    classification, note = classify_run(
        len(samples), out_outliers, in_outliers, out_fit, in_fit, sample_rate
    )
    return RunAnalysis(
        label=label,
        n_reads=len(samples),
        sample_rate=sample_rate,
        output_fit=out_fit,
        input_fit=in_fit,
        output_outlier_indices=out_outliers,
        input_outlier_indices=in_outliers,
        stream_offsets_ms=offsets,
        median_stream_offset_ms=median_offset,
        classification=classification,
        note=note,
    )


@dataclass(frozen=True)
class ResidualPoint:
    """One run's stream offset (single-read and median) vs the click ground truth."""

    label: str
    single_read_offset_ms: float | None
    median_offset_ms: float
    click_offset_ms: float
    single_minus_click_ms: float | None
    median_minus_click_ms: float


@dataclass(frozen=True)
class PopulationSummary:
    """Aggregate over all runs."""

    n_runs: int
    n_runs_with_samples: int
    total_reads: int
    total_outliers: int
    runs_with_outlier: int
    classification_counts: dict[str, int]
    # stream - click residual population, single-read vs median:
    single_residual_mean_ms: float | None
    single_residual_std_ms: float | None
    single_residual_max_abs_ms: float | None
    median_residual_mean_ms: float | None
    median_residual_std_ms: float | None
    median_residual_max_abs_ms: float | None
    # The measurement-basis constant (median of single-click across runs): a healthy run's
    # single_minus_click sits here (~-15 ms on the Pixel 10), so a single-read OUTLIER is a run
    # whose single_minus_click deviates from THIS, not from zero.
    basis_residual_ms: float | None
    median_resolves_outlier_runs: int
    median_resolves_outlier_total: int


def summarize_population(
    runs: list[RunAnalysis],
    residuals: list[ResidualPoint],
    single_outlier_threshold_ms: float = 15.0,
) -> PopulationSummary:
    """Aggregate the per-run analyses + stream-click residuals into the population verdict.

    ``single_outlier_threshold_ms`` defines a "single-read outlier run" *relative to the
    measurement-basis constant*: the basis residual (median of ``single_minus_click`` across runs,
    ~-15 ms on the Pixel 10) is the healthy single-read value, so a run is a single-read outlier
    when its ``single_minus_click`` deviates from that basis by more than the threshold. (Centering
    on the basis, not on zero, is what stops every healthy ~-15 ms run from counting as an
    outlier.) ``median_resolves_outlier_runs`` is how many of those have a ``median_minus_click``
    *within the threshold of the basis* -- direct evidence the median fixes the single read's
    error. That count over ``median_resolves_outlier_total`` is the empirical median-of-k validity
    rate Test 3's binomial assumed.
    """
    class_counts: dict[str, int] = {}
    total_reads = 0
    total_outliers = 0
    runs_with_outlier = 0
    for r in runs:
        class_counts[r.classification] = class_counts.get(r.classification, 0) + 1
        total_reads += r.n_reads
        n_bad = len(r.output_outlier_indices) + len(r.input_outlier_indices)
        total_outliers += n_bad
        if n_bad > 0:
            runs_with_outlier += 1

    single_res = [r.single_minus_click_ms for r in residuals if r.single_minus_click_ms is not None]
    median_res = [r.median_minus_click_ms for r in residuals]

    single_mean = statistics.fmean(single_res) if single_res else None
    single_std = (statistics.pstdev(single_res) if len(single_res) > 1 else 0.0) if single_res else None
    single_max = max(abs(x) for x in single_res) if single_res else None
    median_mean = statistics.fmean(median_res) if median_res else None
    median_std = (statistics.pstdev(median_res) if len(median_res) > 1 else 0.0) if median_res else None
    median_max = max(abs(x) for x in median_res) if median_res else None

    basis = statistics.median(single_res) if single_res else None
    outlier_runs = [r for r in residuals if r.single_minus_click_ms is not None
                    and basis is not None
                    and abs(r.single_minus_click_ms - basis) > single_outlier_threshold_ms]
    resolved = sum(1 for r in outlier_runs if abs(r.median_minus_click_ms - basis) <= single_outlier_threshold_ms)

    return PopulationSummary(
        n_runs=len(runs),
        n_runs_with_samples=len(runs),
        total_reads=total_reads,
        total_outliers=total_outliers,
        runs_with_outlier=runs_with_outlier,
        classification_counts=class_counts,
        single_residual_mean_ms=single_mean,
        single_residual_std_ms=single_std,
        single_residual_max_abs_ms=single_max,
        median_residual_mean_ms=median_mean,
        median_residual_std_ms=median_std,
        median_residual_max_abs_ms=median_max,
        basis_residual_ms=basis,
        median_resolves_outlier_runs=resolved,
        median_resolves_outlier_total=len(outlier_runs),
    )


def _rms(values: list[float]) -> float:
    if not values:
        return 0.0
    return (sum(v * v for v in values) / len(values)) ** 0.5
