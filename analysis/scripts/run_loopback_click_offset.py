#!/usr/bin/env python3
"""Click-anchored offset extraction for the electrical-loopback rig (Test 1 / Test 1a).

Unlike the acoustic sweep, the electrical-loopback captures (PassMark TRRS plug + Movo
UCMA-2, `harness/scripts/run_loopback_batch.sh`) carry no periodic-reference alias risk
worth constraining a GCC-PHAT lag window for: the reference asset's own calibration
click (`overdub_analysis.calibration_click`, a 20 ms 500-4000 Hz chirp at a known fixed
position) is an independent, non-repeating matched-filter target already validated as
the ground-truth instrument for exactly this kind of question (see
`reference_track_README.md` and the Test 2 "Ground-truth correction"). So this script
does not use `gcc_phat` at all -- it locates the click directly, which sidesteps the
whole beat-period-alias family of traps documented in CLAUDE.md/`doc/guides/offline-dsp.md`
without needing an anchored window.

Per capture this reports:
  - click_offset_ms:  matched-filter ground truth (capture's click onset - reference's
                      known click onset), polarity-insensitive, gated on quality_db.
  - stream_offset_ms: the harness's own getTimestamp-derived per-session stream offset
                      (already in the JSON sidecar).
  - residual_ms:      click_offset_ms - stream_offset_ms -- reuses
                      `overdub_analysis.offset_decompose` (same arithmetic Test 2 uses
                      to separate harness start-jitter from real alignment error). Here
                      the interpretation is direct: this residual IS "the discrepancy
                      between AAudio's self-reported latency and the loopback ground
                      truth" that Test 1a's pass bar is stated in terms of.

Aggregated per distinct `condition_id` (capture_format/input_preset arm), over reps
with xrun_count == 0 and click quality >= --quality-floor-db:
  - Test 1a: max |residual_ms| across the group must stay <= --tolerance-ms (default
    5 ms, prototype-plan.md Test 1a).
  - Test 1: population std of residual_ms across the group must stay <= --stability-ms
    (default 3 ms) -- prototype-plan.md's 2026-07-08 "Threshold clarification": the
    +/-3ms bar is on per-rep offsets *after* subtracting each rep's own getTimestamp
    stream offset, since raw offsets across independently-started sessions carry
    benign start-jitter the +/-3ms bar was never meant to catch.

This does NOT establish the "two sequentially-scheduled players" negative control
prototype-plan.md's Test 1 method also calls for -- that needs a different capture
mode (not yet built), not a different offline analysis of the existing captures.

Usage (from analysis/ via the venv per CLAUDE.md):
    .venv/Scripts/python.exe scripts/run_loopback_click_offset.py \\
        --loopback-dir loopback_data \\
        --reference ../harness/src/main/assets/reference_track.wav

Writes a CSV (default <loopback-dir>/loopback_click_offset_results.csv) and prints a
per-capture table plus a per-condition_id summary. Exit code is non-zero if no captures
are found.
"""

from __future__ import annotations

import argparse
import csv
import json
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, filtfilt

from overdub_analysis.calibration_click import CLICK_F_HI_HZ, CLICK_F_LO_HZ, PRE_SILENCE_S, detect_click
from overdub_analysis.offset_decompose import OffsetRecord, summarize

_CLICK_QUALITY_FLOOR_DB = 10.0


