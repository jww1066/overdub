#!/usr/bin/env python3
"""Diagnose audible artifacts (clicks/hiss) in the NLMS echo-cancel residuals.

First audition of run_echo_cancel_eval.py's residuals (2026-07-09) reported
"a lot of clicks and hiss" in residual_bleed_only.wav and clicks in
residual_with_vocal.wav. Two distinct hypotheses produce click-like artifacts,
and they need opposite responses -- so measure, don't guess (offline-dsp guide):

  A. **int16 clipping at the WAV write.** The eval script writes raw residuals
     with np.clip and no peak-safety scaling (render_bleed_mix.py scales;
     run_echo_cancel_eval.py as first committed did not). Hard-clipped peaks
     read as clicks/distortion. This is a *rendering bug* -- the suppression
     numbers are computed on the float arrays and are unaffected, but the
     audition files lie.
  B. **Beat-transient residuals.** A converged linear FIR cannot cancel the
     speaker/mic chain's *nonlinear* behavior at percussive onsets (nor
     adaptation gradient noise concentrated at transients), so each beat can
     leave a click-shaped residue. This is a *mechanism property*, evidence
     about what "18 dB suppression" sounds like solo'd -- not a bug.

Hiss has its own split: room noise + bleed-path HF the reference never
carried (both uncorrelated with the far-end signal, so unremovable by ANY
reference-driven EC) vs correlated HF the filter failed to cancel.

What this script measures, per WAV in the eval dir:
  1. Clip census: samples at full scale (+/-32767) and >= 99% FS, with the
     times of the worst runs -- hypothesis A directly.
  2. Digital-discontinuity census: isolated sample-to-sample steps far above
     the local envelope (a buffer-seam/indexing bug signature, distinct from
     acoustic transients which rise over ~ms).
  3. Click-event detection on the >4 kHz band envelope (clicks are broadband;
     the band above the bleed passband isolates them from the music), then
     the distance from each click to the nearest reference beat onset --
     hypothesis B predicts clicks ON the onsets.
  4. Band-split RMS (capture vs residual: 0.5-4k, 4-8k, 8-16k) -- where the
     hiss lives and whether the filter reduced it at all (unreduced HF =
     uncorrelated, i.e. unremovable; that is the listening test's known
     "bleed path degrades HF" finding, not an EC failure).

Usage (from analysis/ via the venv per CLAUDE.md):
    .venv/Scripts/python.exe scripts/diagnose_ec_residual.py
    .venv/Scripts/python.exe scripts/diagnose_ec_residual.py \\
        --eval-dir echo_cancel_eval --reference ../harness/src/main/assets/reference_track.wav
"""

from __future__ import annotations

import argparse
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, filtfilt

FULL_SCALE = 32767.0


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


def _highpass(x: np.ndarray, cutoff: float, fs: int) -> np.ndarray:
    b, a = butter(4, cutoff / (fs / 2), btype="high")
    return filtfilt(b, a, x)


def _band_rms(x: np.ndarray, fs: int, lo: float, hi: float) -> float:
    nyq = fs / 2
    hi = min(hi, 0.999 * nyq)
    b, a = butter(4, [lo / nyq, hi / nyq], btype="band")
    return float(np.sqrt(np.mean(filtfilt(b, a, x) ** 2)))


def _envelope(x: np.ndarray, fs: int, win_ms: float) -> np.ndarray:
    win = max(1, int(round(win_ms * 1e-3 * fs)))
    kernel = np.ones(win) / win
    return np.sqrt(np.convolve(x**2, kernel, mode="same"))


def clip_census(x: np.ndarray) -> tuple[int, int]:
    """(samples at full scale, samples >= 99% of full scale)."""
    a = np.abs(x)
    return int(np.sum(a >= FULL_SCALE)), int(np.sum(a >= 0.99 * FULL_SCALE))


def digital_discontinuities(x: np.ndarray, fs: int, k: float = 8.0) -> list[int]:
    """Indices where |x[n]-x[n-1]| exceeds k * the local (25 ms) envelope.

    An acoustic transient's largest step is on the order of its local
    envelope; a buffer seam / indexing bug produces a step several times it.
    """
    d = np.abs(np.diff(x))
    env = _envelope(x, fs, 25.0)[1:] + 1e-9
    idx = np.flatnonzero(d > k * env)
    # Collapse runs (a single seam trips a few adjacent samples).
    out: list[int] = []
    for i in idx:
        if not out or i - out[-1] > fs // 100:
            out.append(int(i))
    return out


def click_events(
    x: np.ndarray, fs: int, *, hp_cutoff: float = 4000.0, k: float = 6.0
) -> list[tuple[float, float]]:
    """Broadband click events: (time_s, prominence vs median) of >4 kHz envelope peaks."""
    env = _envelope(_highpass(x, hp_cutoff, fs), fs, 2.0)
    floor = float(np.median(env)) + 1e-9
    hot = env > k * floor
    events: list[tuple[float, float]] = []
    n = 0
    while n < hot.size:
        if hot[n]:
            end = n
            while end < hot.size and hot[end]:
                end += 1
            peak_i = n + int(np.argmax(env[n:end]))
            events.append((peak_i / fs, float(env[peak_i] / floor)))
            n = end + int(0.010 * fs)  # 10 ms refractory
        else:
            n += 1
    return events


