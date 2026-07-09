#!/usr/bin/env python3
"""Re-measure the synthetic SNR floor with the band-limited pipeline + real reference.

Test 2 step 1's original floor (`sweep_snr_floor.py`) was measured on a
broadband click train with full-band GCC-PHAT gated on PSR — a floor of
~-30 dB SNR that did NOT transfer to the real signal chain (the real sweep
failed 0/36 full-band, and PSR was later demoted entirely; see
doc/test2-sweep-results.md). This script is the honest re-measurement folded
into Test 2 step 3 (doc/test2-step2-plan.md item 12): the *production-shaped*
pipeline — the real click-bearing beatbox reference, the 500-4000 Hz
band-limited GCC-PHAT, the click-anchored +/-90 ms lag window, and the
|gcc - click| <= 2 ms gate of `run_click_gated_sweep.py` — against a
synthetic capture (known injected delay) with white noise swept downward in
**in-band** SNR (noise measured where the correlator looks, consistent with
the vocal study's in-band ratio convention).

Two distinct floors fall out, mirroring the vocal study's finding that the
anchor and the correlator fail separately:

  * the **click floor** — the SNR below which the calibration click's
    matched-filter quality drops under the 10 dB trust floor (anchor lost,
    verdict `no-click`), or its detected onset goes wrong;
  * the **gate floor** — the SNR below which the click still anchors but the
    anchored GCC-PHAT offset leaves the +/-2 ms bar.

Both are *outputs* of the measurement, not thresholds to hit.

SNR definition: in-band signal RMS over the beatbox-content region of the
clean delayed capture (the lead-in is mostly silence and would dilute it)
divided by in-band noise RMS, in dB. The equivalent broadband white-noise SNR
is a fixed offset from the in-band number and is printed once in the header.

Usage (from analysis/ via the venv per CLAUDE.md):
    .venv/Scripts/python.exe scripts/sweep_snr_floor_real_reference.py
    .venv/Scripts/python.exe scripts/sweep_snr_floor_real_reference.py \\
        --delay-ms -80 --from 30 --to -36 --step -3 --seeds 3
"""

from __future__ import annotations

import argparse
import csv
import wave
from pathlib import Path

import numpy as np

from overdub_analysis.calibration_click import PRE_SILENCE_S, LEAD_IN_S, detect_click
from overdub_analysis.gcc_phat import gcc_phat
from overdub_analysis.synth import delay
from overdub_analysis.vocal_inject import bandpass, inband_rms

_CLICK_QUALITY_FLOOR_DB = 10.0


