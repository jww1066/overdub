#!/usr/bin/env python3
"""Run GCC-PHAT over a directory of captured sweep WAVs against a reference track.

For each `<condition_id>_<timestamp>.wav` in --sweep-dir, correlate the captured bleed
against the reference track that was played through the speaker (default: the bundled
harness/src/main/assets/reference_track.wav), and emit per-cell GCC-PHAT offset +
peak-to-sidelobe ratio (PSR) alongside the JSON sidecar's metadata. This is the offline
Test 2 step 1 pass over real Tier-3 captures -- the on-device sanity gate only checked
RMS; PSR is the alignment-trustworthiness metric the prototype-plan thresholds gate on
(>=6 dB minimum, >=10 dB confident; see analysis/src/overdub_analysis/gcc_phat.py).

Reusable: re-run after any re-capture or on a second device's sweep dir. Writes a CSV
(default <sweep-dir>/gcc_phat_results.csv) and prints a matrix-ordered summary table
with a verdict per cell.

Usage (from the analysis/ dir, via the venv per CLAUDE.md):
    .venv/Scripts/python.exe scripts/run_gcc_phat_sweep.py \\
        --sweep-dir sweep_data \\
        --reference ../harness/src/main/assets/reference_track.wav

Exit code is non-zero if no captures are found or the reference track can't be read.
"""

from __future__ import annotations

import argparse
import csv
import json
import wave
from pathlib import Path

import numpy as np

from overdub_analysis.gcc_phat import gcc_phat

# Matrix-axis ordering for the summary table (volume x distance x orientation x
# obstruction from test2-step2-plan.md Components Sec 3). Sort key = the tuple of
# these indices, so the table reads in physical-arrangement order, volume innermost.
_DISTANCE_ORDER = {"near": 0, "armslength": 1, "far": 2}
_ORIENTATION_ORDER = {"faceup": 0, "facedown": 1}
_OBSTRUCTION_ORDER = {"none": 0, "pocketed": 1}
_VOLUME_ORDER = {"quiet": 0, "conversational": 1, "loud": 2}

# PSR verdict bands (prototype-plan.md Test 2 thresholds).
_PSR_CONFIDENT_DB = 10.0
_PSR_MINIMUM_DB = 6.0


def _read_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    """Return (float64 mono samples in [-1, 1], framerate). Downmixes multi-channel by averaging.

    16-bit PCM only (the harness writes 16-bit; resample_wav.py has the same constraint).
    """
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


def _rms_int16(samples: np.ndarray) -> float:
    """RMS on the int16 scale the harness uses (RMS_SANITY_FLOOR = 50.0 is in these units)."""
    pcm = (samples * 32768.0).round().astype(np.int64)
    return float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2)))


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
    parser.add_argument(
        "--sweep-dir",
        default="sweep_data",
        help="directory of <condition_id>_<timestamp>.wav + .json pairs (default: sweep_data)",
    )
    parser.add_argument(
        "--reference",
        default="../harness/src/main/assets/reference_track.wav",
        help="reference track WAV that was played through the speaker",
    )
    parser.add_argument(
        "--output-csv",
        default=None,
        help="CSV output path (default: <sweep-dir>/gcc_phat_results.csv)",
    )
    args = parser.parse_args()

    sweep_dir = Path(args.sweep_dir)
    reference_path = Path(args.reference)
    output_csv = Path(args.output_csv) if args.output_csv else sweep_dir / "gcc_phat_results.csv"

    wav_paths = sorted(sweep_dir.glob("*.wav"))
    if not wav_paths:
        print(f"no .wav files found in {sweep_dir}")
        return 1

    ref, ref_rate = _read_wav_mono(reference_path)
    print(
        f"reference: {reference_path}  {len(ref)} samples  {ref_rate} Hz  "
        f"{len(ref) / ref_rate:.2f}s"
    )
    print(f"sweep dir: {sweep_dir}  ({len(wav_paths)} captures)")
    print()

    rows = []
    for wav_path in wav_paths:
        json_path = wav_path.with_suffix(".json")
        mic, mic_rate = _read_wav_mono(wav_path)
        if mic_rate != ref_rate:
            print(
                f"  WARN {wav_path.name}: capture rate {mic_rate} Hz != reference {ref_rate} Hz "
                f"-- offset/PSR are not meaningful; fix the rate mismatch before trusting this row"
            )

        result = gcc_phat(ref, mic, fs=ref_rate)
        rms = _rms_int16(mic)

        meta = {}
        if json_path.exists():
            meta = json.loads(json_path.read_text())

        offset_ms = (result.offset_seconds or 0.0) * 1000.0
        row = {
            "condition_id": meta.get("condition_id", wav_path.stem),
            "volume": meta.get("playback_volume", ""),
            "distance_cm": meta.get("distance_cm", ""),
            "orientation": meta.get("orientation", ""),
            "obstruction": meta.get("obstruction", ""),
            "rms_int16": f"{rms:.1f}",
            "psr_db": f"{result.psr_db:.1f}",
            "offset_samples": result.offset_samples,
            "offset_ms": f"{offset_ms:.2f}",
            "sample_rate": mic_rate,
            "xrun_count": meta.get("xrun_count", ""),
            "output_route": meta.get("output_route", ""),
            "input_preset": meta.get("input_preset", ""),
            "device_model": meta.get("device_model", ""),
            "stream_volume_index": meta.get("stream_volume_index", ""),
            "timestamp": meta.get("timestamp", ""),
            "wav_file": wav_path.name,
            "verdict": _verdict(result.psr_db),
        }
        rows.append(row)

    rows.sort(key=lambda r: _sort_key(r["condition_id"]))

    # Summary table to stdout.
    print(f"{'condition_id':<42} {'rms':>8} {'psr_db':>7} {'off_ms':>8} {'verdict':<10}")
    print("-" * 80)
    counts = {"confident": 0, "minimum": 0, "below": 0}
    for r in rows:
        print(
            f"{r['condition_id']:<42} {r['rms_int16']:>8} {r['psr_db']:>7} "
            f"{r['offset_ms']:>8} {r['verdict']:<10}"
        )
        counts[r["verdict"]] += 1
    print("-" * 80)
    total = len(rows)
    print(
        f"verdicts: {counts['confident']} confident (>= {_PSR_CONFIDENT_DB:.0f} dB), "
        f"{counts['minimum']} minimum (>= {_PSR_MINIMUM_DB:.0f} dB), "
        f"{counts['below']} below (< {_PSR_MINIMUM_DB:.0f} dB)  /  {total} total"
    )

    fieldnames = list(rows[0].keys())
    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSV: {output_csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
