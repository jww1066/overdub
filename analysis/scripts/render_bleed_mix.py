#!/usr/bin/env python3
"""Render the bleed-mix listening test (design-summary.md "Echo cancellation for v1").

The vocal-injection study measured that a speaker-route overdub stem carries
reference bleed ~12 dB ABOVE the vocal in-band (realistic vocal-to-bleed ratio
-12.2 dB), so the stem a downstream listener hears is bleed-dominated. Whether
that aligned bleed reads as benign on-beat "room" or objectionable comb-filter
coloration in a real mix is a listening judgment -- no one has heard the
product-shaped result. This script renders it (decided 2026-07-09; the outcome
decides whether offline on-device NLMS echo cancellation is v1 work or stays
deferred).

Pipeline (pure Python, no device):
  1. Take a click-bearing Session A capture (the bleed-only stem) and a vetted
     dry vocal take recorded in the same measurement basis.
  2. Construct the product-shaped overdub stem: vocal placed at its performed
     timing and mixed at the measured in-band vocal-to-bleed ratio
     (overdub_analysis.vocal_inject -- identical math to the injection study).
  3. Align the stem to the reference clock using the product-shaped offset:
     the click-anchored, band-limited GCC-PHAT offset, gated per capture with
     |gcc - click| <= 2 ms exactly as run_click_gated_sweep.py does. The
     render carries the correlator's real ~1 ms residual error -- that residual
     is part of what the product would ship, so it belongs in the audition.
  4. Render an A/B set, loudness-matched to a common RMS so the comparison
     judges coloration/hiss, not loudness (the first audition's ~16 dB jump
     between the bleed-heavy and bleed-free mixes made the A/B unfair). The real
     in-band level relationships are preserved in the manifest's ratio table --
     the file levels are intentionally flattened for a fair A/B.

       reference_only.wav   the clean reference (listening anchor)
       mix_product.wav      reference + aligned stem (bleed + vocal) -- THE mix
       mix_product_ecN.wav  the same mix with the stem's bleed attenuated N dB
                            (simulated echo cancellation, one file per value of
                            --bleed-suppression-db)
       mix_ideal_ec.wav     reference + aligned vocal only -- perfect echo
                            cancellation (the suppression ladder's limit)
       mix_bleed_only.wav   reference + aligned bleed only -- isolates the
                            bleed's coloration without the vocal masking it
       overdub_stem.wav     the aligned stem solo'd (what a downstream user
                            hears if they mute the reference)

The stem level in the mix is anchored on the VOCAL: one gain scales the whole
stem so its vocal component sits at --vocal-vs-ref-db relative to the
reference in-band; the bleed rides along ~12 dB hotter, which is the finding
being auditioned. Two calibration facts from the first audition (2026-07-09,
"vocal way too soft"): (1) equal in-band RMS is not equal loudness -- the
reference carries bass the 500-4000 Hz band doesn't count -- so the default
anchor is +6 dB, not 0; (2) no stem gain can balance the vocal against the
product mix's backing, because the backing is dominated by the bleed and the
vocal is pinned -12.2 dB under the bleed INSIDE the stem -- raising the gain
raises both together, so vocal-vs-backing saturates ~12 dB short of equal.
"Vocal at a musical level" is only reachable with bleed suppression; that is
what the mix_product_ecN ladder exists to audition, and hearing which rung
first sounds acceptable is the suppression requirement an NLMS would have to
meet.

What to listen for: A/B mix_product against the ecN ladder and mix_ideal_ec.
If unsuppressed bleed reads as tolerable on-beat thickening/"room", echo
cancellation stays deferred; if a ladder rung is where the mix first becomes
acceptable, that rung is the v1 NLMS suppression target. mix_bleed_only
sharpens the coloration judgment if the vocal masks it.

Usage (from analysis/ via the venv per CLAUDE.md):
    .venv/Scripts/python.exe scripts/render_bleed_mix.py
    # or explicitly:
    .venv/Scripts/python.exe scripts/render_bleed_mix.py \\
        --capture recapture_session_a/conversational_armslength_faceup_none_<ts>.wav \\
        --vocal vocal_take/vocal_take_1783545380726.wav

Outputs land in --out-dir (default listening_test/, gitignored -- WAVs are
never committed) plus a render_manifest.txt recording every level and offset.
"""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np

from overdub_analysis.bleed_mix import (
    loudness_match_gains,
    shift_to_reference_clock,
    stem_gain_for_vocal_vs_ref,
)
from overdub_analysis.calibration_click import LEAD_IN_S, PRE_SILENCE_S, detect_click
from overdub_analysis.gcc_phat import gcc_phat
from overdub_analysis.vocal_inject import bandpass, inband_rms

