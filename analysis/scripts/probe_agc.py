#!/usr/bin/env python3
"""Decompose the sweep's gain-ratio compression: device-level vs coupling-path (item 8).

Sweep finding 2 (doc/test2-sweep-results.md): captured RMS compresses the programmatic
gain ratio everywhere (conv/quiet measured ~2.2-2.7x vs the 3.0x a linear chain would
give; loud/quiet ~2.9-3.9x vs 5.0x), worse face-down than face-up -- suggesting TWO
superimposed compression components: a device-level one (residual AGC and/or speaker-amp
nonlinearity, present at both orientations) and a coupling-path one (the speaker->pad
mechanical coupling saturating, face-down only). The raw finding used whole-file RMS with
the room noise floor still folded in, which itself flattens ratios at the quiet end.

This script does the decomposition properly:

1. **Noise-floor subtraction in the power domain, per capture.** Frame-wise RMS (50 ms
   frames); the floor is a low percentile of frame power (the capture's own lead-in/tail
   silence -- the input stream runs before playback starts and 200 ms past its end).
   Corrected signal power = mean power - floor power. The silence fraction is ~constant
   across cells (same reference, same tail), so it scales all cells equally and cancels
   in ratios.
2. **Fit log(corrected RMS) vs log(gain) per physical arrangement** (12 arrangements x
   3 volumes). The slope is the compression exponent: 1.0 = linear chain, lower =
   compression. A 3-point fit; the two pairwise ratios are printed alongside so the fit
   isn't hiding a non-monotonic cell.
3. **Decompose by orientation.** Face-up has no pad coupling, so its mean slope isolates
   the device-level component; face-down carries device + coupling, so the slope
   *difference* estimates the coupling-path component.

What this cannot tell apart: input-side AGC vs output-side speaker-amp compression --
both are "device-level" here. That split needs the on-device two-gain tone probe
(prototype-plan.md "Cross-device generalization"), which plays a fixed tone at two known
gains on the device under test; this script is the offline decomposition of the sweep
data that already exists.

Usage (from analysis/ via the venv per CLAUDE.md):
    .venv/Scripts/python.exe scripts/probe_agc.py --sweep-dir sweep_data
"""

from __future__ import annotations

import argparse
import csv
import json
import wave
from pathlib import Path

import numpy as np

_VOLUME_GAIN = {"quiet": 0.2, "conversational": 0.6, "loud": 1.0}
_DISTANCE_ORDER = {"near": 0, "armslength": 1, "far": 2}
_ORIENTATION_ORDER = {"faceup": 0, "facedown": 1}
_OBSTRUCTION_ORDER = {"none": 0, "pocketed": 1}


def _read_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    if sampwidth != 2:
        raise ValueError(f"{path}: only 16-bit PCM is supported (got {sampwidth * 8}-bit)")
    data = np.frombuffer(raw, dtype="<i2").astype(np.float64)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def _corrected_rms(samples: np.ndarray, rate: int, frame_ms: float, floor_pct: float) -> tuple[float, float]:
    """(floor-corrected RMS, floor RMS), both int16-scale.

    Frame-wise mean power; floor = `floor_pct` percentile of frame power; corrected
    power = mean(frame power) - floor power, clamped at 0.
    """
    frame = max(1, int(rate * frame_ms / 1000.0))
    n_frames = samples.size // frame
    if n_frames < 4:
        raise ValueError(f"capture too short for {frame_ms} ms framing ({samples.size} samples)")
    frames = samples[: n_frames * frame].reshape(n_frames, frame)
    power = np.mean(frames**2, axis=1)
    floor_power = float(np.percentile(power, floor_pct))
    signal_power = max(0.0, float(np.mean(power)) - floor_power)
    return float(np.sqrt(signal_power)), float(np.sqrt(floor_power))


