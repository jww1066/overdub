#!/usr/bin/env python3
"""Detect the calibration click in capture WAV(s) and report the ground-truth offset.

The in-basis ground truth for Test 2's +/-2 ms bar (doc/test2-step2-plan.md item 11):
the bundled reference carries a known chirp at CLICK onset sample
(`overdub_analysis.calibration_click`, PRE_SILENCE_S * rate = 9600 at 48 kHz), so

    ground_truth_offset = detected onset in capture - click onset in reference

in the capture's own sample clock -- the same basis and sign convention as
``gcc_phat(reference, capture).offset_samples``.

For each input WAV this prints: detected onset, detection quality (dB, PSR-style --
gate on it before trusting the onset), the ground-truth offset in samples/ms, and,
when a JSON sidecar with `stream_offset_ms` sits next to the WAV, the
getTimestamp-derived stream offset for side-by-side comparison.

Only captures made with the click-bearing reference asset (2026-07-08 or later)
contain the click; on older captures the quality score will be low -- that is the
no-click signature, not a bug.

Usage:
    python scripts/detect_calibration_click.py capture.wav [more.wav ...]
    python scripts/detect_calibration_click.py --sweep-dir click_check/
    python scripts/detect_calibration_click.py capture.wav --max-offset-ms 300
"""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np

from overdub_analysis.calibration_click import PRE_SILENCE_S, detect_click


def read_wav_mono_16bit(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    if channels != 1 or sampwidth != 2:
        raise ValueError(f"{path}: expected mono 16-bit PCM, got {channels}ch {sampwidth * 8}-bit")
    return np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0, rate


def sidecar_stream_offset_ms(wav_path: Path) -> float | None:
    sidecar = wav_path.with_suffix(".json")
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text()).get("stream_offset_ms")
    except (json.JSONDecodeError, OSError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wavs", nargs="*", help="capture WAV file(s)")
    parser.add_argument("--sweep-dir", help="process every *.wav in this directory")
    parser.add_argument(
        "--max-offset-ms",
        type=float,
        default=300.0,
        help="half-width of the SIGNED ground-truth offset search window (+/- this around "
        "zero offset). The harness basis is negative -- the captured WAV's sample 0 "
        "precedes input-frame 0 -- so the window must admit negative offsets (see "
        "doc/test2-sweep-results.md 'Calibration click cross-check'). 0 disables the window",
    )
    args = parser.parse_args()

    paths = [Path(p) for p in args.wavs]
    if args.sweep_dir:
        paths += sorted(Path(args.sweep_dir).glob("*.wav"))
    if not paths:
        parser.error("no input WAVs (pass files or --sweep-dir)")

    print(f"{'file':<55} {'onset':>8} {'quality_dB':>10} {'gt_offset_ms':>12} {'stream_ms':>10}")
    for path in paths:
        capture, rate = read_wav_mono_16bit(path)
        click_onset_ref = round(rate * PRE_SILENCE_S)
        window = None
        if args.max_offset_ms > 0:
            half = round(rate * args.max_offset_ms / 1000.0)
            window = (max(0, click_onset_ref - half), click_onset_ref + half)
        det = detect_click(capture, rate, search_window=window)
        gt_samples = det.onset_sample - click_onset_ref
        gt_ms = 1000.0 * gt_samples / rate
        stream_ms = sidecar_stream_offset_ms(path)
        stream_str = f"{stream_ms:10.2f}" if stream_ms is not None else f"{'-':>10}"
        print(
            f"{path.name:<55} {det.onset_sample:>8} {det.quality_db:>10.1f} {gt_ms:>12.2f} {stream_str}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