# Same floor as run_click_gated_sweep.py: below this the click anchor is absent
# and the capture cannot be honestly aligned at all.
_CLICK_QUALITY_FLOOR_DB = 10.0
# The baseline gate cell -- used to pick a default capture when --capture is a directory.
_BASELINE_GLOB = "conversational_armslength_faceup_none_*.wav"


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


def _write_wav_mono16(path: Path, samples: np.ndarray, rate: int) -> None:
    clipped = np.clip(np.round(samples), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(clipped.tobytes())


def _resolve_capture(arg: str) -> Path:
    """Accept a WAV path directly, or a sweep dir (picks the first baseline-cell capture)."""
    p = Path(arg)
    if p.is_dir():
        candidates = sorted(p.glob(_BASELINE_GLOB))
        if not candidates:
            raise SystemExit(f"no {_BASELINE_GLOB} captures in {p}")
        return candidates[0]
    if not p.exists():
        raise SystemExit(f"capture not found: {p}")
    return p


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--capture",
        default="recapture_session_a",
        help="click-bearing Session A capture WAV, or a dir (first baseline-cell capture)",
    )
    parser.add_argument(
        "--vocal",
        default="vocal_take/vocal_take_1783545380726.wav",
        help="dry close-mic vocal take WAV (default: take 2, the realistic-ratio take)",
    )
    parser.add_argument("--reference", default="../harness/src/main/assets/reference_track.wav")
    parser.add_argument(
        "--vocal-ratio-db",
        type=float,
        default=-12.2,
        help="in-band vocal-to-bleed ratio for the stem (default: the measured -12.2 dB pin)",
    )
    parser.add_argument(
        "--vocal-vs-ref-db",
        type=float,
        default=6.0,
        help="stem gain anchor: the stem's vocal component's in-band level vs the "
        "reference in the final mix. 0 = equal in-band RMS, which auditions "
        "several dB soft (the band omits the reference's bass); +6 is the "
        "calibrated default from the first listen",
    )
    parser.add_argument(
        "--bleed-suppression-db",
        type=float,
        nargs="*",
        default=[6.0, 12.0, 18.0],
        help="render an extra mix_product_ec<N>.wav per value, with the stem's "
        "bleed attenuated N dB -- a simulated-echo-cancellation ladder; the rung "
        "where the mix first sounds acceptable is the NLMS suppression target",
    )
    parser.add_argument("--lo", type=float, default=500.0)
    parser.add_argument("--hi", type=float, default=4000.0)
    parser.add_argument("--max-offset-ms", type=float, default=300.0)
    parser.add_argument("--anchor-half-width-ms", type=float, default=90.0)
    parser.add_argument("--tolerance-ms", type=float, default=2.0)
    parser.add_argument(
        "--keep-lead-in",
        action="store_true",
        help="keep the 1 s calibration lead-in in the renders (default: trim to content "
        "start, so the audition begins at the music, not the chirp)",
    )
    parser.add_argument("--out-dir", default="listening_test")
    args = parser.parse_args()

    capture_path = _resolve_capture(args.capture)
    vocal_path = Path(args.vocal)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ref, rate = _read_wav_mono(Path(args.reference))
    capture, cap_rate = _read_wav_mono(capture_path)
    vocal, voc_rate = _read_wav_mono(vocal_path)
    if cap_rate != rate or voc_rate != rate:
        raise SystemExit(f"rate mismatch: ref {rate}, capture {cap_rate}, vocal {voc_rate}")

    report: list[str] = []

    def say(line: str = "") -> None:
        print(line)
        report.append(line)

    say(f"reference: {args.reference} ({len(ref)} samples, {rate} Hz)")
    say(f"capture:   {capture_path}")
    say(f"vocal:     {vocal_path}")
    say()

    # --- 1. Click anchor (ground truth) on the raw capture -------------------
    click_onset_ref = round(rate * PRE_SILENCE_S)
    wide = int(args.max_offset_ms * 1e-3 * rate)
    det = detect_click(
        capture, rate, search_window=(max(0, click_onset_ref - wide), click_onset_ref + wide)
    )
    tau_c = det.onset_sample - click_onset_ref
    click_ms = 1000.0 * tau_c / rate
    say(f"click anchor: offset {click_ms:+.2f} ms, quality {det.quality_db:.1f} dB")
    if det.quality_db < _CLICK_QUALITY_FLOOR_DB:
        say(f"ABORT: click quality below the {_CLICK_QUALITY_FLOOR_DB:.0f} dB floor -- "
            "this capture cannot be honestly aligned")
        return 1

    # --- 2. Product-shaped alignment: click-anchored band-limited GCC-PHAT ---
    ref_bp = bandpass(ref, args.lo, args.hi, rate)
    cap_bp = bandpass(capture, args.lo, args.hi, rate)
    anchor_hw = int(args.anchor_half_width_ms * 1e-3 * rate)
    r = gcc_phat(
        ref_bp, cap_bp, fs=rate, lag_window=(tau_c - anchor_hw, tau_c + anchor_hw)
    )
    tau = int(r.offset_samples)
    gcc_ms = 1000.0 * tau / rate
    err_ms = gcc_ms - click_ms
    say(f"gcc-phat:     offset {gcc_ms:+.2f} ms, err vs click {err_ms:+.2f} ms "
        f"(gate: |err| <= {args.tolerance_ms} ms)")
    if abs(err_ms) > args.tolerance_ms:
        say("ABORT: the capture fails the click gate -- a misaligned render would "
            "corrupt the listening judgment; pick another capture")
        return 1
    say("alignment applied to the renders: the GCC-PHAT offset (product-shaped -- "
        "its residual error is part of what ships)")
    say()

    # --- 3. Vocal placement: the take's own stream offset (honest, stable) ----
    # The performer monitored the reference through this session, so the take's
    # getTimestamp stream offset (input vs output, SAME sign convention as the
    # GCC offset -- mic[n] ~= reference[n - offset]) places the vocal at its
    # performed timing directly on the reference grid. This replaces the vocal-
    # injection study's whole-take GCC tau_v (vocal vs reference): that correlates
    # two DIFFERENT waveforms and is tempo-correlated but segment-unstable
    # (leak_detect), which put the vocal off-rhythm in the first audition. The
    # stream offset is the product-shaped anchor (no click at runtime;
    # getTimestamp is available) and is stable. Caveat: it is a single getTimestamp
    # read (the take has no click at gain 0 to cross-check it), so it inherits the
    # Test 1a outlier/desync tail risk -- but it is still far better than the
    # provably-unstable tau_v. If it still sounds off-rhythm, re-record the vocal
    # take with an audible lead-in click for its own click anchor.
    vocal_json = vocal_path.with_suffix(".json")
    vocal_offset_samples: int | None = None
    if vocal_json.exists():
        vmeta = json.loads(vocal_json.read_text())
        som = vmeta.get("stream_offset_ms")
        if som is not None:
            vocal_offset_samples = round(som * rate / 1000.0)
            say(f"vocal placement: stream_offset {som:+.2f} ms "
                f"({vocal_offset_samples} samples) from the take's sidecar -- "
                "performed timing on the reference grid")
    if vocal_offset_samples is None:
        # Fallback: the old, segment-unstable whole-take GCC tau_v, net-shifted
        # onto the reference grid (tau + (tau_v - tau_c), tau ~= tau_c => ~tau_v).
        from overdub_analysis.vocal_inject import vocal_placement_samples
        voc_bp = bandpass(vocal, args.lo, args.hi, rate)
        shift = vocal_placement_samples(ref_bp, voc_bp, rate, tau_c)
        vocal_offset_samples = shift + tau
        say(f"WARN: vocal take sidecar has no stream_offset_ms; falling back to the "
            f"segment-unstable whole-take GCC tau_v (placement {vocal_offset_samples} "
            "samples). Re-record the vocal take with stream timestamps for an "
            "honest placement.")

    # --- 4. Align both stems to the reference clock independently -------------
    bleed_al = shift_to_reference_clock(capture, tau, len(ref))
    vocal_al = shift_to_reference_clock(vocal, vocal_offset_samples, len(ref))

    # --- 5. Levels: in-band ratio, then one stem gain anchored on the vocal ---
    content = 0 if args.keep_lead_in else round(rate * LEAD_IN_S)
    bleed_inband = inband_rms(bleed_al[content:], rate, args.lo, args.hi)
    vocal_inband = inband_rms(vocal_al[content:], rate, args.lo, args.hi)
    ratio_scale = (10.0 ** (args.vocal_ratio_db / 20.0)) * bleed_inband / vocal_inband
    vocal_comp_al = ratio_scale * vocal_al  # the scaled vocal, on the reference grid

    # Sanity: the in-band ratio the stem actually achieved (quadrature estimate,
    # same arithmetic as run_vocal_injection.py; placement-invariant).
    stem_inband = inband_rms(bleed_al[content:] + vocal_comp_al[content:], rate, args.lo, args.hi)
    vocal_in_stem = np.sqrt(max(stem_inband**2 - bleed_inband**2, 0.0))
    achieved_db = (
        20 * np.log10(vocal_in_stem / bleed_inband) if bleed_inband > 0 else float("nan")
    )
    say(f"stem: in-band vocal-to-bleed target {args.vocal_ratio_db:+.1f} dB, "
        f"achieved {achieved_db:+.1f} dB")

    g = stem_gain_for_vocal_vs_ref(
        ref[content:], vocal_comp_al[content:], rate, args.vocal_vs_ref_db,
        lo=args.lo, hi=args.hi,
    )
    bleed_vs_ref_db = 20 * np.log10(
        inband_rms(g * bleed_al[content:], rate, args.lo, args.hi)
        / inband_rms(ref[content:], rate, args.lo, args.hi)
    )
    say(f"stem gain: {20 * np.log10(g):+.1f} dB (vocal lands {args.vocal_vs_ref_db:+.1f} dB "
        f"vs reference in-band; the bleed therefore lands {bleed_vs_ref_db:+.1f} dB)")
    say()

    # --- 6. Renders ----------------------------------------------------------
    renders = {
        "reference_only.wav": ref[content:],
        "mix_product.wav": (ref + g * (bleed_al + vocal_comp_al))[content:],
        "mix_ideal_ec.wav": (ref + g * vocal_comp_al)[content:],
        "mix_bleed_only.wav": (ref + g * bleed_al)[content:],
        "overdub_stem.wav": (g * (bleed_al + vocal_comp_al))[content:],
    }
    for sup_db in args.bleed_suppression_db:
        attenuated = 10.0 ** (-sup_db / 20.0)
        renders[f"mix_product_ec{sup_db:.0f}.wav"] = (
            ref + g * (attenuated * bleed_al + vocal_comp_al)
        )[content:]

    # Diagnostic: how far the vocal sits below each mix's total backing (reference
    # + surviving bleed, in-band) -- the quantity the ear balances against, and
    # the one no stem gain can fix (it saturates at the in-stem vocal-to-bleed
    # ratio as the bleed dominates the backing). These REAL levels are preserved
    # here even though the files below are loudness-matched for a fair A/B.
    voc_rms = inband_rms(g * vocal_comp_al[content:], rate, args.lo, args.hi)
    say("vocal vs total backing (reference + surviving bleed, in-band) -- REAL levels:")
    for name, samples in renders.items():
        if not name.startswith("mix_product"):
            continue
        backing = samples - g * vocal_comp_al[content:]  # mix minus the vocal
        ratio_db = 20 * np.log10(voc_rms / inband_rms(backing, rate, args.lo, args.hi))
        say(f"  {name:<24} vocal sits {ratio_db:+.1f} dB vs its backing")
    ideal_backing_db = 20 * np.log10(voc_rms / inband_rms(ref[content:], rate, args.lo, args.hi))
    say(f"  {'mix_ideal_ec.wav':<24} vocal sits {ideal_backing_db:+.1f} dB vs its backing")
    say()

    # Loudness-match the renders (common RMS, then a peak-safety scale) so the
    # A/B judges coloration/hiss, not loudness -- the first audition's 16 dB jump
    # between mix_product and mix_ideal_ec made the comparison unfair. The real
    # level relationships stay in the ratio table above; the file levels are
    # intentionally flattened here.
    gains, _target = loudness_match_gains(list(renders.values()))
    scaled = [gi * s for gi, s in zip(gains, renders.values())]
    peak = max(float(np.max(np.abs(s))) for s in scaled)
    peak_safety = (0.89 * 32767.0) / peak
    say(f"renders (loudness-matched to common RMS, then peak-safety "
        f"{20 * np.log10(peak_safety):+.1f} dB; file levels are matched, real "
        f"levels are in the table above):")
    for (name, _), s in zip(renders.items(), scaled):
        final = peak_safety * s
        _write_wav_mono16(out_dir / name, final, rate)
        peak_db = 20 * np.log10(float(np.max(np.abs(final))) / 32767.0)
        rms_db = 20 * np.log10(float(np.sqrt(np.mean(final**2))) / 32767.0)
        say(f"  {name:<24} {len(s) / rate:5.2f} s  peak {peak_db:+6.1f}  rms {rms_db:+6.1f} dBFS")
    say()
    say("Listen (headphones, equal loudness): walk mix_product -> ecN -> mix_ideal_ec.")
    say("If unsuppressed bleed is tolerable on-beat thickening/'room', echo")
    say("cancellation stays deferred; otherwise the first acceptable rung is the")
    say("v1 NLMS suppression target. mix_bleed_only isolates the coloration if")
    say("the vocal masks it. Note any HF hiss surviving suppression -- it is the")
    say("bleed's coloration (absent in mix_ideal_ec), itself evidence in the")
    say("decision. Record the verdict in doc/design-summary.md (echo-cancellation")
    say("open item).")

    (out_dir / "render_manifest.txt").write_text("\n".join(report) + "\n")
    print(f"\nmanifest: {out_dir / 'render_manifest.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