def _fit_slope(gains: list[float], rmses: list[float]) -> float:
    """Least-squares slope of log(rms) vs log(gain) -- the compression exponent."""
    x = np.log(np.array(gains))
    y = np.log(np.array(rmses))
    return float(np.polyfit(x, y, 1)[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep-dir", default="sweep_data")
    parser.add_argument("--frame-ms", type=float, default=50.0, help="RMS analysis frame (ms)")
    parser.add_argument(
        "--floor-percentile",
        type=float,
        default=5.0,
        help="percentile of frame power taken as the capture's own noise floor",
    )
    parser.add_argument("--output-csv", default=None)
    args = parser.parse_args()

    sweep_dir = Path(args.sweep_dir)
    wav_paths = sorted(sweep_dir.glob("*.wav"))
    if not wav_paths:
        print(f"no .wav files found in {sweep_dir}")
        return 1

    # Per-capture corrected RMS, keyed by (distance, orientation, obstruction) -> volume.
    cells: dict[tuple[str, str, str], dict[str, dict[str, float]]] = {}
    for wav_path in wav_paths:
        meta_path = wav_path.with_suffix(".json")
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        condition_id = meta.get("condition_id", wav_path.stem)
        parts = condition_id.split("_")
        if len(parts) != 4 or parts[0] not in _VOLUME_GAIN:
            print(f"  WARN skipping {wav_path.name}: not a sweep condition id ({condition_id})")
            continue
        volume, distance, orientation, obstruction = parts
        samples, rate = _read_wav_mono(wav_path)
        corrected, floor = _corrected_rms(samples, rate, args.frame_ms, args.floor_percentile)
        cells.setdefault((distance, orientation, obstruction), {})[volume] = {
            "corrected_rms": corrected,
            "floor_rms": floor,
            "raw_rms": float(np.sqrt(np.mean(samples**2))),
        }

    arrangements = sorted(
        cells.keys(),
        key=lambda k: (_DISTANCE_ORDER.get(k[0], 99), _ORIENTATION_ORDER.get(k[1], 99),
                       _OBSTRUCTION_ORDER.get(k[2], 99)),
    )

    print(f"sweep dir: {sweep_dir} ({len(wav_paths)} captures, {len(arrangements)} arrangements)")
    print(f"floor: {args.floor_percentile:.0f}th percentile of {args.frame_ms:.0f} ms frame power, "
          f"subtracted in the power domain")
    print()
    print(f"{'arrangement':<32} {'slope':>6} {'conv/quiet':>10} {'loud/quiet':>10} "
          f"{'(linear:':>9} {'3.00':>5} {'5.00)':>6}  floor_rms q/c/l")
    print("-" * 104)

    rows = []
    slopes: dict[str, list[float]] = {"faceup": [], "facedown": []}
    for key in arrangements:
        distance, orientation, obstruction = key
        by_vol = cells[key]
        if set(by_vol.keys()) != set(_VOLUME_GAIN.keys()):
            print(f"{'_'.join(key):<32} INCOMPLETE (has {sorted(by_vol.keys())})")
            continue
        gains = [_VOLUME_GAIN[v] for v in ("quiet", "conversational", "loud")]
        rmses = [by_vol[v]["corrected_rms"] for v in ("quiet", "conversational", "loud")]
        floors = [by_vol[v]["floor_rms"] for v in ("quiet", "conversational", "loud")]
        slope = _fit_slope(gains, rmses)
        conv_quiet = rmses[1] / rmses[0]
        loud_quiet = rmses[2] / rmses[0]
        slopes[orientation].append(slope)
        label = f"{distance}_{orientation}_{obstruction}"
        print(f"{label:<32} {slope:>6.3f} {conv_quiet:>10.2f} {loud_quiet:>10.2f} "
              f"{'':>9} {'':>5} {'':>6}  {floors[0]:.0f}/{floors[1]:.0f}/{floors[2]:.0f}")
        rows.append({
            "distance": distance,
            "orientation": orientation,
            "obstruction": obstruction,
            "slope": f"{slope:.3f}",
            "conv_quiet_ratio": f"{conv_quiet:.2f}",
            "loud_quiet_ratio": f"{loud_quiet:.2f}",
            "corrected_rms_quiet": f"{rmses[0]:.1f}",
            "corrected_rms_conversational": f"{rmses[1]:.1f}",
            "corrected_rms_loud": f"{rmses[2]:.1f}",
            "floor_rms_quiet": f"{floors[0]:.1f}",
            "floor_rms_conversational": f"{floors[1]:.1f}",
            "floor_rms_loud": f"{floors[2]:.1f}",
        })

    print("-" * 104)
    up = np.array(slopes["faceup"])
    down = np.array(slopes["facedown"])
    if up.size and down.size:
        print(f"face-up   slope: mean={up.mean():.3f} std={up.std():.3f} (n={up.size})  "
              f"-- device-level compression exponent (no pad coupling in this path)")
        print(f"face-down slope: mean={down.mean():.3f} std={down.std():.3f} (n={down.size})  "
              f"-- device-level + pad-coupling")
        print(f"coupling-path component (face-up minus face-down slope): {up.mean() - down.mean():.3f}")
        print()
        print("reading: slope 1.000 = linear chain; below 1 = compression. The face-up slope")
        print("isolates the device-level component (residual AGC / speaker-amp nonlinearity,")
        print("despite InputPreset VoiceRecognition); the face-down shortfall vs face-up is the")
        print("mechanical speaker->pad coupling saturating. Input-AGC vs output-amp cannot be")
        print("split offline -- that needs the on-device two-gain tone probe (prototype-plan.md).")

    if rows:
        output_csv = Path(args.output_csv) if args.output_csv else sweep_dir / "agc_probe_results.csv"
        with open(output_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nCSV: {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
