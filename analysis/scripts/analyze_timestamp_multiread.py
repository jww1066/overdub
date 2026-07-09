#!/usr/bin/env python3
"""Analyze the multi-read timestamp series across a batch (test2-step2-plan.md item 13 (b)).

Reads every capture sidecar's ``timestamp_samples`` (the periodic getTimestamp series the harness
drains across the session), fits each stream's reads to an anchored frame-vs-time line, flags
off-line points (single-read glitches), classifies each run (clean / single-read-glitch /
session-level-state), and -- when a click-gated results CSV is supplied -- tests whether the
*median* stream offset recovers the click ground truth on runs whose single latched read was the
outlier. That last test is the empirical median-of-k validity check Test 3's binomial knife-edge
assumed; without it, only the structural (glitch-vs-session-state) read runs.

See ``overdub_analysis/timestamp_multiread.py`` for the arithmetic and the flagging rules, and
``doc/test2-sweep-results.md`` "Session A timestamp-outlier decomposition" for why multi-read
logging is the instrument single-read sidecars under-determine.

Usage (from analysis/ via the venv per CLAUDE.md), after run_click_gated_sweep.py has produced the
click CSV for the batch:
    .venv/Scripts/python.exe scripts/analyze_timestamp_multiread.py \\
        --sweep-dir recapture_session_a \\
        --click-csv recapture_session_a/click_gated_results.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

from overdub_analysis.timestamp_multiread import (
    StreamRead,
    TimestampSample,
    ResidualPoint,
    analyze_run,
    summarize_population,
)

REQUIRED = ("sample_rate", "timestamp_samples")


def _load_click_offsets(click_csv: Path) -> dict[str, float]:
    """wav filename -> click_offset_ms, from run_click_gated_sweep.py's output CSV."""
    offsets: dict[str, float] = {}
    with open(click_csv, newline="") as f:
        for row in csv.DictReader(f):
            wav_file = row.get("wav_file", "")
            raw = row.get("click_offset_ms", "")
            if wav_file and raw:
                offsets[Path(wav_file).name] = float(raw)
    return offsets


def _load_runs(sweep_dir: Path, click_offsets: dict[str, float]) -> list[tuple[str, dict, float | None]]:
    """(sidecar-dict, click_offset) per capture that carries a timestamp_samples series."""
    out = []
    for json_path in sorted(sweep_dir.glob("*.json")):
        meta = json.loads(json_path.read_text())
        ts = meta.get("timestamp_samples")
        if not ts:
            continue
        wav_name = json_path.with_suffix(".wav").name
        out.append((json_path.stem, meta, click_offsets.get(wav_name)))
    return out


