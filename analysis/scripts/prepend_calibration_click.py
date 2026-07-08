#!/usr/bin/env python3
"""Prepend the calibration click lead-in to a mono 16-bit WAV.

Step in the reference-track pipeline (doc/test2-step2-plan.md item 11):
after `resample_wav.py` brings the source recording to the device's native
rate, this prepends the exactly-known 1.000 s calibration lead-in
(0.200 s silence + 20 ms 500-4000 Hz chirp + 0.780 s silence) so every
capture carries an in-basis ground-truth marker for the +/-2 ms offset bar.

The click's shape/placement live in `overdub_analysis.calibration_click`
(single source of truth shared with the detector); this script only does WAV
I/O around it, then re-detects the click in its own output as a round-trip
self-check before declaring success.

NOTE: captures made with the click-less asset must be analyzed against a
click-less reference (regenerate with resample_wav.py alone) -- against the
click version their offsets shift by the whole lead-in.

Usage:
    python scripts/prepend_calibration_click.py in.wav out.wav [--expect-rate 48000]
"""

from __future__ import annotations

import argparse
import wave

import numpy as np

from overdub_analysis.calibration_click import detect_click, prepend_click


def read_wav_mono_16bit(path: str) -> tuple[np.ndarray, int]:
    with wave.open(path, "rb") as w:
        channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    if channels != 1:
        raise ValueError(f"{path}: expected mono, got {channels} channels (run resample_wav.py --mono first)")
    if sampwidth != 2:
        raise ValueError(f"{path}: expected 16-bit PCM, got {sampwidth * 8}-bit")
    data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    return data, rate


def write_wav_mono_16bit(path: str, samples: np.ndarray, rate: int) -> None:
    pcm = np.round(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="source WAV (mono 16-bit, already at the target rate)")
    parser.add_argument("output", help="destination WAV")
    parser.add_argument(
        "--expect-rate",
        type=int,
        default=None,
        help="fail unless the input is at this rate (guards against skipping resample_wav.py)",
    )
    args = parser.parse_args()

    data, rate = read_wav_mono_16bit(args.input)
    if args.expect_rate is not None and rate != args.expect_rate:
        raise SystemExit(f"ERROR: {args.input} is {rate} Hz, expected {args.expect_rate} Hz")

    result = prepend_click(data, rate)
    write_wav_mono_16bit(args.output, result.samples, rate)

    # Round-trip self-check: re-read the written file and re-detect the click.
    written, _ = read_wav_mono_16bit(args.output)
    det = detect_click(written, rate)
    if det.onset_sample != result.click_onset_sample:
        raise SystemExit(
            f"ERROR: self-check failed -- detected click onset {det.onset_sample}, "
            f"expected {result.click_onset_sample}"
        )

    n = result.samples.size
    print(f"wrote {args.output}: mono 16bit {rate}Hz {n} frames {n / rate:.2f}s")
    print(
        f"click onset = sample {result.click_onset_sample} "
        f"({result.click_onset_sample / rate:.3f}s); "
        f"lead-in = {result.lead_in_samples} samples ({result.lead_in_samples / rate:.3f}s); "
        f"original content starts at sample {result.lead_in_samples}"
    )
    print(f"self-check: click re-detected at sample {det.onset_sample}, quality {det.quality_db:.1f} dB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
