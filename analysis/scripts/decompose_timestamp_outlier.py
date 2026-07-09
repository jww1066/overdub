#!/usr/bin/env python3
"""Attribute Session A's ~40 ms getTimestamp outlier to a specific raw component (item 13 (a)).

test2-step2-plan.md item 13 (a) / prototype-plan.md Test 1a "Interim timestamp-variance plan"
step 1. Reads every capture sidecar in a directory (the four raw ``(framePosition, nanoTime)``
values), the matching WAV frame counts, and -- when present -- the click-gated results CSV
(``click_offset_ms`` as independent ground truth), decomposes each run's stream offset into its
frame-delta / clock-delta components plus per-stream consistency checks, and attributes any
outlier run to the raw value whose component subset deviates. See
``overdub_analysis/timestamp_decompose.py`` for the arithmetic and the flagging rules.

Why it matters: Test 3's median-of-5 knife-edge rests on the outlier being a single-read glitch;
if the culprit is a framePosition disagreeing with the captured WAV length, a sanity check against
elapsed capture length is a cheaper, stronger product remedy than taking k reads.

Usage (from analysis/ via the venv per CLAUDE.md):
    .venv/Scripts/python.exe scripts/decompose_timestamp_outlier.py \\
        --sweep-dir recapture_session_a
"""

from __future__ import annotations

import argparse
import csv
import json
import wave
from pathlib import Path

from overdub_analysis.timestamp_decompose import (
    COMPONENTS,
    TimestampRun,
    attribute_outliers,
    interpret,
)

REQUIRED_SIDECAR_FIELDS = (
    "sample_rate",
    "output_timestamp_frames",
    "output_timestamp_nanos",
    "input_timestamp_frames",
    "input_timestamp_nanos",
)


def _wav_frames(path: Path) -> int | None:
    if not path.exists():
        return None
    with wave.open(str(path), "rb") as w:
        return w.getnframes()


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


def _load_runs(
    sweep_dir: Path, condition: str | None, click_offsets: dict[str, float]
) -> list[TimestampRun]:
    runs: list[TimestampRun] = []
    for json_path in sorted(sweep_dir.glob("*.json")):
        meta = json.loads(json_path.read_text())
        if condition and meta.get("condition_id") != condition:
            continue
        if any(meta.get(k) is None for k in REQUIRED_SIDECAR_FIELDS):
            print(f"NOTE: {json_path.name} carries no stream timestamps -- skipped")
            continue
        wav_path = json_path.with_suffix(".wav")
        frames = _wav_frames(wav_path)
        if frames is None:
            print(f"NOTE: {wav_path.name} missing -- run kept, WAV checks skipped")
        runs.append(
            TimestampRun(
                label=json_path.stem.rsplit("_", 1)[-1],  # the capture's timestamp suffix
                sample_rate=int(meta["sample_rate"]),
                output_frames=float(meta["output_timestamp_frames"]),
                output_nanos=float(meta["output_timestamp_nanos"]),
                input_frames=float(meta["input_timestamp_frames"]),
                input_nanos=float(meta["input_timestamp_nanos"]),
                wall_ms=float(meta["timestamp"]) if meta.get("timestamp") is not None else None,
                wav_frames=frames,
                click_offset_ms=click_offsets.get(wav_path.name),
            )
        )
    return runs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep-dir", default="recapture_session_a",
                        help="directory of capture sidecars/WAVs (default: recapture_session_a)")
    parser.add_argument("--click-csv", default=None,
                        help="click-gated results CSV (default: <sweep-dir>/click_gated_results.csv"
                             " if present)")
    parser.add_argument("--condition", default="conversational_armslength_faceup_none",
                        help="restrict to one condition_id so the cluster is same-cell repeats; "
                             "pass '' to take every sidecar in the directory")
    parser.add_argument("--outlier-threshold-ms", type=float, default=5.0)
    parser.add_argument("--flag-threshold-ms", type=float, default=5.0)
    args = parser.parse_args()

    sweep_dir = Path(args.sweep_dir)
    if not sweep_dir.is_dir():
        print(f"sweep dir not found: {sweep_dir}")
        return 1

    click_csv = Path(args.click_csv) if args.click_csv else sweep_dir / "click_gated_results.csv"
    click_offsets = _load_click_offsets(click_csv) if click_csv.exists() else {}
    if not click_offsets:
        print(f"NOTE: no click CSV at {click_csv} -- falling back to the raw stream offset "
              "as the discriminant (noisier: it carries start jitter)")

    runs = _load_runs(sweep_dir, args.condition or None, click_offsets)
    if not runs:
        print(f"no sidecars with stream timestamps in {sweep_dir}"
              + (f" for condition '{args.condition}'" if args.condition else ""))
        return 1

    print(f"sweep dir: {sweep_dir}  condition: {args.condition or '(all)'}  runs: {len(runs)}")
    print()

    # Per-run component table.
    short = {
        "frame_delta_ms": "d_frames",
        "clock_delta_ms": "d_clock",
        "input_minus_wav_ms": "in-wav",
        "output_minus_wav_ms": "out-wav",
        "wav_ms": "wav_len",
        "output_anchor_ms": "out_anchor",
        "input_anchor_ms": "in_anchor",
    }
    header = f"{'run':<14} {'offset':>8} {'s-click':>8}" + "".join(
        f" {short[c]:>10}" for c in COMPONENTS
    )
    print(header)
    print("-" * len(header))
    for r in runs:
        s_click = f"{r.stream_minus_click_ms:.2f}" if r.stream_minus_click_ms is not None else "-"
        cells = "".join(
            f" {r.component(c):>10.2f}" if r.component(c) is not None else f" {'-':>10}"
            for c in COMPONENTS
        )
        print(f"{r.label:<14} {r.stream_offset_ms:>8.2f} {s_click:>8}{cells}")
    print("-" * len(header))
    print("(all values ms; anchors are monotonic-minus-wall, comparable across runs only)")
    print()

    try:
        result = attribute_outliers(
            runs,
            outlier_threshold_ms=args.outlier_threshold_ms,
            flag_threshold_ms=args.flag_threshold_ms,
        )
    except ValueError as e:
        print(f"attribution not possible: {e}")
        return 1

    print(f"discriminant: {result.discriminant}  "
          f"(outlier > {args.outlier_threshold_ms} ms from median)")
    print(f"healthy cluster: {len(result.cluster_labels)} runs")
    if not result.attributions:
        print("no outlier runs at this threshold.")
        return 0

    for a in result.attributions:
        print()
        print(f"OUTLIER {a.label}: discriminant deviation {a.discriminant_deviation_ms:+.2f} ms")
        print(f"  {'component':<22} {'value':>10} {'cluster med':>12} {'spread':>8} "
              f"{'deviation':>10}  flag")
        for d in a.deviations:
            mark = "FLAG" if d.flagged else ""
            print(f"  {d.component:<22} {d.value_ms:>10.2f} {d.cluster_median_ms:>12.2f} "
                  f"{d.cluster_spread_ms:>8.2f} {d.deviation_ms:>+10.2f}  {mark}")
        print()
        print(f"  attribution: {interpret(a)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
