#!/usr/bin/env python3
"""Run band-limited GCC-PHAT over a directory of captured sweep WAVs.

This is the population-level counterpart to `diagnose_gcc_phat.py`, which validated
the band-limited PHAT fix (bandpass both signals to ~500-4000 Hz before GCC-PHAT) on a
*single* baseline capture. The full-band pass (`run_gcc_phat_sweep.py`) failed 0/36; the
diagnostic recovered PSR ~10 dB with a +97 ms offset on one cell. Before recording the
fix as "validated", it has to clear the bars across the whole 36-cell matrix -- a single
mid-range cell recovering is a favorable-case existence proof, not a population guarantee
(CLAUDE.md, "favorable-case existence proof, not a population guarantee").

For each `<condition_id>_<timestamp>.wav`, bandpass both the reference and the capture to
--lo..--hi Hz (zero-phase Butterworth, so the true time offset is preserved), run GCC-PHAT,
and report per-cell full-band vs band-limited PSR and offset side by side, plus how many
cells clear the >=6 dB minimum / >=10 dB confident bars and the offset spread across cells
(a real system round-trip should be roughly constant cell-to-cell; a large spread means the
argmax is still landing on noise).

Usage (from analysis/ via the venv per CLAUDE.md):
    .venv/Scripts/python.exe scripts/run_bandlimited_gcc_phat_sweep.py \\
        --sweep-dir sweep_data \\
        --reference ../harness/src/main/assets/reference_track.wav \\
        --lo 500 --hi 4000

Writes a CSV (default <sweep-dir>/gcc_phat_bandlimited_results.csv) and prints a
matrix-ordered summary table. Exit code is non-zero if no captures are found.
"""

from __future__ import annotations

import argparse
import csv
import json
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, filtfilt

from overdub_analysis.gcc_phat import gcc_phat

# Matrix-axis ordering for the summary table (matches run_gcc_phat_sweep.py).
_DISTANCE_ORDER = {"near": 0, "armslength": 1, "far": 2}
_ORIENTATION_ORDER = {"faceup": 0, "facedown": 1}
_OBSTRUCTION_ORDER = {"none": 0, "pocketed": 1}
_VOLUME_ORDER = {"quiet": 0, "conversational": 1, "loud": 2}

_PSR_CONFIDENT_DB = 10.0
_PSR_MINIMUM_DB = 6.0


def _read_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        framerate = w.getframerate()
        raw = w.readframes(w.getnframes())
    if sampwidth != 2:
        raise ValueError(f"{path}: only 16-bit PCM is supported (got {sampwidth * 8}-bit)")
    data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, framerate


def _bandpass(x: np.ndarray, lo: float, hi: float, fs: int) -> np.ndarray:
    """Zero-phase 4th-order Butterworth bandpass (filtfilt: no group-delay offset)."""
    nyq = 0.5 * fs
    b, a = butter(4, [lo / nyq, hi / nyq], btype="band")
    return filtfilt(b, a, x)


def _verdict(psr_db: float) -> str:
    if psr_db >= _PSR_CONFIDENT_DB:
        return "confident"
    if psr_db >= _PSR_MINIMUM_DB:
        return "minimum"
    return "below"


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
    parser.add_argument("--output-csv", default=None)
    args = parser.parse_args()

    sweep_dir = Path(args.sweep_dir)
    output_csv = (
        Path(args.output_csv)
        if args.output_csv
        else sweep_dir / "gcc_phat_bandlimited_results.csv"
    )

    wav_paths = sorted(sweep_dir.glob("*.wav"))
    if not wav_paths:
        print(f"no .wav files found in {sweep_dir}")
        return 1

    ref, ref_rate = _read_wav_mono(Path(args.reference))
    ref_bp = _bandpass(ref, args.lo, args.hi, ref_rate)
    print(f"reference: {args.reference}  {len(ref)} samples  {ref_rate} Hz")
    print(f"band: {args.lo:.0f}-{args.hi:.0f} Hz  sweep dir: {sweep_dir} ({len(wav_paths)} captures)")
    print()

    rows = []
    for wav_path in wav_paths:
        json_path = wav_path.with_suffix(".json")
        mic, mic_rate = _read_wav_mono(wav_path)
        if mic_rate != ref_rate:
            print(f"  WARN {wav_path.name}: rate {mic_rate} != ref {ref_rate}")

        full = gcc_phat(ref, mic, fs=ref_rate)
        mic_bp = _bandpass(mic, args.lo, args.hi, mic_rate)
        bp = gcc_phat(ref_bp, mic_bp, fs=ref_rate)

        meta = json.loads(json_path.read_text()) if json_path.exists() else {}
        rows.append({
            "condition_id": meta.get("condition_id", wav_path.stem),
            "full_psr_db": f"{full.psr_db:.1f}",
            "full_offset_ms": f"{(full.offset_seconds or 0.0) * 1000.0:.2f}",
            "bp_psr_db": f"{bp.psr_db:.1f}",
            "bp_offset_ms": f"{(bp.offset_seconds or 0.0) * 1000.0:.2f}",
            "bp_offset_samples": bp.offset_samples,
            "verdict": _verdict(bp.psr_db),
            "device_model": meta.get("device_model", ""),
            "wav_file": wav_path.name,
        })

    rows.sort(key=lambda r: _sort_key(r["condition_id"]))

    print(f"{'condition_id':<42} {'full_psr':>8} {'full_ms':>9} {'bp_psr':>7} {'bp_ms':>9} {'verdict':<9}")
    print("-" * 92)
    counts = {"confident": 0, "minimum": 0, "below": 0}
    for r in rows:
        print(f"{r['condition_id']:<42} {r['full_psr_db']:>8} {r['full_offset_ms']:>9} "
              f"{r['bp_psr_db']:>7} {r['bp_offset_ms']:>9} {r['verdict']:<9}")
        counts[r["verdict"]] += 1
    print("-" * 92)
    total = len(rows)
    print(
        f"band-limited verdicts: {counts['confident']} confident (>= {_PSR_CONFIDENT_DB:.0f} dB), "
        f"{counts['minimum']} minimum (>= {_PSR_MINIMUM_DB:.0f} dB), "
        f"{counts['below']} below (< {_PSR_MINIMUM_DB:.0f} dB)  /  {total} total"
    )
    bp_ms = np.array([float(r["bp_offset_ms"]) for r in rows])
    print(
        f"band-limited offset (ms): min={bp_ms.min():.1f} max={bp_ms.max():.1f} "
        f"mean={bp_ms.mean():.1f} std={bp_ms.std():.1f}  "
        f"(a real round-trip should be ~constant cell-to-cell)"
    )

    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSV: {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
