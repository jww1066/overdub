#!/usr/bin/env python3
"""Click-gated GCC-PHAT sweep: the honest Test 2 step 2 gate (item 11c).

Successor to `run_bandlimited_gcc_phat_sweep.py` for captures made with the
click-bearing reference asset (2026-07-08 or later). That script's gate --
PSR >= 6 dB inside a (0, 300 ms) positivity lag window -- was shown by the
calibration-click cross-check to bless a +187 ms beat-period alias of the
reference (doc/test2-sweep-results.md), and `evaluate_alias_gate.py` then
measured that the alias peak genuinely dominates the band-limited correlation
(~12 dB above the true peak), so no wide window -- signed or not -- can fix it.
The remedy is an ANCHORED window narrower than half the ~187 ms beat period,
centered per capture on the matched-filter click ground truth, plus the gate

    PASS  <=>  |gcc_phat_offset - click_offset| <= 2 ms      (the +/-2 ms bar)

**PSR is reported as a diagnostic only, never gated on.** The true acoustic
peak is a multipath cluster (near-equal sub-peaks spread over ~+/-6 samples at
48 kHz), so the 2-sample-exclusion PSR reads ~0 dB at a perfectly correct
alignment; the default diagnostic exclusion here is wider (16 samples) to span
that cluster. See `evaluate_alias_gate.py`'s peak-shape output.

Per capture this also emits `stream_minus_click_ms` (getTimestamp stream offset
minus click truth) when the sidecar carries `stream_offset_ms`: across a sweep
this is the per-capture measurement-basis residual -- the ~14-15 ms constant the
timestamp study could previously only infer as (201 ms residual - 187 ms alias).

Old click-less captures score below the click-quality floor and are reported as
`no-click` rather than silently mis-gated (pairing rule:
harness/src/main/assets/reference_track_README.md).

Usage (from analysis/ via the venv per CLAUDE.md):
    .venv/Scripts/python.exe scripts/run_click_gated_sweep.py --sweep-dir <dir> \\
        --reference ../harness/src/main/assets/reference_track.wav

Writes a CSV (default <sweep-dir>/click_gated_results.csv) and prints a
matrix-ordered summary. Exit code is non-zero if no captures are found.
"""

from __future__ import annotations

import argparse
import csv
import json
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, filtfilt

from overdub_analysis.calibration_click import PRE_SILENCE_S, detect_click
from overdub_analysis.gcc_phat import gcc_phat

# Matrix-axis ordering for the summary table (matches run_gcc_phat_sweep.py).
_DISTANCE_ORDER = {"near": 0, "armslength": 1, "far": 2}
_ORIENTATION_ORDER = {"faceup": 0, "facedown": 1}
_OBSTRUCTION_ORDER = {"none": 0, "pocketed": 1}
_VOLUME_ORDER = {"quiet": 0, "conversational": 1, "loud": 2}

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


