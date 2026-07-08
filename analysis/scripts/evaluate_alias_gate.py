#!/usr/bin/env python3
"""Decide the beat-period-alias remedy for the GCC-PHAT sweep gate (item 11a).

The calibration-click cross-check (doc/test2-sweep-results.md, 2026-07-08) showed the
band-limited GCC-PHAT locking onto a +187 ms beat-period alias of the reference instead
of the true (negative, harness-basis) alignment peak, with PSR and the (0, 300 ms)
positivity lag window both blessing the alias. Before the 36-cell re-capture sweep is
run, the sweep pipeline needs to know WHICH remedy actually rejects the alias:

  A. **Signed wide window** (-300..+300 ms): works only if, once negative offsets are
     admitted, the true peak genuinely outranks the alias peak in the correlation.
  B. **Anchored narrow window** (center +/- half-width < half the beat period): works
     regardless of which peak is globally larger, because the alias is excluded by
     construction. Two anchors are tested:
       - click-anchored (the harness's ground truth -- validation instrument), and
       - stream-timestamp-anchored (the sidecar's getTimestamp-derived
         `stream_offset_ms` -- the PRODUCT-shaped anchor, available with no click).

For each click-bearing capture this script reports, side by side:
  - the matched-filter click ground truth (offset + detection quality),
  - band-limited GCC-PHAT under each candidate window (offset, PSR, error vs click,
    PASS/FAIL against the +/-2 ms bar),
  - a trimmed variant (both signals cut past the 1.0 s lead-in, per
    reference_track_README.md's equal-trim rule) to check whether the chirp's own
    correlated energy is what makes or breaks the signed-window variant,
  - the top competing peaks of the raw band-limited correlation inside the signed
    window (via `gcc_phat_correlation`), so "the alias peak is genuinely larger by
    X dB" is a measured number, not an inference from argmax behavior.

Usage (from analysis/ via the venv per CLAUDE.md):
    .venv/Scripts/python.exe scripts/evaluate_alias_gate.py --sweep-dir click_check
    .venv/Scripts/python.exe scripts/evaluate_alias_gate.py capture.wav --tolerance-ms 2
"""

from __future__ import annotations

import argparse
import json
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.signal import butter, filtfilt, find_peaks

from overdub_analysis.calibration_click import LEAD_IN_S, PRE_SILENCE_S, detect_click
from overdub_analysis.gcc_phat import gcc_phat, gcc_phat_correlation

_PSR_MINIMUM_DB = 6.0
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


def _bandpass(x: np.ndarray, lo: float, hi: float, fs: int) -> np.ndarray:
    """Zero-phase 4th-order Butterworth bandpass (filtfilt: no group-delay offset)."""
    nyq = 0.5 * fs
    b, a = butter(4, [lo / nyq, hi / nyq], btype="band")
    return filtfilt(b, a, x)


def _sidecar_stream_offset_ms(wav_path: Path) -> float | None:
    sidecar = wav_path.with_suffix(".json")
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text()).get("stream_offset_ms")
    except (json.JSONDecodeError, OSError):
        return None


@dataclass(frozen=True)
class VariantResult:
    name: str
    offset_ms: float
    psr_db: float
    err_ms: float
    passed: bool


def _run_variant(
    name: str,
    ref_bp: np.ndarray,
    cap_bp: np.ndarray,
    rate: int,
    lag_window: tuple[int | None, int | None] | None,
    gt_ms: float,
    tolerance_ms: float,
) -> VariantResult:
    r = gcc_phat(ref_bp, cap_bp, fs=rate, lag_window=lag_window)
    offset_ms = (r.offset_seconds or 0.0) * 1000.0
    err_ms = offset_ms - gt_ms
    return VariantResult(
        name=name,
        offset_ms=offset_ms,
        psr_db=r.psr_db,
        err_ms=err_ms,
        passed=abs(err_ms) <= tolerance_ms,
    )


def _competing_peaks(
    ref_bp: np.ndarray,
    cap_bp: np.ndarray,
    rate: int,
    window_ms: float,
    top_k: int,
    min_separation_ms: float,
) -> list[tuple[float, float]]:
    """Top-k peaks of the raw band-limited GCC inside +/-window_ms.

    Returns (offset_ms, level_db_re_top) tuples, strongest first.
    """
    gcc, offset_all = gcc_phat_correlation(ref_bp, cap_bp)
    bound = int(window_ms * 1e-3 * rate)
    sel = np.abs(offset_all) <= bound
    order = np.argsort(offset_all[sel])
    offs = offset_all[sel][order]
    vals = gcc[sel][order]
    distance = max(1, int(min_separation_ms * 1e-3 * rate))
    idx, _ = find_peaks(vals, distance=distance)
    if idx.size == 0:
        return []
    ranked = idx[np.argsort(vals[idx])[::-1]][:top_k]
    top_val = float(vals[ranked[0]])
    return [
        (1000.0 * float(offs[i]) / rate, 20.0 * float(np.log10(vals[i] / top_val)))
        for i in ranked
    ]


