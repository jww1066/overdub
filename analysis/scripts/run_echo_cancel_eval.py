#!/usr/bin/env python3
"""Evaluate offline NLMS echo cancellation against the ~12 dB v1 target.

The bleed-mix listening test (design-summary.md "Echo cancellation for v1",
2026-07-09) decided echo cancellation is v1 work and set a rough suppression
target of ~12 dB -- the first simulated-EC ladder rung that auditioned as
acceptable. That ladder ATTENUATED the bleed arithmetically; nothing yet shows
an actual EC mechanism can reach the rung on the real speaker->mic path. This
script measures it: offline NLMS (overdub_analysis.echo_cancel) with the exact
clean reference as the far-end signal, run on a real click-bearing Session A
capture, reporting achieved in-band bleed suppression against the target.

Pipeline (pure Python, no device):
  1. Click anchor + click-gated band-limited GCC-PHAT alignment of the capture,
     exactly as run_click_gated_sweep.py / render_bleed_mix.py gate it (a
     misaligned capture would corrupt the suppression number).
  2. Shift the capture onto the reference clock MINUS a guard delay, so the
     echo path sits causally ~guard into the NLMS filter span (the +/-2 ms
     alignment residual could otherwise make it marginally acausal).
  3. Offline NLMS, multiple passes (default 2): pass 1 converges the filter on
     the take itself, the final pass's residual is the deliverable -- what
     "offline EC on-device" means for the product.
  4. Report in-band (500-4000 Hz) suppression over the content region, the
     per-second suppression profile (convergence honesty), the estimated
     path's tail energy (filter-length adequacy), and the capture's own
     room-noise floor (the ceiling any EC can reach -- NLMS cannot remove
     noise uncorrelated with the reference).
  5. Optionally repeat with a dry vocal take mixed in at the measured
     realistic in-band vocal-to-bleed ratio (-12.2 dB): the product adapts
     with the performer's vocal present, which costs misadjustment; this run
     measures whether the target still holds (the vocal itself passes through
     NLMS untouched by construction -- the echo estimate is built from the
     reference alone).

Outputs land in --out-dir (default echo_cancel_eval/, gitignored -- WAVs are
never committed) plus an eval_manifest.txt recording every number. The
residual WAVs can be auditioned against the listening test's simulated ec12
rung.

Usage (from analysis/ via the venv per CLAUDE.md):
    .venv/Scripts/python.exe scripts/run_echo_cancel_eval.py
    # or explicitly:
    .venv/Scripts/python.exe scripts/run_echo_cancel_eval.py \\
        --capture recapture_session_a/conversational_armslength_faceup_none_<ts>.wav \\
        --vocal vocal_take/vocal_take_1783545380726.wav
"""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np

from overdub_analysis.bleed_mix import shift_to_reference_clock
from overdub_analysis.calibration_click import LEAD_IN_S, PRE_SILENCE_S, detect_click
from overdub_analysis.echo_cancel import (
    clip_mask,
    mute_spans,
    nlms,
    suppression_db,
    suppression_profile,
    tail_energy_fraction,
)
from overdub_analysis.gcc_phat import gcc_phat
from overdub_analysis.vocal_inject import bandpass, inband_rms

