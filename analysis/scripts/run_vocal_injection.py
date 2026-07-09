#!/usr/bin/env python3
"""Vocal-interference injection sweep (doc/test2-step2-plan.md item 12).

The Session A sweep measured bleed alignment against a quiet room; production
correlates through a loud vocal sitting in the 500-4000 Hz analysis band. This
mixes a dry close-mic vocal take (harness/scripts/run_vocal_take.sh) into each
click-bearing Session A capture at a swept *in-band* vocal-to-bleed ratio and
re-judges the click gate (|gcc_phat - click| <= 2 ms -- the same honest gate as
run_click_gated_sweep.py, NOT PSR) on the mix, to find where the vocal starts
pulling the alignment off the bleed peak.

The vocal is placed at its performed timing in the capture (the in-time / worst
case): shift = tau_v - tau_c, where tau_v is the vocal's whole-take GCC-PHAT lag
vs the reference and tau_c is the capture's click ground-truth offset
(overdub_analysis.vocal_inject.vocal_placement_samples). The ratio is the
primary variable; the placement is approximate (tau_v is tempo-correlated but
segment-unstable, per leak_detect) and defaults to that best-guess in-time lag.

The click is detected IN THE MIX (not the raw capture): a production capture IS
the mix, so if the vocal ever destroyed the click anchor the gate must say so
(a "no-click" row is a real finding, not a bug). The click sits at the capture
start (~0.12 s) and the vocal is placed later (~0.2 s+), so the anchor normally
survives -- but that is verified, not assumed.

A control row (ratio "none") judges the raw capture first, reproducing the
Session A result; a vocal that degrades it is the study's signal.

The mix is NORMALIZED to peak ~-0.4 dBFS before gating. The in-band ratio is
what the study varies; absolute level is a nuisance -- and a linear sum of two
int16 signals can hit the rail even at low ratios (the captures themselves sit
at the int16 rail), which would be a simulation artifact, not a physical
prediction. Normalization is free: the click matched-filter quality and GCC-PHAT
are both scale-invariant, so the verdicts are unaffected. The achieved in-band
ratio is computed from the un-normalized mix (vs the raw capture's bleed) BEFORE
normalizing, so the ratio column stays honest.

Usage (from analysis/ via the venv):
    .venv/Scripts/python.exe scripts/run_vocal_injection.py \\
        --sweep-dir recapture_session_a \\
        --vocal vocal_take/vocal_take_1783545380726.wav \\
        --reference ../harness/src/main/assets/reference_track.wav

Writes a CSV (default <sweep-dir>/vocal_injection_results.csv) and prints a
per-capture x ratio table. Exit code is non-zero if no captures are found.
"""

from __future__ import annotations

import argparse
import csv
import json
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, filtfilt

from overdub_analysis.calibration_click import PRE_SILENCE_S, detect_click
from overdub_analysis.gcc_phat import gcc_phat
from overdub_analysis.vocal_inject import (
    bandpass,
    inband_rms,
    mix_at_inband_ratio,
    vocal_placement_samples,
)

# Same floor as run_click_gated_sweep.py: below this the click is "absent".
_CLICK_QUALITY_FLOOR_DB = 10.0
# Default in-band ratio sweep (dB) around the measured -12.2 dB pin.
_DEFAULT_RATIOS_DB = [-24.0, -18.0, -12.0, -6.0, 0.0, 6.0]
# Mix is normalized to this fraction of full scale before gating (see module docstring).
_NORM_PEAK_FRAC = 0.95


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.astype(np.float64), rate