def _peak_shape(
    ref_bp: np.ndarray,
    cap_bp: np.ndarray,
    rate: int,
    center_offset_samples: int,
    span: int,
) -> list[tuple[int, float]]:
    """Correlation magnitude around a given offset, in dB re the local max.

    Answers "is this peak impulse-sharp or smeared?" -- a smeared true peak
    explains a near-0 dB PSR at the 2-sample exclusion (its own shoulder gets
    counted as the sidelobe), which matters for how the sweep gate reads PSR.
    """
    gcc, offset_all = gcc_phat_correlation(ref_bp, cap_bp)
    sel = np.abs(offset_all - center_offset_samples) <= span
    order = np.argsort(offset_all[sel])
    offs = offset_all[sel][order]
    vals = np.abs(gcc[sel][order])
    top = float(vals.max())
    return [
        (int(o - center_offset_samples), 20.0 * float(np.log10(max(v, 1e-15) / top)))
        for o, v in zip(offs, vals)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wavs", nargs="*", help="click-bearing capture WAV file(s)")
    parser.add_argument("--sweep-dir", help="process every *.wav in this directory")
    parser.add_argument("--reference", default="../harness/src/main/assets/reference_track.wav")
    parser.add_argument("--lo", type=float, default=500.0, help="bandpass low edge (Hz)")
    parser.add_argument("--hi", type=float, default=4000.0, help="bandpass high edge (Hz)")
    parser.add_argument(
        "--max-offset-ms",
        type=float,
        default=300.0,
        help="half-width of the wide search windows (click detection and the signed "
        "GCC-PHAT window are both +/- this around zero offset)",
    )
    parser.add_argument(
        "--anchor-half-width-ms",
        type=float,
        default=90.0,
        help="half-width of the anchored windows; must stay below half the reference "
        "beat period (~187 ms -> <93.5) so a one-beat alias can never be inside",
    )
    parser.add_argument("--tolerance-ms", type=float, default=2.0, help="the +/-2 ms pass bar")
    parser.add_argument("--top-peaks", type=int, default=6)
    parser.add_argument(
        "--peak-shape-span",
        type=int,
        default=8,
        help="samples either side of the true/alias peaks to print (0 disables); "
        "shows whether each peak is impulse-sharp or smeared, which is what the "
        "2-sample-exclusion PSR actually responds to",
    )
    parser.add_argument(
        "--min-peak-separation-ms",
        type=float,
        default=20.0,
        help="minimum spacing between reported competing peaks (suppresses shoulder samples)",
    )
    args = parser.parse_args()

    paths = [Path(p) for p in args.wavs]
    if args.sweep_dir:
        paths += sorted(Path(args.sweep_dir).glob("*.wav"))
    if not paths:
        parser.error("no input WAVs (pass files or --sweep-dir)")
    if args.anchor_half_width_ms >= 93.5:
        print(
            f"WARN: anchor half-width {args.anchor_half_width_ms} ms >= half the ~187 ms "
            "beat period; a one-beat alias can sit inside the anchored window"
        )

    ref, ref_rate = _read_wav_mono(Path(args.reference))
    ref_bp = _bandpass(ref, args.lo, args.hi, ref_rate)
    lead_in = round(ref_rate * LEAD_IN_S)
    ref_trim_bp = _bandpass(ref[lead_in:], args.lo, args.hi, ref_rate)
    click_onset_ref = round(ref_rate * PRE_SILENCE_S)
    wide = int(args.max_offset_ms * 1e-3 * ref_rate)
    anchor_hw = int(args.anchor_half_width_ms * 1e-3 * ref_rate)

    print(f"reference: {args.reference}  {len(ref)} samples  {ref_rate} Hz")
    print(f"band: {args.lo:.0f}-{args.hi:.0f} Hz  tolerance: +/-{args.tolerance_ms} ms  "
          f"wide window: +/-{args.max_offset_ms:.0f} ms  anchored: +/-{args.anchor_half_width_ms:.0f} ms")

    pass_counts: dict[str, int] = {}
    totals = 0
    for path in paths:
        capture, rate = _read_wav_mono(path)
        if rate != ref_rate:
            print(f"\nSKIP {path.name}: rate {rate} != reference {ref_rate}")
            continue
        totals += 1

        # Ground truth: matched-filter click, searched over the SIGNED window
        # (the harness basis is negative -- a positive-only search finds a
        # wrong peak; see doc/test2-sweep-results.md "Calibration click cross-check").
        det = detect_click(
            capture,
            rate,
            search_window=(max(0, click_onset_ref - wide), click_onset_ref + wide),
        )
        gt_samples = det.onset_sample - click_onset_ref
        gt_ms = 1000.0 * gt_samples / rate
        stream_ms = _sidecar_stream_offset_ms(path)

        print(f"\n=== {path.name}")
        quality_note = (
            "  ** BELOW QUALITY FLOOR - ground truth untrustworthy, capture may be click-less **"
            if det.quality_db < _CLICK_QUALITY_FLOOR_DB
            else ""
        )
        print(f"click ground truth: {gt_ms:+.2f} ms (onset {det.onset_sample}, "
              f"quality {det.quality_db:.1f} dB){quality_note}")
        if stream_ms is not None:
            print(f"sidecar stream_offset_ms: {stream_ms:+.2f} "
                  f"(anchor error vs click: {stream_ms - gt_ms:+.2f} ms)")

        cap_bp = _bandpass(capture, args.lo, args.hi, rate)
        cap_trim_bp = _bandpass(capture[lead_in:], args.lo, args.hi, rate)

        anchored = _run_variant("click-anchored +/-90ms (remedy B)", ref_bp, cap_bp, rate,
                                (gt_samples - anchor_hw, gt_samples + anchor_hw),
                                gt_ms, args.tolerance_ms)
        variants = [
            _run_variant("unconstrained", ref_bp, cap_bp, rate, None, gt_ms, args.tolerance_ms),
            _run_variant("positive_0..300ms (old gate)", ref_bp, cap_bp, rate,
                         (0, wide), gt_ms, args.tolerance_ms),
            _run_variant("signed +/-300ms (remedy A)", ref_bp, cap_bp, rate,
                         (-wide, wide), gt_ms, args.tolerance_ms),
            anchored,
        ]
        if stream_ms is not None:
            stream_samples = int(round(stream_ms * 1e-3 * rate))
            variants.append(
                _run_variant("stream-anchored +/-90ms (product-shaped)", ref_bp, cap_bp, rate,
                             (stream_samples - anchor_hw, stream_samples + anchor_hw),
                             gt_ms, args.tolerance_ms)
            )
        variants.append(
            _run_variant("trimmed, signed +/-300ms", ref_trim_bp, cap_trim_bp, rate,
                         (-wide, wide), gt_ms, args.tolerance_ms)
        )

        print(f"{'variant':<42} {'offset_ms':>10} {'psr_db':>7} {'err_ms':>9}  verdict")
        print("-" * 80)
        for v in variants:
            psr_note = "" if v.psr_db >= _PSR_MINIMUM_DB else " (psr<6)"
            print(f"{v.name:<42} {v.offset_ms:>+10.2f} {v.psr_db:>7.1f} {v.err_ms:>+9.2f}  "
                  f"{'PASS' if v.passed else 'FAIL'}{psr_note}")
            pass_counts[v.name] = pass_counts.get(v.name, 0) + (1 if v.passed else 0)

        peaks = _competing_peaks(ref_bp, cap_bp, rate, args.max_offset_ms,
                                 args.top_peaks, args.min_peak_separation_ms)
        print(f"top competing peaks in +/-{args.max_offset_ms:.0f} ms "
              f"(band-limited raw GCC; 0.0 dB = winner):")
        for off_ms, level_db in peaks:
            marker = ""
            if abs(off_ms - gt_ms) <= args.tolerance_ms:
                marker = "  <-- true peak (matches click)"
            elif abs(off_ms - gt_ms - 187.0) < 15.0 or abs(off_ms - gt_ms + 187.0) < 15.0:
                marker = "  <-- one-beat alias"
            print(f"  {off_ms:+9.2f} ms  {level_db:+6.2f} dB{marker}")

        if args.peak_shape_span > 0 and peaks:
            alias_samples = int(round(peaks[0][0] * 1e-3 * rate))
            # Center the true-peak shape on the CORRELATOR's recovered offset (the
            # click-anchored variant), not the click offset itself -- the GCC peak
            # sits a small residual away from the click and the lobe shape is only
            # meaningful around the actual local max.
            anchored_samples = int(round(anchored.offset_ms * 1e-3 * rate))
            for label, center in [("true peak (click-anchored GCC)", anchored_samples),
                                  ("winning peak", alias_samples)]:
                if label == "winning peak" and abs(alias_samples - anchored_samples) <= args.peak_shape_span:
                    continue  # winner IS the true peak; one shape suffices
                shape = _peak_shape(ref_bp, cap_bp, rate, center, args.peak_shape_span)
                line = "  ".join(f"{db:+5.1f}" for _, db in shape)
                print(f"shape around {label} (dB re local max, "
                      f"{-args.peak_shape_span}..+{args.peak_shape_span} samples):")
                print(f"  {line}")

    if totals > 1:
        print(f"\n=== summary over {totals} captures (PASS = |offset - click| <= "
              f"{args.tolerance_ms} ms)")
        for name, count in pass_counts.items():
            print(f"  {name:<42} {count}/{totals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
