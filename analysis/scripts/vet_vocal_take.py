#!/usr/bin/env python3
"""Vet a close-mic vocal take for the item-12 vocal-interference study.

A take recorded via harness/scripts/run_vocal_take.sh (record-only, playback
gain 0.0) must satisfy, per doc/test2-step2-plan.md item 12, before it can be
mixed into sweep captures at controlled vocal-to-bleed ratios:

  1. FORMAT   -- mono 16-bit at the reference rate (same basis as the captures).
  2. NO CLIP  -- close-mic plosives clip easily; clipping is nonlinear and
                 cannot be scaled away when the mixing ratio is applied later.
                 Hard-fail on any sample at the int16 rails.
  3. ACTIVE   -- the take must be continuously performed: report active-window
                 fraction (gaps of silence let the correlator see clean bleed,
                 making the eventual injection test easier than production) and
                 the active-region RMS used for ratio pinning.
  4. NO LEAK  -- the performer monitors the reference on ANOTHER device's
                 headphones; any leak of the reference into this take would
                 inject a copy at an unknown offset and corrupt the study.
                 Hard gate: the calibration click must NOT be detectable in the
                 take (matched filter quality below the click floor). Diagnostic:
                 band-limited full-range GCC-PHAT PSR vs the reference -- a
                 waveform-correlated peak is a leak signature (the vocal being
                 merely tempo-correlated with the reference does not produce one).

With --bleed-rms <value> (e.g. the baseline cell's captured RMS) it also prints
the vocal-to-bleed ratio in dB -- the number item 12 needs pinned before the
injection study runs. Both RMS values live in the same measurement basis
because the take was captured through the identical mic chain.

Usage (from analysis/ via the venv):
    .venv/Scripts/python.exe scripts/vet_vocal_take.py vocal_take/take.wav [more.wav ...] \\
        --reference ../harness/src/main/assets/reference_track.wav --bleed-rms 4171.1

Exit code is non-zero if any take hard-fails (format / clipping / silent / leak).
"""

from __future__ import annotations

import argparse
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, filtfilt

from overdub_analysis.calibration_click import detect_click
from overdub_analysis.gcc_phat import gcc_phat
from overdub_analysis.leak_detect import classify_leak

# Same floor as run_click_gated_sweep.py: at/above this the click is considered present.
_CLICK_QUALITY_FLOOR_DB = 10.0
# GCC-PHAT PSR at/above this against the reference marks a suspicious waveform-correlated leak.
_LEAK_PSR_WARN_DB = 6.0
# int16 rail proximity treated as clipping (true rails are -32768/32767).
_CLIP_ABS = 32700
_WINDOW_MS = 50
# A window is "active" if within 20 dB of the take's loud (p90) windows.
_ACTIVE_REL = 0.1
# Warn if less than this fraction of windows is active (performance gaps).
_ACTIVE_FRACTION_WARN = 0.8
# Segment length for the leak-vs-performance lag-stability discriminator.
_SEGMENT_S = 4.0
# Per-segment lag search half-width around the whole-take peak.
_SEGMENT_LAG_HW_S = 0.100
# Segment lags agreeing within this = machine-stable = a real leak.
_LEAK_LAG_SPREAD_MS = 2.0


def read_wav_mono_16bit(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"{path}: expected mono 16-bit, got {w.getnchannels()}ch {8 * w.getsampwidth()}bit")
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.astype(np.float64), rate


def _bandpass(x: np.ndarray, lo: float, hi: float, fs: int) -> np.ndarray:
    b, a = butter(4, [lo / (fs / 2), hi / (fs / 2)], btype="band")
    return filtfilt(b, a, x)


def window_rms(x: np.ndarray, window: int) -> np.ndarray:
    n = len(x) // window
    if n == 0:
        return np.array([np.sqrt(np.mean(x**2))])
    return np.sqrt(np.mean(x[: n * window].reshape(n, window) ** 2, axis=1))


