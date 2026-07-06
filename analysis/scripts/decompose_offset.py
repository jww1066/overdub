#!/usr/bin/env python3
"""Subtract each cell's hardware stream offset from its GCC-PHAT offset (test2-step2-plan.md item 10).

Joins the band-limited GCC-PHAT sweep results (``gcc_phat_bandlimited_results.csv``, produced by
``run_bandlimited_gcc_phat_sweep.py``) with the per-capture JSON sidecars' ``stream_offset_ms`` field
(logged by the harness from each stream's ``getTimestamp()``), and reports the residual
``gcc_phat_offset - stream_offset`` per cell plus the population spread.

The point (see the module docstring in ``overdub_analysis/offset_decompose.py`` and
``doc/guides/offline-dsp.md``): the 61-151 ms cross-cell offset spread is suspected to be per-session
harness start-jitter, not real alignment error, because every sweep cell is an independently-started
output+input stream pair. If that is right, the residual std collapses far below the raw GCC-PHAT std.

Until a device re-run captures cells that carry ``stream_offset_ms`` (this is device-gated -- the
Pixel 10 has to be reconnected and a few cells re-captured), this script will report "0 cells carry a
stream offset" and only echo the raw GCC-PHAT spread; that is the expected state, not an error.

Usage (from analysis/ via the venv per CLAUDE.md):
    .venv/Scripts/python.exe scripts/decompose_offset.py \\
        --sweep-dir sweep_data \\
        --results-csv sweep_data/gcc_phat_bandlimited_results.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from overdub_analysis.offset_decompose import OffsetRecord, summarize


def _load_records(results_csv: Path, sweep_dir: Path, offset_column: str) -> list[OffsetRecord]:
    records: list[OffsetRecord] = []
    with open(results_csv, newline="") as f:
        for row in csv.DictReader(f):
            if offset_column not in row:
                raise SystemExit(
                    f"column '{offset_column}' not in {results_csv} "
                    f"(have: {', '.join(row.keys())})"
                )
            condition_id = row.get("condition_id", "")
            gcc_ms = float(row[offset_column])

            stream_ms: float | None = None
            wav_file = row.get("wav_file", "")
            if wav_file:
                json_path = sweep_dir / (Path(wav_file).stem + ".json")
                if json_path.exists():
                    meta = json.loads(json_path.read_text())
                    raw = meta.get("stream_offset_ms")
                    stream_ms = float(raw) if raw is not None else None

            records.append(
                OffsetRecord(
                    condition_id=condition_id,
                    gcc_phat_offset_ms=gcc_ms,
                    stream_offset_ms=stream_ms,
                )
            )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep-dir", default="sweep_data")
    parser.add_argument("--results-csv", default=None,
                        help="default <sweep-dir>/gcc_phat_bandlimited_results.csv")
    parser.add_argument("--offset-column", default="bp_offset_ms",
                        help="GCC-PHAT offset column in the results CSV (default: bp_offset_ms)")
    parser.add_argument("--output-csv", default=None,
                        help="optional path to write the per-cell residual table")
    args = parser.parse_args()

    sweep_dir = Path(args.sweep_dir)
    results_csv = Path(args.results_csv) if args.results_csv else (
        sweep_dir / "gcc_phat_bandlimited_results.csv"
    )
    if not results_csv.exists():
        print(f"results CSV not found: {results_csv}")
        return 1

    records = _load_records(results_csv, sweep_dir, args.offset_column)
    if not records:
        print(f"no rows in {results_csv}")
        return 1

    summary = summarize(records)

    print(f"results: {results_csv}  offset column: {args.offset_column}")
    print(f"sweep dir: {sweep_dir}  ({summary.n_total} cells, "
          f"{summary.n_with_timestamps} carry a stream offset)")
    print()
    print(f"{'condition_id':<42} {'gcc_ms':>9} {'stream_ms':>10} {'residual_ms':>12}")
    print("-" * 76)
    for r in records:
        stream = f"{r.stream_offset_ms:.2f}" if r.stream_offset_ms is not None else "-"
        residual = f"{r.residual_ms:.2f}" if r.residual_ms is not None else "-"
        print(f"{r.condition_id:<42} {r.gcc_phat_offset_ms:>9.2f} {stream:>10} {residual:>12}")
    print("-" * 76)

    print(
        f"gcc-phat offset (ms): mean={summary.gcc_phat_mean_ms:.1f} "
        f"std={summary.gcc_phat_std_ms:.1f}  (n={summary.n_total})"
    )
    if summary.residual_std_ms is not None:
        print(
            f"residual      (ms): mean={summary.residual_mean_ms:.1f} "
            f"std={summary.residual_std_ms:.1f}  (n={summary.n_with_timestamps})"
        )
        if summary.gcc_phat_std_ms > 0:
            drop = 100.0 * (1.0 - summary.residual_std_ms / summary.gcc_phat_std_ms)
            print(
                f"residual std is {drop:.0f}% below the raw offset std -- "
                + (
                    "the cross-cell spread was harness start-jitter (removable)."
                    if drop >= 50.0
                    else "the spread is NOT explained by start-jitter; suspect real misalignment."
                )
            )
    else:
        print("residual      (ms): no cell carries a stream offset yet -- re-capture on-device "
              "(item 10 is device-gated) to populate stream_offset_ms.")

    if args.output_csv:
        out = Path(args.output_csv)
        with open(out, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["condition_id", "gcc_phat_offset_ms", "stream_offset_ms", "residual_ms"])
            for r in records:
                writer.writerow([
                    r.condition_id,
                    f"{r.gcc_phat_offset_ms:.3f}",
                    "" if r.stream_offset_ms is None else f"{r.stream_offset_ms:.3f}",
                    "" if r.residual_ms is None else f"{r.residual_ms:.3f}",
                ])
        print(f"\nCSV: {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