# Same floor as run_click_gated_sweep.py / render_bleed_mix.py.
_CLICK_QUALITY_FLOOR_DB = 10.0
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
        help="dry close-mic vocal take for the vocal-present run (skipped with a "
        "note if the file is absent); pass an empty string to skip explicitly",
    )
    parser.add_argument("--reference", default="../harness/src/main/assets/reference_track.wav")
    parser.add_argument(
        "--target-db",
        type=float,
        default=12.0,
        help="the v1 suppression target from the listening test",
    )
    parser.add_argument(
        "--num-taps",
        type=int,
        default=4096,
        help="NLMS filter length in samples (~85 ms at 48 kHz: guard + multipath "
        "+ reverb tail; check the reported tail energy)",
    )
    # Defaults are the validated 2026-07-09 config: offline adaptation has no
    # convergence deadline, so a small step size buys low misadjustment under
    # near-end (vocal) signal and extra passes buy back the convergence. On the
    # Session A baseline capture the vocal-present bleed suppression measured
    # 10.6 dB at mu 0.5 / 2 passes, 11.8 at 0.15 / 3, 14.1 at 0.05 / 4 (the
    # bleed-only number stays ~18.5 dB throughout).
    parser.add_argument("--mu", type=float, default=0.05)
    parser.add_argument("--passes", type=int, default=4)
    parser.add_argument(
        "--guard-ms",
        type=float,
        default=10.0,
        help="extra delay applied to the aligned capture so the +/-2 ms "
        "alignment residual cannot make the echo path acausal",
    )
    parser.add_argument(
        "--vocal-ratio-db",
        type=float,
        default=-12.2,
        help="in-band vocal-to-bleed ratio for the vocal-present run (the measured pin)",
    )
    parser.add_argument("--lo", type=float, default=500.0)
    parser.add_argument("--hi", type=float, default=4000.0)
    parser.add_argument("--max-offset-ms", type=float, default=300.0)
    parser.add_argument("--anchor-half-width-ms", type=float, default=90.0)
    parser.add_argument("--tolerance-ms", type=float, default=2.0)
    parser.add_argument(
        "--clip-pad-ms",
        type=float,
        default=3.0,
        help="widen each capture-saturation span this much per side (the input "
        "chain's filtering smears clipping past the flat top)",
    )
    parser.add_argument(
        "--clip-fade-ms",
        type=float,
        default=2.0,
        help="raised-cosine fade length into/out of each muted saturation span",
    )
    parser.add_argument(
        "--keep-lead-in",
        action="store_true",
        help="keep the 1 s calibration lead-in in the renders (default: trim it -- "
        "the chirp survives EC nearly uncancelled because its ~0.9 FS level "
        "drives the path into a gain regime the music-converged filter "
        "doesn't model, and auditioning that reads as a mechanism failure)",
    )
    parser.add_argument("--out-dir", default="echo_cancel_eval")
    args = parser.parse_args()

    capture_path = _resolve_capture(args.capture)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ref, rate = _read_wav_mono(Path(args.reference))
    capture, cap_rate = _read_wav_mono(capture_path)
    if cap_rate != rate:
        raise SystemExit(f"rate mismatch: ref {rate}, capture {cap_rate}")

    report: list[str] = []

    def say(line: str = "") -> None:
        print(line)
        report.append(line)

    say(f"reference: {args.reference} ({len(ref)} samples, {rate} Hz)")
    say(f"capture:   {capture_path}")
    say(f"nlms:      num_taps {args.num_taps}, mu {args.mu}, passes {args.passes}, "
        f"guard {args.guard_ms} ms")
    say()

    # --- 1. Click anchor + click-gated GCC-PHAT alignment ---------------------
    click_onset_ref = round(rate * PRE_SILENCE_S)
    wide = int(args.max_offset_ms * 1e-3 * rate)
    det = detect_click(
        capture, rate, search_window=(max(0, click_onset_ref - wide), click_onset_ref + wide)
    )
    tau_c = det.onset_sample - click_onset_ref
    click_ms = 1000.0 * tau_c / rate
    say(f"click anchor: offset {click_ms:+.2f} ms, quality {det.quality_db:.1f} dB")
    if det.quality_db < _CLICK_QUALITY_FLOOR_DB:
        say(f"ABORT: click quality below the {_CLICK_QUALITY_FLOOR_DB:.0f} dB floor")
        return 1

    ref_bp = bandpass(ref, args.lo, args.hi, rate)
    cap_bp = bandpass(capture, args.lo, args.hi, rate)
    anchor_hw = int(args.anchor_half_width_ms * 1e-3 * rate)
    r = gcc_phat(ref_bp, cap_bp, fs=rate, lag_window=(tau_c - anchor_hw, tau_c + anchor_hw))
    tau = int(r.offset_samples)
    err_ms = 1000.0 * (tau - tau_c) / rate
    say(f"gcc-phat:     offset {1000.0 * tau / rate:+.2f} ms, err vs click {err_ms:+.2f} ms "
        f"(gate: |err| <= {args.tolerance_ms} ms)")
    if abs(err_ms) > args.tolerance_ms:
        say("ABORT: capture fails the click gate -- a misaligned capture would "
            "corrupt the suppression measurement")
        return 1
    say()

    # --- 2. Align onto the reference clock, minus the causality guard ---------
    guard = round(args.guard_ms * 1e-3 * rate)
    # d[i] = capture[i + tau - guard]: the reference grid delayed by `guard`,
    # so the echo path sits at delay ~guard in the filter span.
    d = shift_to_reference_clock(capture, tau - guard, len(ref))
    # Content region on d's grid: skip the lead-in -- NOT because the chirp is
    # trivially cancellable (measured 2026-07-09: it is barely cancelled at
    # all; played at ~0.9 FS it drives the speaker/input chain into a
    # different gain regime than the music the filter converges on, a
    # level-dependence no LTI filter models) -- but because it is
    # unrepresentative of the content the suppression target is about. End
    # the region where the shifted capture runs out of source samples (beyond
    # that d is zeros and the residual is pure -echo_estimate, an artifact).
    off = tau - guard
    cov_end = max(0, -off) + max(
        0, min(len(capture) - max(0, off), len(ref) - max(0, -off))
    )
    content = round(rate * LEAD_IN_S) + guard
    body = slice(content, cov_end)

    # Capture-saturation handling: a railed sample is missing data -- a
    # nonlinearity a linear EC cannot model -- so left alone every clipped
    # beat leaves a click in the residual (first audition, 2026-07-09). The
    # clip-aware treatment: freeze adaptation across railed spans (adapting on
    # the rail injects the clipping error into the weights) and mute the
    # residual across them with short fades (the distortion there is
    # uncancellable and the buried content unrecoverable; ~ms of smooth
    # silence is the least-artifact rendering).
    pad = round(args.clip_pad_ms * 1e-3 * rate)
    fade = round(args.clip_fade_ms * 1e-3 * rate)
    mask_c = clip_mask(capture, pad=pad)
    clipped = int(np.sum(np.abs(capture) >= 32767.0))
    mask_d = shift_to_reference_clock(mask_c.astype(np.float64), tau - guard, len(ref)) > 0.5
    adapt_mask = ~mask_d if mask_d.any() else None
    if clipped:
        n_spans = int(np.sum(np.diff(mask_d.astype(np.int8)) == 1) + (1 if mask_d[0] else 0))
        say(f"WARN: capture contains {clipped} full-scale samples -- the on-device "
            "input chain clipped on transients (capture saturation, not filter "
            f"failure). Clip-aware treatment active: adaptation frozen and residual "
            f"muted across {n_spans} spans, {1000.0 * np.sum(mask_d) / rate:.0f} ms "
            f"total (pad {args.clip_pad_ms:.0f} ms, fades {args.clip_fade_ms:.0f} ms); "
            "*_unrepaired.wav renders keep the raw residual for A/B.")
        say()

    # --- 3. The EC ceiling: the capture's own room-noise floor ----------------
    # d[0 : click onset + guard] predates the click: room noise only. NLMS
    # cannot remove energy uncorrelated with the reference, so bleed-to-noise
    # is the most suppression ANY reference-driven EC could show here.
    noise_region = d[: click_onset_ref + guard]
    noise_rms = inband_rms(noise_region, rate, args.lo, args.hi)
    bleed_rms = inband_rms(d[body], rate, args.lo, args.hi)
    ceiling_db = 20.0 * np.log10(bleed_rms / noise_rms) if noise_rms > 0 else float("inf")
    say(f"room-noise EC ceiling: capture in-band content sits {ceiling_db:.1f} dB above "
        "the pre-click room floor (max observable suppression)")
    say()

    # --- 4. Bleed-only NLMS run ------------------------------------------------
    say("=== bleed-only run (Session A capture as-is) ===")
    res = nlms(
        ref, d, num_taps=args.num_taps, mu=args.mu, passes=args.passes,
        adapt_mask=adapt_mask,
    )
    residual = mute_spans(res.residual, mask_d, fade=fade)
    sup_inband = suppression_db(d[body], residual[body], rate, args.lo, args.hi)
    sup_raw = suppression_db(d[body], res.residual[body], rate, args.lo, args.hi)
    broadband = 20.0 * np.log10(
        float(np.sqrt(np.mean(d[body] ** 2)))
        / float(np.sqrt(np.mean(residual[body] ** 2)))
    )
    say(f"in-band suppression ({args.lo:.0f}-{args.hi:.0f} Hz): {sup_inband:.1f} dB "
        f"(target {args.target_db:.0f} dB; before clip repair {sup_raw:.1f} dB)  |  "
        f"broadband: {broadband:.1f} dB")
    tail = tail_energy_fraction(res.impulse_response)
    say(f"path-estimate tail energy (last 10% of taps): {100.0 * tail:.1f}% "
        f"({'OK' if tail < 0.05 else 'RAISE num_taps -- the reverb tail is truncated'})")
    say("per-second in-band suppression (convergence honesty):")
    for t, db in suppression_profile(d[body], residual[body], rate, args.lo, args.hi):
        say(f"  {t:5.1f}s  {db:6.1f} dB")
    verdict = "PASS" if sup_inband >= args.target_db else "SHORT OF TARGET"
    say(f"bleed-only verdict: {verdict} ({sup_inband:.1f} dB vs {args.target_db:.0f} dB target)")
    say()

    renders: dict[str, np.ndarray] = {
        "capture_aligned.wav": d,
        "residual_bleed_only.wav": residual,
        "echo_estimate.wav": res.echo_estimate,
    }
    if mask_d.any():
        renders["residual_bleed_only_unrepaired.wav"] = res.residual

    # --- 5. Vocal-present run (the product's adaptation condition) ------------
    vocal_path = Path(args.vocal) if args.vocal else None
    if vocal_path and vocal_path.exists():
        say("=== vocal-present run (adaptation with the performer's vocal in the mic) ===")
        vocal, voc_rate = _read_wav_mono(vocal_path)
        if voc_rate != rate:
            raise SystemExit(f"rate mismatch: ref {rate}, vocal {voc_rate}")
        vocal_json = vocal_path.with_suffix(".json")
        som = None
        if vocal_json.exists():
            som = json.loads(vocal_json.read_text()).get("stream_offset_ms")
        if som is None:
            say("SKIP: vocal take sidecar has no stream_offset_ms (honest placement "
                "unavailable; see render_bleed_mix.py step 3)")
        else:
            voc_off = round(som * rate / 1000.0)
            vocal_al = shift_to_reference_clock(vocal, voc_off - guard, len(ref))
            scale = (
                (10.0 ** (args.vocal_ratio_db / 20.0))
                * bleed_rms
                / inband_rms(vocal_al[body], rate, args.lo, args.hi)
            )
            stem = d + scale * vocal_al
            say(f"vocal: {vocal_path} placed at stream_offset {som:+.2f} ms, "
                f"scaled to {args.vocal_ratio_db:+.1f} dB in-band vs bleed")
            res_v = nlms(
                ref, stem, num_taps=args.num_taps, mu=args.mu, passes=args.passes,
                adapt_mask=adapt_mask,
            )
            # The same clip repair mutes the vocal across the railed spans too
            # (the bleed's clipping corrupted those samples of the shared mic
            # signal); the spans total ~tens of ms across a take, entered and
            # left with fades.
            residual_v = mute_spans(res_v.residual, mask_d, fade=fade)
            # Bleed suppression specifically: the echo estimate is judged against
            # the bleed component we know exactly (d), not the stem.
            sup_v = suppression_db(d[body], (d - res_v.echo_estimate)[body], rate, args.lo, args.hi)
            say(f"in-band BLEED suppression with vocal present: {sup_v:.1f} dB "
                f"(bleed-only run: {sup_inband:.1f} dB; delta {sup_v - sup_inband:+.1f} dB "
                "= misadjustment cost of near-end signal)")
            verdict_v = "PASS" if sup_v >= args.target_db else "SHORT OF TARGET"
            say(f"vocal-present verdict: {verdict_v} ({sup_v:.1f} dB vs "
                f"{args.target_db:.0f} dB target)")
            renders["stem_with_vocal.wav"] = stem
            renders["residual_with_vocal.wav"] = residual_v
            if mask_d.any():
                renders["residual_with_vocal_unrepaired.wav"] = res_v.residual
    else:
        say(f"vocal-present run skipped (no vocal take at {args.vocal!r})")
    say()

    # --- 6. Renders for audition ----------------------------------------------
    # Trimmed to the body region by default: the lead-in's chirp survives EC
    # almost uncancelled (level-dependent path -- see the alignment comment),
    # and past the capture's coverage the "residual" is pure -echo_estimate;
    # both would read as artifacts of the mechanism when they are artifacts of
    # the rendering. One shared, attenuate-only gain keeps the files honestly
    # comparable (capture vs residual level difference IS the finding) while
    # preventing the int16 write from hard-clipping the residual's transient
    # spikes into extra clicks.
    lo_cut = 0 if args.keep_lead_in else content
    trimmed = {name: s[lo_cut:cov_end] for name, s in renders.items()}
    peak = max(float(np.max(np.abs(s))) for s in trimmed.values())
    gain = min(1.0, (0.89 * 32767.0) / peak) if peak > 0 else 1.0
    say(f"renders (trimmed to {lo_cut / rate:.2f}..{cov_end / rate:.2f} s, shared gain "
        f"{20.0 * np.log10(gain):+.1f} dB):")
    for name, s in trimmed.items():
        final = gain * s
        _write_wav_mono16(out_dir / name, final, rate)
        peak_db = 20.0 * np.log10(max(float(np.max(np.abs(final))), 1.0) / 32767.0)
        rms_db = 20.0 * np.log10(max(float(np.sqrt(np.mean(final**2))), 1.0) / 32767.0)
        say(f"  {name:<26} peak {peak_db:+6.1f}  rms {rms_db:+6.1f} dBFS")
    say()
    say("Audition: residual_bleed_only.wav against capture_aligned.wav (and the")
    say("listening test's mix_product_ec12 rung). Beat-aligned clicks are the")
    say("capture's own clipped transients -- muted by the clip repair in the main")
    say("renders; *_unrepaired.wav keeps them for A/B. Steady hiss is the bleed's")
    say("uncorrelated HF + room noise -- unremovable by reference-driven EC.")
    say("Record the outcome in doc/design-summary.md (echo-cancellation item).")

    (out_dir / "eval_manifest.txt").write_text("\n".join(report) + "\n")
    print(f"\nmanifest: {out_dir / 'eval_manifest.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