def reference_onsets(ref: np.ndarray, fs: int) -> np.ndarray:
    """Beat-onset times: peaks of the in-band envelope's positive derivative."""
    env = _envelope(_band_rms_signal(ref, fs), fs, 10.0)
    rise = np.maximum(0.0, np.diff(env))
    thresh = 4.0 * float(np.median(rise)) + 1e-9
    idx = np.flatnonzero(rise > thresh)
    onsets: list[int] = []
    for i in idx:
        if not onsets or i - onsets[-1] > int(0.050 * fs):
            onsets.append(int(i))
    return np.array(onsets) / fs


def _band_rms_signal(x: np.ndarray, fs: int) -> np.ndarray:
    b, a = butter(4, [500.0 / (fs / 2), 4000.0 / (fs / 2)], btype="band")
    return filtfilt(b, a, x)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--eval-dir", default="echo_cancel_eval")
    parser.add_argument("--reference", default="../harness/src/main/assets/reference_track.wav")
    parser.add_argument(
        "--onset-tolerance-ms",
        type=float,
        default=30.0,
        help="a click within this of a reference onset counts as beat-aligned",
    )
    parser.add_argument(
        "--also",
        nargs="*",
        default=[],
        help="additional WAVs to run the same census on (e.g. the raw device "
        "capture, to check whether clipping originated on-device)",
    )
    parser.add_argument(
        "--render-offset-s",
        type=float,
        default=1.01,
        help="time trimmed off the front of the eval renders (run_echo_cancel_eval "
        "trims the lead-in + guard by default; its manifest prints the trim "
        "window). Added to click times before matching reference onsets. Use 0 "
        "for untrimmed files (--keep-lead-in evals, raw captures via --also)",
    )
    args = parser.parse_args()

    eval_dir = Path(args.eval_dir)
    ref, ref_rate = _read_wav_mono(Path(args.reference))
    onsets = reference_onsets(ref, ref_rate)
    print(f"reference: {len(onsets)} beat onsets detected")
    print()

    capture: np.ndarray | None = None
    cap_path = eval_dir / "capture_aligned.wav"
    if cap_path.exists():
        capture, _ = _read_wav_mono(cap_path)

    paths = [
        eval_dir / name
        for name in (
            "capture_aligned.wav",
            "residual_bleed_only.wav",
            "residual_with_vocal.wav",
            "stem_with_vocal.wav",
            "echo_estimate.wav",
        )
    ] + [Path(a) for a in args.also]
    for p in paths:
        name = p.name if p.parent == eval_dir else str(p)
        if not p.exists():
            print(f"--- {name}: absent, skipped")
            continue
        x, fs = _read_wav_mono(p)
        full, near = clip_census(x)
        seams = digital_discontinuities(x, fs)
        clicks = click_events(x, fs)
        print(f"--- {name}")
        print(f"    peak {np.max(np.abs(x)):.0f} / {FULL_SCALE:.0f}  "
              f"clipped samples: {full} at FS, {near} >= 99% FS")
        print(f"    digital discontinuities (seam-like steps): {len(seams)}"
              + (f"  at {[f'{i / fs:.2f}s' for i in seams[:8]]}" if seams else ""))
        # Renders from run_echo_cancel_eval are trimmed; --also files are not.
        t_off = 0.0 if p.parent != eval_dir else args.render_offset_s
        if clicks:
            near_onset = sum(
                1 for t, _ in clicks
                if onsets.size
                and np.min(np.abs(onsets - (t + t_off))) <= args.onset_tolerance_ms * 1e-3
            )
            top = sorted(clicks, key=lambda c: -c[1])[:5]
            print(f"    click events (>4 kHz envelope, k=6): {len(clicks)}; "
                  f"{near_onset}/{len(clicks)} within {args.onset_tolerance_ms:.0f} ms "
                  f"of a reference beat onset")
            print(f"    worst: " + ", ".join(f"{t:.2f}s x{prom:.0f}" for t, prom in top))
        else:
            print("    click events (>4 kHz envelope, k=6): none")
        # Split regions: lead-in (chirp), content body, and the tail where the
        # aligned capture has run out of samples (zeros) but the reference has
        # not -- a residual there is pure -echo_estimate, an eval-rendering
        # artifact, not cancellation failure.
        body_lo = int(max(0.0, 1.01 - t_off) * fs)
        body_hi = min(x.size, int(max(0.0, 15.5 - t_off) * fs))
        regions = {
            "full": slice(None),
            "lead-in": slice(0, body_lo),
            "body": slice(body_lo, body_hi),
            "tail": slice(body_hi, None),
        }
        for lo, hi in ((500.0, 4000.0), (4000.0, 8000.0), (8000.0, 16000.0)):
            parts = []
            for rname, sl in regions.items():
                seg = x[sl]
                if seg.size < fs // 10:
                    continue
                rms = _band_rms(seg, fs, lo, hi)
                part = f"{rname} {rms:7.1f}"
                if capture is not None and name != "capture_aligned.wav":
                    cap_rms = _band_rms(capture[sl], fs, lo, hi)
                    if cap_rms > 0 and rms > 0:
                        part += f" ({20.0 * np.log10(rms / cap_rms):+5.1f} dB)"
                parts.append(part)
            print(f"    band {lo / 1000.0:4.1f}-{hi / 1000.0:4.1f} kHz rms:  " + "  |  ".join(parts))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
