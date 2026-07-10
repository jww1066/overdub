#!/usr/bin/env python3
"""Detect the selected calibration signal (the riser) in capture WAV(s) and judge the pass bar.

Prep piece (b) for the riser on-device capture (doc/prototype-plan.md item 1):
the riser analogue of `detect_calibration_click.py`. For each capture this
matched-filters `SELECTED_CANDIDATE_FACTORY`'s template (onset in the reference
at `SELECTED_MIX_ONSET_S`, mixed there by `mix_calibration_signal.py`) and
reports, per file:

  - the detected onset and detection quality (dB, PSR-style, measured with the
    COMPRESSED-PULSE-WIDTH quality exclusion, not the template length -- a
    pulse-compressed peak is ~1/bandwidth wide no matter how long the template
    is, and a template-length exclusion wipes every competitor and returns inf);
  - the riser's ground-truth offset (detected onset - reference onset), in the
    capture's own sample clock -- the same basis and sign convention as
    `gcc_phat` and the click;
  - the CLICK's ground-truth offset from the same capture (the independent,
    already-validated instrument), and the riser-vs-click delta;
  - the sidecar `stream_offset_ms` when present, and a clip census
    (CLAUDE.md trap (f): census raw captures at intake);
  - the on-device pass bar verdict: quality >= 10 dB AND |riser - click| <= 2 ms.

The <= 2 ms "onset recovery" bar is judged against the click because a real
capture's true onset is unknown (unknown start latency): the click is the
in-basis ground truth Test 2 already validated at ~34 dB quality on this route.
Captures made with a riser-less asset (before the 2026-07-09 asset generation)
score low riser quality -- that is the no-signal signature, not a bug.

If on-device quality reads low, check WHERE the competing peak sits before
re-tuning anything (doc/guides/offline-dsp.md "measure, don't assume"): a
competitor a few ms after the peak is the room's reverb shoulder, a different
condition than a competitor at an unrelated lag -- widen --exclusion-ms only
for the former, and say so in the results doc.

Usage:
    python scripts/detect_calibration_signal.py capture.wav [more.wav ...]
    python scripts/detect_calibration_signal.py --sweep-dir riser_check/
    python scripts/detect_calibration_signal.py capture.wav --max-offset-ms 300
"""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np

from overdub_analysis.calibration_candidates import (
    SELECTED_CANDIDATE_FACTORY,
    SELECTED_MIX_ONSET_S,
    compressed_pulse_exclusion,
    detect_template,
)
from overdub_analysis.calibration_click import PRE_SILENCE_S, detect_click

QUALITY_BAR_DB = 10.0
RECOVERY_BAR_MS = 2.0


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


def signed_window(ref_onset: int, rate: int, max_offset_ms: float) -> tuple[int, int] | None:
    """The SIGNED +/-max_offset_ms search window around the reference onset.

    The harness basis is negative -- the captured WAV's sample 0 precedes
    input-frame 0 -- so the window must admit negative offsets (see
    doc/test2-sweep-results.md 'Calibration click cross-check').
    """
    if max_offset_ms <= 0:
        return None
    half = round(rate * max_offset_ms / 1000.0)
    return (max(0, ref_onset - half), ref_onset + half)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wavs", nargs="*", help="capture WAV file(s)")
    parser.add_argument("--sweep-dir", help="process every *.wav in this directory")
    parser.add_argument(
        "--max-offset-ms",
        type=float,
        default=300.0,
        help="half-width of the signed ground-truth offset search window "
        "(applies to both the riser and the click searches). 0 disables the window",
    )
    parser.add_argument(
        "--exclusion-ms",
        type=float,
        default=None,
        help="override the quality-exclusion half-width in ms (default: the "
        "compressed-pulse width from the template's bandwidth, ~4 ms for the riser)",
    )
    args = parser.parse_args()

    paths = [Path(p) for p in args.wavs]
    if args.sweep_dir:
        paths += sorted(Path(args.sweep_dir).glob("*.wav"))
    if not paths:
        parser.error("no input WAVs (pass files or --sweep-dir)")

    print(
        f"pass bar: quality >= {QUALITY_BAR_DB:.0f} dB and |riser_gt - click_gt| <= "
        f"{RECOVERY_BAR_MS:.0f} ms (the click is the in-basis ground truth)"
    )
    header = (
        f"{'file':<45} {'onset':>8} {'quality_dB':>10} {'gt_offset_ms':>12} "
        f"{'click_gt_ms':>11} {'clickq_dB':>9} {'delta_ms':>8} {'stream_ms':>10} {'clip':>5} {'verdict':>7}"
    )
    print(header)
    for path in paths:
        capture, rate = read_wav_mono_16bit(path)
        clips = int(np.count_nonzero(np.abs(capture) >= 32767.0 / 32768.0))

        spec = SELECTED_CANDIDATE_FACTORY(rate)
        sig_onset_ref = round(rate * SELECTED_MIX_ONSET_S)
        if args.exclusion_ms is not None:
            excl = round(rate * args.exclusion_ms / 1000.0)
        else:
            excl = compressed_pulse_exclusion(spec.template, rate)
        det = detect_template(
            capture,
            spec.template,
            rate,
            search_window=signed_window(sig_onset_ref, rate, args.max_offset_ms),
            quality_exclusion=excl,
        )
        gt_ms = 1000.0 * (det.onset_sample - sig_onset_ref) / rate

        click_onset_ref = round(rate * PRE_SILENCE_S)
        click_det = detect_click(
            capture, rate, search_window=signed_window(click_onset_ref, rate, args.max_offset_ms)
        )
        click_gt_ms = 1000.0 * (click_det.onset_sample - click_onset_ref) / rate
        delta_ms = gt_ms - click_gt_ms

        stream_ms = sidecar_stream_offset_ms(path)
        stream_str = f"{stream_ms:10.2f}" if stream_ms is not None else f"{'-':>10}"
        # The <= 2 ms bar is only meaningful if the click (the ground-truth
        # instrument) itself detected confidently in this capture.
        verdict = (
            "PASS"
            if det.quality_db >= QUALITY_BAR_DB
            and abs(delta_ms) <= RECOVERY_BAR_MS
            and click_det.quality_db >= QUALITY_BAR_DB
            else "FAIL"
        )
        print(
            f"{path.name:<45} {det.onset_sample:>8} {det.quality_db:>10.1f} {gt_ms:>12.2f} "
            f"{click_gt_ms:>11.2f} {click_det.quality_db:>9.1f} {delta_ms:>8.2f} "
            f"{stream_str} {clips:>5} {verdict:>7}"
        )
    print(
        f"(signal = {SELECTED_CANDIDATE_FACTORY().name}; reference onset {SELECTED_MIX_ONSET_S:.3f}s; "
        f"quality exclusion {'overridden' if args.exclusion_ms is not None else 'compressed-pulse'} "
        f"= {excl} samples at the last file's rate; a verdict also requires clickq >= "
        f"{QUALITY_BAR_DB:.0f} dB -- with a low-quality click, delta_ms has no ground truth)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
