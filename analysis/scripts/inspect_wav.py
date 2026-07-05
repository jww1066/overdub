#!/usr/bin/env python3
"""Print the PCM format of one or more WAV files, and optionally gate on expected values.

Used to confirm a reference-track or captured-sweep WAV matches what the harness
expects before it is bundled/analysed -- the harness warns (does not resample) on a
sample-rate mismatch, so an off-rate reference track silently confounds the sweep.
The Pixel 10's native output rate is 48000 Hz mono (test2-step2-plan.md Components
Sec 1), which is the default expectation here.

Exit code is non-zero if any file fails an --expect-* check, so this is usable as a
gate in a script or CI step, not just for eyeballing.

Usage:
    python scripts/inspect_wav.py boots.wav
    python scripts/inspect_wav.py ../boots.wav --expect-rate 48000 --expect-channels 1
    python scripts/inspect_wav.py sweep/*.wav --expect-rate 48000
"""

from __future__ import annotations

import argparse
import wave


def inspect(path: str) -> dict:
    with wave.open(path, "rb") as w:
        channels = w.getnchannels()
        sampwidth_bits = w.getsampwidth() * 8
        framerate = w.getframerate()
        frames = w.getnframes()
    return {
        "path": path,
        "channels": channels,
        "sampwidth_bits": sampwidth_bits,
        "framerate": framerate,
        "frames": frames,
        "duration_s": frames / framerate if framerate else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="WAV file(s) to inspect")
    parser.add_argument("--expect-rate", type=int, default=None, help="fail if framerate != this (Hz)")
    parser.add_argument("--expect-channels", type=int, default=None, help="fail if channel count != this")
    parser.add_argument("--expect-bits", type=int, default=None, help="fail if sample width != this (bits)")
    args = parser.parse_args()

    any_fail = False
    for path in args.paths:
        try:
            info = inspect(path)
        except (OSError, wave.Error) as e:
            print(f"{path}: ERROR - {e}")
            any_fail = True
            continue

        checks = []
        if args.expect_rate is not None and info["framerate"] != args.expect_rate:
            checks.append(f"rate {info['framerate']} != expected {args.expect_rate}")
        if args.expect_channels is not None and info["channels"] != args.expect_channels:
            checks.append(f"channels {info['channels']} != expected {args.expect_channels}")
        if args.expect_bits is not None and info["sampwidth_bits"] != args.expect_bits:
            checks.append(f"bits {info['sampwidth_bits']} != expected {args.expect_bits}")

        status = "OK" if not checks else "FAIL"
        print(
            f"{info['path']}: {info['channels']}ch {info['sampwidth_bits']}bit "
            f"{info['framerate']}Hz {info['frames']} frames "
            f"{info['duration_s']:.2f}s  [{status}]"
        )
        for c in checks:
            print(f"    - {c}")
            any_fail = True

    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