def _sort_key(condition_id: str) -> tuple[int, int, int, int]:
    parts = condition_id.split("_")
    if len(parts) != 4:
        return (99, 99, 99, 99)
    volume, distance, orientation, obstruction = parts
    return (
        _DISTANCE_ORDER.get(distance, 99),
        _ORIENTATION_ORDER.get(orientation, 99),
        _OBSTRUCTION_ORDER.get(obstruction, 99),
        _VOLUME_ORDER.get(volume, 99),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep-dir", default="sweep_data")
    parser.add_argument("--reference", default="../harness/src/main/assets/reference_track.wav")
    parser.add_argument("--lo", type=float, default=500.0, help="bandpass low edge (Hz)")
    parser.add_argument("--hi", type=float, default=4000.0, help="bandpass high edge (Hz)")
    parser.add_argument(
        "--max-offset-ms",
        type=float,
        default=300.0,
        help="half-width of the SIGNED click-search window (+/- around zero offset); "
        "the harness basis is negative, so negative offsets must be admitted",
    )
    parser.add_argument(
        "--anchor-half-width-ms",
        type=float,
        default=90.0,
        help="half-width of the GCC-PHAT lag window centered on each capture's click "
        "offset; must stay below half the ~187 ms reference beat period so a "
        "one-beat alias can never sit inside",
    )
    parser.add_argument("--tolerance-ms", type=float, default=2.0, help="the +/-2 ms pass bar")
    parser.add_argument(
        "--psr-exclusion",
        type=int,
        default=16,
        help="samples excluded around the peak for the DIAGNOSTIC psr_db column; sized "
        "to span the measured ~+/-6-sample multipath cluster of the true acoustic "
        "peak (PSR is never part of the gate)",
    )
    parser.add_argument("--output-csv", default=None)
    args = parser.parse_args()

    sweep_dir = Path(args.sweep_dir)
    output_csv = (
        Path(args.output_csv) if args.output_csv else sweep_dir / "click_gated_results.csv"
    )

    wav_paths = sorted(sweep_dir.glob("*.wav"))
    if not wav_paths:
        print(f"no .wav files found in {sweep_dir}")
        return 1
    if args.anchor_half_width_ms >= 93.5:
        print(
            f"WARN: anchor half-width {args.anchor_half_width_ms} ms >= half the ~187 ms "
            "beat period; a one-beat alias can sit inside the anchored window"
        )

    ref, ref_rate = _read_wav_mono(Path(args.reference))
    ref_bp = _bandpass(ref, args.lo, args.hi, ref_rate)
    click_onset_ref = round(ref_rate * PRE_SILENCE_S)
    wide = int(args.max_offset_ms * 1e-3 * ref_rate)
    anchor_hw = int(args.anchor_half_width_ms * 1e-3 * ref_rate)

    print(f"reference: {args.reference}  {len(ref)} samples  {ref_rate} Hz")
    print(f"band: {args.lo:.0f}-{args.hi:.0f} Hz  sweep dir: {sweep_dir} ({len(wav_paths)} captures)")
    print(f"gate: |gcc_phat - click| <= {args.tolerance_ms} ms inside a click-anchored "
          f"+/-{args.anchor_half_width_ms:.0f} ms window (PSR diagnostic-only, "
          f"exclusion {args.psr_exclusion})")
    print()

    rows = []
    for wav_path in wav_paths:
        capture, rate = _read_wav_mono(wav_path)
        if rate != ref_rate:
            print(f"  WARN {wav_path.name}: rate {rate} != ref {ref_rate}")

        det = detect_click(
            capture,
            rate,
            search_window=(max(0, click_onset_ref - wide), click_onset_ref + wide),
        )
        click_samples = det.onset_sample - click_onset_ref
        click_ms = 1000.0 * click_samples / rate

        json_path = wav_path.with_suffix(".json")
        meta = json.loads(json_path.read_text()) if json_path.exists() else {}
        stream_ms = meta.get("stream_offset_ms")

        row = {
            "condition_id": meta.get("condition_id", wav_path.stem),
            "click_offset_ms": f"{click_ms:.2f}",
            "click_quality_db": f"{det.quality_db:.1f}",
            "gcc_offset_ms": "",
            "err_ms": "",
            "verdict": "no-click",
            "psr_db_diag": "",
            "stream_offset_ms": f"{stream_ms:.2f}" if stream_ms is not None else "",
            "stream_minus_click_ms": "",
            "device_model": meta.get("device_model", ""),
            "wav_file": wav_path.name,
        }

        if det.quality_db >= _CLICK_QUALITY_FLOOR_DB:
            cap_bp = _bandpass(capture, args.lo, args.hi, rate)
            r = gcc_phat(
                ref_bp,
                cap_bp,
                fs=rate,
                psr_exclusion=args.psr_exclusion,
                lag_window=(click_samples - anchor_hw, click_samples + anchor_hw),
            )
            gcc_ms = (r.offset_seconds or 0.0) * 1000.0
            err_ms = gcc_ms - click_ms
            row.update({
                "gcc_offset_ms": f"{gcc_ms:.2f}",
                "err_ms": f"{err_ms:.2f}",
                "verdict": "PASS" if abs(err_ms) <= args.tolerance_ms else "FAIL",
                "psr_db_diag": f"{r.psr_db:.1f}",
            })
            if stream_ms is not None:
                row["stream_minus_click_ms"] = f"{stream_ms - click_ms:.2f}"
        rows.append(row)

    rows.sort(key=lambda r: _sort_key(r["condition_id"]))

    print(f"{'condition_id':<42} {'click_ms':>9} {'q_db':>5} {'gcc_ms':>9} "
          f"{'err_ms':>7} {'psr':>5} {'strm-clk':>8}  verdict")
    print("-" * 100)
    counts = {"PASS": 0, "FAIL": 0, "no-click": 0}
    for r in rows:
        print(f"{r['condition_id']:<42} {r['click_offset_ms']:>9} {r['click_quality_db']:>5} "
              f"{r['gcc_offset_ms']:>9} {r['err_ms']:>7} {r['psr_db_diag']:>5} "
              f"{r['stream_minus_click_ms']:>8}  {r['verdict']}")
        counts[r["verdict"]] += 1
    print("-" * 100)
    total = len(rows)
    print(f"verdicts: {counts['PASS']} PASS, {counts['FAIL']} FAIL, "
          f"{counts['no-click']} no-click  /  {total} total "
          f"(PASS = |gcc - click| <= {args.tolerance_ms} ms)")

    errs = np.array([float(r["err_ms"]) for r in rows if r["err_ms"] != ""])
    if errs.size:
        print(f"correlator error vs click (ms): mean={errs.mean():.2f} std={errs.std():.2f} "
              f"max|err|={np.abs(errs).max():.2f}")
    basis = np.array([
        float(r["stream_minus_click_ms"]) for r in rows if r["stream_minus_click_ms"] != ""
    ])
    if basis.size:
        print(f"stream - click basis residual (ms): mean={basis.mean():.2f} "
              f"std={basis.std():.2f}  (the genuine measurement-basis constant, "
              f"per-capture)")

    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSV: {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