def vet_take(
    wav_path: Path,
    reference: np.ndarray,
    ref_rate: int,
    band: tuple[float, float],
    bleed_rms: float | None,
) -> bool:
    print(f"--- {wav_path.name} ---")
    take, rate = read_wav_mono_16bit(wav_path)
    ok = True

    if rate != ref_rate:
        print(f"  FORMAT FAIL: take rate {rate} != reference rate {ref_rate}")
        return False
    print(f"  format: mono 16bit {rate}Hz {len(take)} samples {len(take) / rate:.2f}s")

    peak = int(np.max(np.abs(take)))
    clipped = int(np.sum(np.abs(take) >= _CLIP_ABS))
    if clipped > 0:
        print(f"  CLIP FAIL: {clipped} samples at/near the int16 rails (peak {peak}) -- re-record quieter/farther")
        ok = False
    else:
        print(f"  clipping: none (peak {peak} = {20 * np.log10(peak / 32767.0):.1f} dBFS)")

    wrms = window_rms(take, int(rate * _WINDOW_MS / 1000))
    p90 = float(np.percentile(wrms, 90))
    active_mask = wrms >= _ACTIVE_REL * p90
    active_fraction = float(np.mean(active_mask))
    active_rms = float(np.sqrt(np.mean(wrms[active_mask] ** 2))) if active_mask.any() else 0.0
    overall_rms = float(np.sqrt(np.mean(take**2)))
    print(f"  levels: overall_rms={overall_rms:.1f} active_rms={active_rms:.1f} active_fraction={active_fraction:.2f}")
    if overall_rms < 50.0:
        print("  SILENT FAIL: overall RMS below the harness sanity floor -- nothing was performed")
        ok = False
    elif active_fraction < _ACTIVE_FRACTION_WARN:
        print(f"  WARN: active fraction {active_fraction:.2f} < {_ACTIVE_FRACTION_WARN} -- performance gaps make the injection test easier than production")

    # Leak gate: the reference's calibration click must not be detectable in the take.
    det = detect_click(take, rate)
    if det.quality_db >= _CLICK_QUALITY_FLOOR_DB:
        print(f"  LEAK FAIL: calibration click detected in the take (quality {det.quality_db:.1f} dB >= {_CLICK_QUALITY_FLOOR_DB}) -- headphone leak; lower monitor volume / use sealed phones and re-record")
        ok = False
    else:
        print(f"  leak (click): not detected (quality {det.quality_db:.1f} dB < {_CLICK_QUALITY_FLOOR_DB}) -- OK")

    # Leak diagnostic: waveform correlation against the reference, then -- if there's a peak worth
    # explaining -- lag-stability discrimination across segments (overdub_analysis.leak_detect: a
    # leak's lag is machine-stable, a performer's timing jitters; a windowed argmax at the boundary
    # is not a peak). The library function is unit-tested for both failure modes this discriminator
    # once had inline (FFT-range overflow on late segments, edge-pinning false peaks).
    ref_bp = _bandpass(reference, *band, ref_rate)
    take_bp = _bandpass(take, *band, rate)
    r = gcc_phat(ref_bp, take_bp, fs=rate)
    print(f"  leak (gcc-phat psr): {r.psr_db:.1f} dB at lag {(r.offset_seconds or 0.0) * 1000.0:+.1f} ms")
    cls = classify_leak(
        ref_bp, take_bp, rate,
        psr_db=r.psr_db, offset_samples=r.offset_samples,
        leak_psr_warn_db=_LEAK_PSR_WARN_DB,
        segment_s=_SEGMENT_S, lag_hw_s=_SEGMENT_LAG_HW_S, leak_spread_ms=_LEAK_LAG_SPREAD_MS,
    )
    if cls.below_threshold:
        print("  leak (segment consistency): below warn threshold -- OK")
    elif cls.leak:
        lags_str = " ".join(f"{s.lag_ms:+.1f}{'(edge)' if s.edge_pinned else ''}" for s in cls.segment_lags)
        print(f"  LEAK FAIL: segment lags [{lags_str}] machine-stable -- monitored playback is leaking into the mic; lower monitor volume / seal headphones and re-record")
        ok = False
    else:
        lags_str = " ".join(f"{s.lag_ms:+.1f}{'(edge)' if s.edge_pinned else ''}" for s in cls.segment_lags)
        print(f"  leak (segment consistency): lags [{lags_str}] -- no machine-stable peak across segments (a leak would sit at the same interior lag in every segment); the whole-take peak is the in-time performance / coincidental alignment, not a leak (an item-12-relevant finding, not contamination)")

    if bleed_rms is not None and active_rms > 0:
        ratio_db = 20 * np.log10(active_rms / bleed_rms)
        print(f"  vocal-to-bleed ratio: active_rms {active_rms:.1f} vs bleed_rms {bleed_rms:.1f} = {ratio_db:+.1f} dB")

    print(f"  verdict: {'OK' if ok else 'REJECT'}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("wavs", nargs="+", help="vocal take WAV file(s)")
    parser.add_argument("--reference", required=True, help="the click-bearing bundled reference WAV")
    parser.add_argument("--bleed-rms", type=float, default=None, help="baseline cell captured RMS for ratio pinning")
    parser.add_argument("--lo", type=float, default=500.0, help="analysis band low edge Hz (default 500)")
    parser.add_argument("--hi", type=float, default=4000.0, help="analysis band high edge Hz (default 4000)")
    args = parser.parse_args()

    reference, ref_rate = read_wav_mono_16bit(Path(args.reference))
    results = [
        vet_take(Path(w), reference, ref_rate, (args.lo, args.hi), args.bleed_rms) for w in args.wavs
    ]
    n_ok = sum(results)
    print(f"\n{n_ok}/{len(results)} takes OK")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
