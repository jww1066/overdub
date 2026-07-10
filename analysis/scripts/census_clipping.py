#!/usr/bin/env python3
"""Clip census for capture WAVs, int16 or float32 -- the capture-headroom probe's offline judge.

Context (doc/guides/offline-dsp.md "census raw captures"; design-summary.md capture-headroom):
the Pixel 10's input chain rails on kick transients at conversational volume (1,247 railed
samples in the Session A baseline). The headroom probe re-captures the same cell three ways
(i16+VoiceRecognition control, float32+VoiceRecognition, float32+Unprocessed) and this script
answers, per file: is the waveform flat-topped, and where does its peak sit relative to int16
full scale?

Reported per file:
  - format/rate/duration, RMS (dBFS re. int16 FS);
  - peak |x| as a fraction of int16 full scale (>1.0 is only reachable in a float capture and
    is direct evidence of recovered headroom);
  - railed count: samples at/above int16 full scale (the control arm's expected signature);
  - near-FS count: samples >= 99% of int16 FS;
  - flat-top run: the longest run of consecutive samples equal to the file's own peak value --
    the rail detector that works even when a float capture rails at some value OTHER than
    int16 FS (an analog-saturation rail lands wherever the HAL gain puts it);
  - the sidecar's capture_format/input_preset/xrun_count when a matching .json sits next to
    the WAV (honesty check: the sidecar must agree with the file's actual dtype).

Verdict per file: RAILED when railed > 0 or the flat-top run is >= FLAT_TOP_RUN_MIN samples at
a peak >= 0.5 FS (a smooth 48 kHz waveform does not hold its exact peak for that long); else
CLEAN. Exit code is 0 always -- both outcomes are data (the control arm SHOULD rail); this is
a measurement, not a gate.

Usage:
    analysis/.venv/Scripts/python analysis/scripts/census_clipping.py capture1.wav capture2.wav
    analysis/.venv/Scripts/python analysis/scripts/census_clipping.py headroom_probe/*.wav
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy.io import wavfile

INT16_FULL_SCALE = 32767.0
# A smooth acoustic waveform at 48 kHz holds its exact sample-quantized peak for 1-2 samples;
# a rail holds it for tens. 4 is conservatively between.
FLAT_TOP_RUN_MIN = 4


def longest_run_at(x: np.ndarray, value: float) -> int:
    """Longest run of consecutive samples whose |x| equals `value` exactly."""
    hits = np.abs(x) == value
    if not hits.any():
        return 0
    # Run lengths via boundaries of the boolean mask.
    padded = np.concatenate(([False], hits, [False]))
    edges = np.flatnonzero(np.diff(padded.astype(np.int8)))
    starts, ends = edges[::2], edges[1::2]
    return int((ends - starts).max())


def census_one(path: Path) -> dict:
    rate, data = wavfile.read(path)
    if data.ndim > 1:
        data = data[:, 0]  # captures are mono; take channel 0 if not

    if data.dtype == np.int16:
        fmt = "i16"
        x = data.astype(np.float64)  # already in int16 counts
    elif data.dtype == np.float32:
        fmt = "float32"
        # Scale float FS (+/-1.0) into int16 counts: int16 FS 32767 == 32767/32768 of float FS,
        # so the shared thresholds below compare like with like across formats.
        x = data.astype(np.float64) * (INT16_FULL_SCALE + 1.0)
    else:
        raise ValueError(f"unsupported WAV dtype {data.dtype} (expected int16 or float32)")

    abs_x = np.abs(x)
    peak = float(abs_x.max()) if x.size else 0.0
    rms = float(np.sqrt(np.mean(x**2))) if x.size else 0.0
    railed = int((abs_x >= INT16_FULL_SCALE).sum())
    near_fs = int((abs_x >= 0.99 * INT16_FULL_SCALE).sum())
    over_fs = int((abs_x > INT16_FULL_SCALE + 1.0).sum())  # beyond int16 range: float-only headroom
    flat_run = longest_run_at(x, peak) if peak > 0 else 0

    is_railed = railed > 0 or (flat_run >= FLAT_TOP_RUN_MIN and peak >= 0.5 * INT16_FULL_SCALE)

    sidecar = {}
    json_path = path.with_suffix(".json")
    if json_path.exists():
        meta = json.loads(json_path.read_text())
        sidecar = {
            "capture_format": meta.get("capture_format"),
            "input_preset": meta.get("input_preset"),
            "xrun_count": meta.get("xrun_count"),
        }

    return {
        "path": path,
        "fmt": fmt,
        "rate": int(rate),
        "n": int(x.size),
        "peak_fs": peak / INT16_FULL_SCALE,
        "rms_dbfs": 20.0 * math.log10(rms / INT16_FULL_SCALE) if rms > 0 else float("-inf"),
        "railed": railed,
        "near_fs": near_fs,
        "over_fs": over_fs,
        "flat_run": flat_run,
        "is_railed": is_railed,
        "sidecar": sidecar,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("paths", nargs="+", help="capture WAV file(s)")
    args = parser.parse_args()

    for p in args.paths:
        path = Path(p)
        r = census_one(path)
        verdict = "RAILED" if r["is_railed"] else "CLEAN"
        print(f"{path.name}")
        print(f"  format={r['fmt']} rate={r['rate']} n={r['n']} ({r['n'] / r['rate']:.2f} s)")
        print(f"  rms={r['rms_dbfs']:.1f} dBFS  peak={r['peak_fs']:.6f} x int16-FS")
        print(
            f"  railed(>=int16 FS)={r['railed']}  near(>=99% FS)={r['near_fs']}  "
            f"over(int16 range)={r['over_fs']}  flat-top run={r['flat_run']}"
        )
        if r["sidecar"]:
            s = r["sidecar"]
            print(
                f"  sidecar: capture_format={s['capture_format']} "
                f"input_preset={s['input_preset']} xrun={s['xrun_count']}"
            )
            if s["capture_format"] is not None and s["capture_format"] != r["fmt"]:
                print("  WARNING sidecar capture_format disagrees with the file's actual dtype")
        print(f"  verdict: {verdict}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