def _samples_from_meta(meta: dict) -> list[TimestampSample]:
    return [
        TimestampSample(
            output=StreamRead(int(s["outputFrames"]), int(s["outputNanos"])),
            input=StreamRead(int(s["inputFrames"]), int(s["inputNanos"])),
        )
        for s in meta["timestamp_samples"]
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep-dir", default="recapture_session_a",
                        help="directory of capture sidecars with timestamp_samples")
    parser.add_argument("--click-csv", default=None,
                        help="click-gated results CSV (default: <sweep-dir>/click_gated_results.csv)")
    parser.add_argument("--outlier-threshold-ms", type=float, default=5.0,
                        help="abs residual floor for flagging an off-line read (ms)")
    parser.add_argument("--single-outlier-threshold-ms", type=float, default=15.0,
                        help="|single-read offset - click| above this marks a 'single-read outlier "
                             "run' for the median-resolves-outlier count (ms)")
    parser.add_argument("--condition", default="",
                        help="optional: restrict to one condition_id (default: all sidecars)")
    args = parser.parse_args()

    sweep_dir = Path(args.sweep_dir)
    if not sweep_dir.is_dir():
        print(f"sweep dir not found: {sweep_dir}")
        return 1
    click_csv = Path(args.click_csv) if args.click_csv else sweep_dir / "click_gated_results.csv"
    click_offsets = _load_click_offsets(click_csv) if click_csv.exists() else {}
    if not click_offsets:
        print(f"NOTE: no click CSV at {click_csv} -- running the structural (glitch-vs-session) "
              "read only; the median-of-k validity test needs click ground truth")

    raw = _load_runs(sweep_dir, click_offsets)
    if args.condition:
        raw = [(l, m, c) for (l, m, c) in raw if m.get("condition_id") == args.condition]
    if not raw:
        print(f"no sidecars with timestamp_samples in {sweep_dir}"
              + (f" for condition '{args.condition}'" if args.condition else ""))
        return 1

    runs = []
    residuals: list[ResidualPoint] = []
    res_by_label: dict[str, ResidualPoint] = {}
    print(f"sweep dir: {sweep_dir}  runs: {len(raw)}  click-anchored: {bool(click_offsets)}")
    print()
    print(f"{'run':<16} {'n':>3} {'out_flg':>7} {'in_flg':>6} {'med_off':>9} "
          f"{'sng_off':>9} {'s-click':>8} {'m-click':>8}  classification")
    print("-" * 100)
    for label, meta, click in raw:
        samples = _samples_from_meta(meta)
        rate = int(meta["sample_rate"])
        run = analyze_run(label, samples, rate, abs_threshold_ms=args.outlier_threshold_ms)
        runs.append(run)
        single_off = meta.get("stream_offset_ms")
        rp: ResidualPoint | None = None
        if click is not None and single_off is not None:
            rp = ResidualPoint(
                label=label,
                single_read_offset_ms=float(single_off),
                median_offset_ms=run.median_stream_offset_ms,
                click_offset_ms=click,
                single_minus_click_ms=float(single_off) - click,
                median_minus_click_ms=run.median_stream_offset_ms - click,
            )
            residuals.append(rp)
            res_by_label[label] = rp
        single_str = f"{single_off:+.2f}" if single_off is not None else "-"
        s_click = f"{rp.single_minus_click_ms:+.2f}" if rp and rp.single_minus_click_ms is not None else "-"
        m_click = f"{rp.median_minus_click_ms:+.2f}" if rp else "-"
        print(
            f"{label:<16} {run.n_reads:>3} {len(run.output_outlier_indices):>7} "
            f"{len(run.input_outlier_indices):>6} {run.median_stream_offset_ms:>+9.2f} "
            f"{single_str:>9} {s_click:>8} {m_click:>8}  {run.classification}"
        )
    print("-" * 100)
    print("(out_flg/in_flg = off-line reads flagged on each stream; med_off = median stream offset; "
          "s/m-click = single/median minus click)")
    print()

    summary = summarize_population(runs, residuals, args.single_outlier_threshold_ms)
    print("=== population ===")
    print(f"runs: {summary.n_runs}  total reads: {summary.total_reads}  "
          f"total off-line reads: {summary.total_outliers}  runs with >=1 outlier: "
          f"{summary.runs_with_outlier}")
    print(f"classification: {summary.classification_counts}")
    if summary.total_reads > 0:
        read_rate = 100.0 * summary.total_outliers / summary.total_reads
        run_rate = 100.0 * summary.runs_with_outlier / summary.n_runs
        print(f"off-line read rate: {read_rate:.2f}%  ({summary.total_outliers}/{summary.total_reads})")
        print(f"runs-with-outlier rate: {run_rate:.1f}%  ({summary.runs_with_outlier}/{summary.n_runs})")
    # Cross-run spread of the median stream offset: on independently-started sessions this is the
    # per-session start-jitter distribution for the batch's route (item 10 measured 13.4 ms std on
    # the speaker route). NOT within-session noise, and NOT an honesty statement -- a uniform
    # session-level shift hides inside this spread and only an independent anchor (click/rig) can
    # see it.
    med_offsets = [r.median_stream_offset_ms for r in runs]
    if len(med_offsets) >= 2:
        mean_off = statistics.mean(med_offsets)
        std_off = statistics.stdev(med_offsets)
        print(f"median-offset spread across runs (start jitter): mean={mean_off:+.2f} ms  "
              f"std={std_off:.2f} ms  range=[{min(med_offsets):+.2f}, {max(med_offsets):+.2f}]")
    print()

    if residuals:
        print("=== stream - click residual (ms) ===")
        if summary.single_residual_mean_ms is not None:
            print(f"single-read: mean={summary.single_residual_mean_ms:+.2f} "
                  f"std={summary.single_residual_std_ms:.2f} "
                  f"max|.|={summary.single_residual_max_abs_ms:.2f}  (n={len(residuals)})")
        print(f"median-read: mean={summary.median_residual_mean_ms:+.2f} "
              f"std={summary.median_residual_std_ms:.2f} "
              f"max|.|={summary.median_residual_max_abs_ms:.2f}  (n={len(residuals)})")
        if summary.basis_residual_ms is not None:
            print(f"basis residual (median single-click, the healthy single-read value): "
                  f"{summary.basis_residual_ms:+.2f} ms")
        print()
        print("=== median-of-k validity (the Test 3 knife-edge, measured) ===")
        print(f"single-read-outlier runs (|single-click - basis| > "
              f"{args.single_outlier_threshold_ms} ms): {summary.median_resolves_outlier_total}")
        print(f"  of those, median inside the threshold of the basis (median resolves it): "
              f"{summary.median_resolves_outlier_runs}")
        if summary.median_resolves_outlier_total > 0:
            rate = 100.0 * summary.median_resolves_outlier_runs / summary.median_resolves_outlier_total
            print(f"  -> median-of-k resolves {rate:.0f}% of single-read-outlier runs")
    else:
        print("(no click ground truth -- median-of-k validity test skipped)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
