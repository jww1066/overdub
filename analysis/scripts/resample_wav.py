#!/usr/bin/env python3
"""Resample a WAV to a target sample rate (and optionally downmix to mono / force 16-bit).

The harness warns but does NOT resample a reference track whose rate differs from the
device's native output rate (test2-step2-plan.md Components Sec 1) -- a 44.1kHz file
played through a 48kHz stream silently confounds the sweep. Use this to convert an
arbitrary source recording (e.g. boots.wav at 44100 Hz) into the 48000 Hz / mono /
16-bit PCM WAV the harness expects before bundling it as reference_track.wav.

Resampling is rational (scipy.signal.resample_poly with an anti-alias FIR): for
44100 -> 48000 the ratio reduces exactly to 160/147, so there is no fractional-rate
error. Requires scipy; if it's not in the analysis venv, `pip install -e ".[dev]"`
per CLAUDE.md's Python-tooling note.

Usage:
    python scripts/resample_wav.py ../boots.wav out.wav --rate 48000 --mono
    python scripts/resample_wav.py in.wav out.wav --rate 48000 --mono --bits 16
"""

from __future__ import annotations

import argparse
import wave
from math import gcd

import numpy as np
from scipy.signal import resample_poly


def read_wav(path: str) -> tuple[np.ndarray, int]:
    """Return (float64 samples in [-1, 1], framerate). Shape is (frames,) or (frames, channels)."""
    with wave.open(path, "rb") as w:
        channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        framerate = w.getframerate()
        raw = w.readframes(w.getnframes())

    if sampwidth != 2:
        raise ValueError(f"{path}: only 16-bit PCM input is supported (got {sampwidth * 8}-bit)")
    data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels)
    return data, framerate


def write_wav_16bit(path: str, samples: np.ndarray, framerate: int) -> None:
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = np.round(clipped * 32767.0).astype("<i2")
    channels = 1 if pcm.ndim == 1 else pcm.shape[1]
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(framerate)
        w.writeframes(pcm.tobytes())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="source WAV")
    parser.add_argument("output", help="destination WAV")
    parser.add_argument("--rate", type=int, required=True, help="target sample rate (Hz)")
    parser.add_argument("--mono", action="store_true", help="downmix to mono (average channels)")
    parser.add_argument("--bits", type=int, default=16, choices=[16], help="output bit depth (16 only)")
    args = parser.parse_args()

    data, src_rate = read_wav(args.input)

    if args.mono and data.ndim == 2:
        data = data.mean(axis=1)
    elif data.ndim == 2 and data.shape[1] > 1:
        print(f"note: input is {data.shape[1]}-channel and --mono not set; resampling each channel")

    if src_rate == args.rate:
        print(f"input already at {args.rate} Hz; copying with no rate change")
        out = data
    else:
        g = gcd(args.rate, src_rate)
        up, down = args.rate // g, src_rate // g
        # resample_poly works along axis 0, which is the frame axis for both shapes here.
        out = resample_poly(data, up, down, axis=0)
        print(f"resampled {src_rate} -> {args.rate} Hz (rational {up}/{down})")

    write_wav_16bit(args.output, out, args.rate)
    frames = out.shape[0]
    ch = 1 if out.ndim == 1 else out.shape[1]
    print(f"wrote {args.output}: {ch}ch 16bit {args.rate}Hz {frames} frames {frames / args.rate:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