def _read_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    if sampwidth != 2:
        raise ValueError(f"{path}: only 16-bit PCM is supported (got {sampwidth * 8}-bit)")
    data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="../harness/src/main/assets/reference_track.wav")
    parser.add_argument(
        "--delay-ms",
        type=float,
        default=-80.0,
        help="injected delay of the synthetic capture vs the reference (ms); the "
        "default mirrors the measured harness-basis offset (~-80 ms, negative)",
    )
    parser.add_argument("--from", dest="snr_hi", type=float, default=30.0, help="start in-band SNR (dB)")
    parser.add_argument("--to", dest="snr_lo", type=float, default=-36.0, help="end in-band SNR (dB)")
    parser.add_argument("--step", type=float, default=-3.0, help="SNR step (dB, negative)")
    parser.add_argument("--seeds", type=int, default=3, help="independent noise seeds per SNR point")
    parser.add_argument("--lo", type=float, default=500.0, help="analysis band low edge (Hz)")
    parser.add_argument("--hi", type=float, default=4000.0, help="analysis band high edge (Hz)")
    parser.add_argument(
        "--max-offset-ms",
        type=float,
        default=300.0,
        help="half-width of the SIGNED click search window (matches run_click_gated_sweep.py)",
    )
    parser.add_argument(
        "--anchor-half-width-ms",
        type=float,
        default=90.0,
        help="click-anchored GCC-PHAT lag-window half-width (< half the ~187 ms beat period)",
    )
    parser.add_argument("--tolerance-ms", type=float, default=2.0, help="the +/-2 ms pass bar")
    parser.add_argument("--output-csv", default="sweep_data/snr_floor_real_reference.csv")
    args = parser.parse_args()

    if args.step >= 0:
        parser.error("--step must be negative to sweep downward")

    ref, rate = _read_wav_mono(Path(args.reference))
    ref_bp = bandpass(ref, args.lo, args.hi, rate)
    click_onset_ref = round(rate * PRE_SILENCE_S)
    lead_in = round(rate * LEAD_IN_S)
    wide = int(args.max_offset_ms * 1e-3 * rate)
    anchor_hw = int(args.anchor_half_width_ms * 1e-3 * rate)

    d = int(round(args.delay_ms * 1e-3 * rate))
    clean = delay(ref, d)

    # In-band signal RMS over the beatbox-content region only (lead-in is
    # mostly silence; including it would dilute the SNR definition).
    content_start = max(0, lead_in + d)
    sig_inband = inband_rms(clean[content_start:], rate, args.lo, args.hi)
    sig_broad = float(np.sqrt(np.mean(clean[content_start:] ** 2)))

    snrs = np.arange(args.snr_hi, args.snr_lo - 1e-9, args.step)
    truth_ms = 1000.0 * d / rate

    # White noise: in-band and broadband RMS per unit scale, measured (not
    # assumed from the bandwidth fraction), so the broadband-equivalent SNR
    # offset in the header is honest.
    probe = np.random.default_rng(0).standard_normal(clean.size)
    unit_inband = inband_rms(probe, rate, args.lo, args.hi)
    unit_broad = float(np.sqrt(np.mean(probe**2)))
    broadband_offset_db = 20.0 * np.log10((sig_broad / unit_broad) / (sig_inband / unit_inband))

    print(f"reference: {args.reference}  {ref.size} samples  {rate} Hz")
    print(f"injected delay: {truth_ms:+.2f} ms ({d:+d} samples)")
    print(f"band: {args.lo:.0f}-{args.hi:.0f} Hz  gate: click-anchored "
          f"+/-{args.anchor_half_width_ms:.0f} ms window, |gcc - click| <= {args.tolerance_ms} ms, "
          f"click quality floor {_CLICK_QUALITY_FLOOR_DB:.0f} dB")
    print(f"SNR is IN-BAND (signal = beatbox content region); broadband white-noise "
          f"equivalent = in-band {broadband_offset_db:+.1f} dB")
    print()
    print(f"{'inband_snr_db':>13} {'seed':>4} {'click_q_db':>10} {'click_err_ms':>12} "
          f"{'gcc_err_ms':>10} {'gcc_vs_truth_ms':>15}  verdict")

    rows = []
    click_floor: dict[int, float | None] = {}
    gate_floor: dict[int, float | None] = {}
    for seed in range(args.seeds):
        noise_unit = np.random.default_rng(seed).standard_normal(clean.size)
        click_floor[seed] = None
        gate_floor[seed] = None
        for snr in snrs:
            scale = sig_inband / (unit_inband * 10.0 ** (float(snr) / 20.0))
            mix = clean + scale * noise_unit

            det = detect_click(
                mix, rate,
                search_window=(max(0, click_onset_ref - wide), click_onset_ref + wide),
            )
            click_samples = det.onset_sample - click_onset_ref
            click_ms = 1000.0 * click_samples / rate
            click_err_ms = click_ms - truth_ms

            row = {
                "inband_snr_db": f"{snr:.1f}",
                "seed": seed,
                "click_quality_db": f"{det.quality_db:.1f}",
                "click_err_ms": f"{click_err_ms:.2f}",
                "gcc_err_ms": "",
                "gcc_vs_truth_ms": "",
                "verdict": "no-click",
            }
            click_ok = (
                det.quality_db >= _CLICK_QUALITY_FLOOR_DB
                and abs(click_err_ms) <= args.tolerance_ms
            )
            if det.quality_db >= _CLICK_QUALITY_FLOOR_DB:
                mix_bp = bandpass(mix, args.lo, args.hi, rate)
                r = gcc_phat(
                    ref_bp, mix_bp, fs=rate,
                    lag_window=(click_samples - anchor_hw, click_samples + anchor_hw),
                )
                gcc_ms = (r.offset_seconds or 0.0) * 1000.0
                err_ms = gcc_ms - click_ms
                row["gcc_err_ms"] = f"{err_ms:.2f}"
                row["gcc_vs_truth_ms"] = f"{gcc_ms - truth_ms:.2f}"
                row["verdict"] = "PASS" if abs(err_ms) <= args.tolerance_ms else "FAIL"
                # An anchored gate that "passes" against a WRONG click onset is
                # not a pass — the anchor itself has left the truth.
                if row["verdict"] == "PASS" and abs(click_err_ms) > args.tolerance_ms:
                    row["verdict"] = "click-wrong"
            if not click_ok and click_floor[seed] is None:
                click_floor[seed] = float(snr)
            if click_ok and row["verdict"] != "PASS" and gate_floor[seed] is None:
                gate_floor[seed] = float(snr)

            print(f"{row['inband_snr_db']:>13} {seed:>4} {row['click_quality_db']:>10} "
                  f"{row['click_err_ms']:>12} {row['gcc_err_ms']:>10} "
                  f"{row['gcc_vs_truth_ms']:>15}  {row['verdict']}")
            rows.append(row)

    print()
    for seed in range(args.seeds):
        cf = click_floor[seed]
        gf = gate_floor[seed]
        print(f"seed {seed}: click floor (anchor lost/wrong) at "
              f"{'never' if cf is None else f'{cf:.1f} dB'}; "
              f"gate floor (click OK, gcc off) at "
              f"{'never' if gf is None else f'{gf:.1f} dB'}")

    out_path = Path(args.output_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSV: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