def _read_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    if sampwidth != 2:
        raise ValueError(f"{path}: only 16-bit PCM is supported (got {sampwidth * 8}-bit)")
    data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def _bandpass(x: np.ndarray, lo: float, hi: float, fs: int) -> np.ndarray:
    """Zero-phase 4th-order Butterworth bandpass (filtfilt: no group-delay offset)."""
    nyq = 0.5 * fs
    b, a = butter(4, [lo / nyq, hi / nyq], btype="band")
    return filtfilt(b, a, x)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loopback-dir", default="loopback_data")
    parser.add_argument("--reference", default="../harness/src/main/assets/reference_track.wav")
    parser.add_argument("--lo", type=float, default=CLICK_F_LO_HZ, help="bandpass low edge (Hz)")
    parser.add_argument("--hi", type=float, default=CLICK_F_HI_HZ, help="bandpass high edge (Hz)")
    parser.add_argument(
        "--max-offset-ms",
        type=float,
        default=300.0,
        help="half-width of the click search window around the reference's known click "
        "onset -- the electrical round trip is physically bounded well under this",
    )
    parser.add_argument(
        "--quality-floor-db", type=float, default=_CLICK_QUALITY_FLOOR_DB,
        help="minimum matched-filter quality_db to trust a capture's click onset",
    )
    parser.add_argument(
        "--tolerance-ms", type=float, default=5.0,
        help="Test 1a bar: max |residual_ms| per rep (prototype-plan.md Test 1a)",
    )
    parser.add_argument(
        "--stability-ms", type=float, default=3.0,
        help="Test 1 bar: population std of residual_ms across a condition_id's reps "
        "(prototype-plan.md Test 1, per the 2026-07-08 threshold clarification)",
    )
    parser.add_argument("--output-csv", default=None)
    args = parser.parse_args()

    loopback_dir = Path(args.loopback_dir)
    output_csv = (
        Path(args.output_csv) if args.output_csv else loopback_dir / "loopback_click_offset_results.csv"
    )

    wav_paths = sorted(loopback_dir.glob("*.wav"))
    if not wav_paths:
        print(f"no .wav files found in {loopback_dir}")
        return 1

    ref, ref_rate = _read_wav_mono(Path(args.reference))
    ref_bp = _bandpass(ref, args.lo, args.hi, ref_rate)
    click_onset_ref = round(ref_rate * PRE_SILENCE_S)
    wide = int(args.max_offset_ms * 1e-3 * ref_rate)

    print(f"reference: {args.reference}  {len(ref)} samples  {ref_rate} Hz  click onset @ sample {click_onset_ref}")
    print(f"band: {args.lo:.0f}-{args.hi:.0f} Hz  loopback dir: {loopback_dir} ({len(wav_paths)} captures)")
    print(f"quality floor: {args.quality_floor_db:.0f} dB  Test1a bar: |residual| <= {args.tolerance_ms:.1f} ms  "
          f"Test1 bar: residual std <= {args.stability_ms:.1f} ms")
    print()

    rows = []
    for wav_path in wav_paths:
        capture, rate = _read_wav_mono(wav_path)
        if rate != ref_rate:
            print(f"  WARN {wav_path.name}: rate {rate} != ref {ref_rate}")

        json_path = wav_path.with_suffix(".json")
        meta = json.loads(json_path.read_text()) if json_path.exists() else {}
        condition_id = meta.get("condition_id", wav_path.stem)
        xrun = meta.get("xrun_count")
        stream_ms = meta.get("stream_offset_ms")

        cap_bp = _bandpass(capture, args.lo, args.hi, rate)
        det = detect_click(
            cap_bp,
            rate,
            search_window=(max(0, click_onset_ref - wide), click_onset_ref + wide),
        )
        click_samples = det.onset_sample - click_onset_ref
        click_ms = 1000.0 * click_samples / rate

        row = {
            "condition_id": condition_id,
            "click_offset_ms": f"{click_ms:.2f}",
            "click_quality_db": f"{det.quality_db:.1f}",
            "stream_offset_ms": f"{stream_ms:.2f}" if stream_ms is not None else "",
            "residual_ms": "",
            "xrun_count": xrun if xrun is not None else "",
            "input_route": meta.get("input_route", ""),
            "output_route": meta.get("output_route", ""),
            "trusted": "no",
            "wav_file": wav_path.name,
        }

        trusted = det.quality_db >= args.quality_floor_db and (xrun == 0) and stream_ms is not None
        if trusted:
            residual_ms = click_ms - stream_ms
            row["residual_ms"] = f"{residual_ms:.2f}"
            row["trusted"] = "yes"
        rows.append(row)

    print(f"{'condition_id':<38} {'click_ms':>9} {'q_db':>6} {'stream_ms':>10} {'residual_ms':>12} {'xrun':>5}  trusted")
    print("-" * 100)
    for r in rows:
        print(
            f"{r['condition_id']:<38} {r['click_offset_ms']:>9} {r['click_quality_db']:>6} "
            f"{r['stream_offset_ms']:>10} {r['residual_ms']:>12} {str(r['xrun_count']):>5}  {r['trusted']}"
        )
    print("-" * 100)

    # Per-condition_id aggregate, over trusted reps only.
    by_condition: dict[str, list[dict]] = {}
    for r in rows:
        by_condition.setdefault(r["condition_id"], []).append(r)

    print()
    for condition_id, group in by_condition.items():
        trusted_rows = [r for r in group if r["trusted"] == "yes"]
        print(f"{condition_id}: {len(group)} captures, {len(trusted_rows)} trusted")
        if len(trusted_rows) < 2:
            print("  not enough trusted reps to judge stability")
            continue
        records = [
            OffsetRecord(
                condition_id=condition_id,
                gcc_phat_offset_ms=float(r["click_offset_ms"]),
                stream_offset_ms=float(r["stream_offset_ms"]),
            )
            for r in trusted_rows
        ]
        summary = summarize(records)
        max_abs_residual = max(abs(r.residual_ms) for r in records if r.residual_ms is not None)
        test1a_pass = max_abs_residual <= args.tolerance_ms
        test1_pass = (summary.residual_std_ms or 0.0) <= args.stability_ms
        print(
            f"  residual (ms): mean={summary.residual_mean_ms:.2f} std={summary.residual_std_ms:.2f} "
            f"max|.|={max_abs_residual:.2f}  (n={summary.n_with_timestamps})"
        )
        print(
            f"  Test1a (max|residual| <= {args.tolerance_ms:.1f} ms): "
            + ("PASS" if test1a_pass else "FAIL")
        )
        print(
            f"  Test1  (residual std <= {args.stability_ms:.1f} ms):   "
            + ("PASS" if test1_pass else "FAIL")
        )
        print()

    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"CSV: {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