def _gate(
    ref_bp: np.ndarray,
    mix: np.ndarray,
    rate: int,
    click_onset_ref: int,
    wide: int,
    anchor_hw: int,
    lo: float,
    hi: float,
    psr_exclusion: int,
    tolerance_ms: float,
) -> dict:
    """Run the click-anchored gate on ``mix``. Mirrors run_click_gated_sweep.py."""
    det = detect_click(
        mix, rate, search_window=(max(0, click_onset_ref - wide), click_onset_ref + wide)
    )
    click_samples = det.onset_sample - click_onset_ref
    click_ms = 1000.0 * click_samples / rate
    row = {
        "click_offset_ms": f"{click_ms:.2f}",
        "click_quality_db": f"{det.quality_db:.1f}",
        "gcc_offset_ms": "",
        "err_ms": "",
        "verdict": "no-click",
        "psr_db_diag": "",
    }
    if det.quality_db >= _CLICK_QUALITY_FLOOR_DB:
        r = gcc_phat(
            ref_bp,
            bandpass(mix, lo, hi, rate),
            fs=rate,
            psr_exclusion=psr_exclusion,
            lag_window=(click_samples - anchor_hw, click_samples + anchor_hw),
        )
        gcc_ms = (r.offset_seconds or 0.0) * 1000.0
        err_ms = gcc_ms - click_ms
        row.update({
            "gcc_offset_ms": f"{gcc_ms:.2f}",
            "err_ms": f"{err_ms:.2f}",
            "verdict": "PASS" if abs(err_ms) <= tolerance_ms else "FAIL",
            "psr_db_diag": f"{r.psr_db:.1f}",
        })
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sweep-dir", required=True, help="dir of click-bearing captures (WAV+JSON)")
    parser.add_argument("--vocal", required=True, help="dry close-mic vocal take WAV")
    parser.add_argument("--reference", default="../harness/src/main/assets/reference_track.wav")
    parser.add_argument("--ratios", type=float, nargs="*", default=_DEFAULT_RATIOS_DB,
                        help="in-band vocal-to-bleed ratios to sweep (dB); default around the -12.2 dB pin")
    parser.add_argument("--lo", type=float, default=500.0)
    parser.add_argument("--hi", type=float, default=4000.0)
    parser.add_argument("--max-offset-ms", type=float, default=300.0)
    parser.add_argument("--anchor-half-width-ms", type=float, default=90.0)
    parser.add_argument("--tolerance-ms", type=float, default=2.0)
    parser.add_argument("--psr-exclusion", type=int, default=16)
    parser.add_argument("--output-csv", default=None)
    args = parser.parse_args()

    sweep_dir = Path(args.sweep_dir)
    output_csv = Path(args.output_csv) if args.output_csv else sweep_dir / "vocal_injection_results.csv"
    wav_paths = sorted(sweep_dir.glob("*.wav"))
    if not wav_paths:
        print(f"no .wav files found in {sweep_dir}")
        return 1

    ref, ref_rate = _read_wav(Path(args.reference))
    ref_bp = bandpass(ref, args.lo, args.hi, ref_rate)
    vocal, voc_rate = _read_wav(Path(args.vocal))
    if voc_rate != ref_rate:
        print(f"vocal rate {voc_rate} != reference {ref_rate}; resample first")
        return 1
    voc_bp = bandpass(vocal, args.lo, args.hi, voc_rate)
    click_onset_ref = round(ref_rate * PRE_SILENCE_S)
    wide = int(args.max_offset_ms * 1e-3 * ref_rate)
    anchor_hw = int(args.anchor_half_width_ms * 1e-3 * ref_rate)

    vocal_inband = inband_rms(vocal, voc_rate, args.lo, args.hi)
    print(f"reference: {len(ref)} samples {ref_rate} Hz; vocal: {len(vocal)} samples, "
          f"in-band RMS {vocal_inband:.1f}")
    print(f"band: {args.lo:.0f}-{args.hi:.0f} Hz; ratios (dB in-band): control + {args.ratios}")
    print(f"gate: |gcc_phat - click| <= {args.tolerance_ms} ms in a click-anchored "
          f"+/-{args.anchor_half_width_ms:.0f} ms window (PSR diagnostic-only)")
    print()

    rows = []
    for wav_path in wav_paths:
        capture, rate = _read_wav(wav_path)
        if rate != ref_rate:
            print(f"  WARN {wav_path.name}: rate {rate} != ref {ref_rate}")
        json_path = wav_path.with_suffix(".json")
        meta = json.loads(json_path.read_text()) if json_path.exists() else {}
        cond = meta.get("condition_id", wav_path.stem)
        bleed_inband = inband_rms(capture, rate, args.lo, args.hi)

        # Control: the raw capture (no vocal). Reproduces the Session A verdict.
        ctrl = _gate(ref_bp, capture, rate, click_onset_ref, wide, anchor_hw,
                     args.lo, args.hi, args.psr_exclusion, args.tolerance_ms)
        ctrl_row = {"condition_id": cond, "ratio_db": "none",
                    "achieved_ratio_db": "ref",
                    "wav_file": wav_path.name, **ctrl}
        rows.append(ctrl_row)

        # Placement: the vocal's in-time offset in THIS capture's clock (once per capture).
        det_raw = detect_click(capture, rate,
                               search_window=(max(0, click_onset_ref - wide), click_onset_ref + wide))
        tau_c = det_raw.onset_sample - click_onset_ref
        shift = vocal_placement_samples(ref_bp, voc_bp, rate, tau_c)

        for ratio_db in args.ratios:
            mix = mix_at_inband_ratio(capture, vocal, rate, ratio_db,
                                      lo=args.lo, hi=args.hi, placement_samples=shift)
            # Sanity: the in-band ratio the mix actually achieved (vs the raw bleed),
            # measured from the UN-normalized mix before normalization (below).
            mix_bleed_inband = inband_rms(mix, rate, args.lo, args.hi)
            vocal_in_mix = np.sqrt(max(mix_bleed_inband**2 - bleed_inband**2, 0.0))
            achieved_db = 20 * np.log10(vocal_in_mix / bleed_inband) if bleed_inband > 0 else float("nan")
            # Normalize to a safe peak so a rail-clipping artifact of the linear int16
            # sum can't confound the gate (scale-invariant, so verdicts are unaffected).
            peak = float(np.max(np.abs(mix)))
            if peak > 0:
                mix = mix * (_NORM_PEAK_FRAC * 32767.0 / peak)
            gated = _gate(ref_bp, mix, rate, click_onset_ref, wide, anchor_hw,
                          args.lo, args.hi, args.psr_exclusion, args.tolerance_ms)
            rows.append({
                "condition_id": cond,
                "ratio_db": f"{ratio_db:.0f}",
                "achieved_ratio_db": f"{achieved_db:+.1f}" if not np.isnan(achieved_db) else "",
                "wav_file": wav_path.name,
                **gated,
            })

    fields = ["condition_id", "ratio_db", "achieved_ratio_db",
              "click_offset_ms", "click_quality_db", "gcc_offset_ms", "err_ms",
              "verdict", "psr_db_diag", "wav_file"]
    with output_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"CSV: {output_csv}")

    # Per-capture summary: control verdict + the ratio at which it first fails.
    print()
    print(f"{'condition_id':<38} {'control':<8} {'first_fail_ratio':<18} {'max_pass_ratio':<16}")
    print("-" * 90)
    seen = set()
    for r in rows:
        cond = r["condition_id"]
        if cond in seen:
            continue
        seen.add(cond)
        crows = [x for x in rows if x["condition_id"] == cond]
        ctrl = next(x for x in crows if x["ratio_db"] == "none")
        injected = [x for x in crows if x["ratio_db"] != "none"]
        first_fail = next((x["ratio_db"] for x in injected if x["verdict"] == "FAIL"), "none")
        max_pass = max((float(x["ratio_db"]) for x in injected if x["verdict"] == "PASS"), default=None)
        max_pass_s = f"{max_pass:+.0f} dB" if max_pass is not None else "none"
        print(f"{cond:<38} {ctrl['verdict']:<8} {first_fail:<18} {max_pass_s:<16}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
