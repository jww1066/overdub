#!/usr/bin/env python3
"""Mix the selected calibration signal (the log-sweep riser) into the reference asset.

Prep piece (a) for the riser on-device capture (doc/prototype-plan.md item 1):
takes the click-bearing reference (output of `prepend_calibration_click.py`) and
additively mixes `SELECTED_CANDIDATE_FACTORY`'s template at the known onset
`SELECTED_MIX_ONSET_S` (0.550 s) inside the 1.0 s lead-in's post-click silence.
Both ground-truth instruments then land in every capture: the already-validated
click (the in-basis truth) and the riser under test, so the on-device pass bar
(>= 10 dB detection quality, <= 2 ms onset recovery vs the click) is judged by
`detect_calibration_signal.py` on one capture.

Placement inside the existing lead-in (not appended to it) keeps every analysis
that trims LEAD_IN_S valid without change; the mix function's silence guard
makes running this twice, or on a click-less asset, a hard error. Shape and
placement live in `overdub_analysis.calibration_candidates`
(SELECTED_CANDIDATE_FACTORY / SELECTED_MIX_ONSET_S -- the single source of
truth shared with the detector); this script only does WAV I/O around it, then
re-detects both the riser and the click in its own output as a round-trip
self-check before declaring success.

Usage:
    python scripts/mix_calibration_signal.py in.wav out.wav [--expect-rate 48000]

(in.wav and out.wav may be the same path: the input is fully read before the
output is written.)
"""

from __future__ import annotations

import argparse
import wave

import numpy as np

from overdub_analysis.calibration_candidates import (
    SELECTED_CANDIDATE_FACTORY,
    compressed_pulse_exclusion,
    detect_template,
    mix_into_click_lead_in,
)
from overdub_analysis.calibration_click import PRE_SILENCE_S, detect_click


def read_wav_mono_16bit(path: str) -> tuple[np.ndarray, int]:
    with wave.open(path, "rb") as w:
        channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    if channels != 1:
        raise ValueError(f"{path}: expected mono, got {channels} channels")
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


def clip_census(samples: np.ndarray) -> int:
    """Count full-scale samples (|x| at the int16 rails) -- CLAUDE.md trap (f)."""
    return int(np.count_nonzero(np.abs(samples) >= 32767.0 / 32768.0))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="click-bearing reference WAV (prepend_calibration_click.py output)")
    parser.add_argument("output", help="destination WAV (the harness asset)")
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

    clips_in = clip_census(data)
    spec = SELECTED_CANDIDATE_FACTORY(rate)
    result = mix_into_click_lead_in(data, rate, spec=spec)
    write_wav_mono_16bit(args.output, result.samples, rate)

    # Round-trip self-check: re-read the written file, re-detect BOTH
    # instruments (the riser just mixed, and the click that must survive it).
    written, _ = read_wav_mono_16bit(args.output)
    excl = compressed_pulse_exclusion(spec.template, rate)
    half = round(rate * 0.090)  # the +/-90 ms anchored product window
    sig_det = detect_template(
        written,
        spec.template,
        rate,
        search_window=(result.signal_onset_sample - half, result.signal_onset_sample + half),
        quality_exclusion=excl,
    )
    if sig_det.onset_sample != result.signal_onset_sample:
        raise SystemExit(
            f"ERROR: self-check failed -- detected {spec.name} onset {sig_det.onset_sample}, "
            f"expected {result.signal_onset_sample}"
        )
    click_det = detect_click(written, rate)
    click_expected = round(rate * PRE_SILENCE_S)
    if click_det.onset_sample != click_expected:
        raise SystemExit(
            f"ERROR: self-check failed -- click onset {click_det.onset_sample} after mix, "
            f"expected {click_expected}"
        )
    clips_out = clip_census(written)
    if clips_out > clips_in:
        raise SystemExit(
            f"ERROR: mix added clipped samples ({clips_in} -> {clips_out})"
        )

    n = result.samples.size
    print(f"wrote {args.output}: mono 16bit {rate}Hz {n} frames {n / rate:.2f}s")
    print(
        f"{result.signal_name} onset = sample {result.signal_onset_sample} "
        f"({result.signal_onset_sample / rate:.3f}s), length {result.signal_length} samples "
        f"({result.signal_length / rate:.3f}s); click onset = sample {click_expected}; "
        f"content still starts at 1.000s"
    )
    print(
        f"self-check: {result.signal_name} re-detected at sample {sig_det.onset_sample}, "
        f"quality {sig_det.quality_db:.1f} dB (exclusion {excl} samples); "
        f"click re-detected at sample {click_det.onset_sample}, quality {click_det.quality_db:.1f} dB"
    )
    print(f"clip census: input {clips_in}, output {clips_out} full-scale samples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
