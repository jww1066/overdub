#!/usr/bin/env python3
"""Measure the width of the GCC-PHAT main correlation lobe around its peak.

`gcc_phat`'s PSR metric treats everything outside a `psr_exclusion`-sample
window around the peak as "sidelobe." If the main lobe itself is wider than
that window, genuine main-lobe shoulder samples get miscounted as the
sidelobe, artificially depressing PSR.

Two modes:

* **Click-train (default):** prints the clean correlation magnitude around the
  peak for the broadband click-train signal class the unit tests use, so the
  `psr_exclusion` default can be sized against that lobe rather than guessed.

* **Band-limited real signal (`--reference <wav>`):** next-steps item 7b. Band-
  passing to a narrow band (e.g. 500-4000 Hz) *widens* the main lobe (half-width
  ~ 1/(2*bandwidth)). This mode band-passes the real reference (and a real
  capture) and reports the -3/-6 dB and first-null half-widths, then prints the
  PSR you'd get at a range of `psr_exclusion` values inside a plausible lag
  window -- so recalibrating the exclusion is data-driven, not guessed. This is
  the case that made the band-limited sweep report a near-constant ~11 dB PSR
  (the fixed 2-sample exclusion was measuring the filter's lobe, not the peak).

Usage:
    python scripts/measure_main_lobe_width.py                      # click-train
    python scripts/measure_main_lobe_width.py --click-width 8 --span 10
    python scripts/measure_main_lobe_width.py \\
        --reference ../harness/src/main/assets/reference_track.wav \\
        --sweep-dir sweep_data --lo 500 --hi 4000                  # band-limited
"""

from __future__ import annotations

import argparse
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, filtfilt

from overdub_analysis import broadband_click_train, delay
from overdub_analysis.gcc_phat import _cross_spectrum_phat, gcc_phat

DEFAULT_FS = 48_000.0
DEFAULT_DURATION_S = 1.0
DEFAULT_PERIOD = 1000
DEFAULT_SEED = 0
_EPS = 1e-12


# --------------------------------------------------------------------------- #
# Click-train mode (original behavior)
# --------------------------------------------------------------------------- #
def _click_train_mode(args: argparse.Namespace) -> int:
    n = int(round(args.fs * DEFAULT_DURATION_S))
    ref = broadband_click_train(
        n, period=DEFAULT_PERIOD, click_width=args.click_width,
        rng=np.random.default_rng(args.seed),
    )
    mic = delay(ref, args.delay)

    nfft = 1 << int(np.ceil(np.log2(ref.size + mic.size - 1)))
    gcc = _cross_spectrum_phat(ref, mic, nfft, eps=_EPS)
    peak_idx = int(np.argmax(gcc))
    peak = gcc[peak_idx]

    print(f"click_width={args.click_width}  peak index={peak_idx}  peak={peak:.4f}")
    print(f"{'offset':>7} {'magnitude':>10} {'dB rel. peak':>14}")
    for offset in range(-args.span, args.span + 1):
        idx = (peak_idx + offset) % nfft
        mag = gcc[idx]
        db = 20.0 * np.log10(abs(mag) / abs(peak)) if peak != 0 else float("-inf")
        marker = "  <- peak" if offset == 0 else ""
        print(f"{offset:7d} {mag:10.4f} {db:14.1f}{marker}")
    return 0


# --------------------------------------------------------------------------- #
# Band-limited real-signal mode (item 7b)
# --------------------------------------------------------------------------- #
def _read_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        ch, sw, fr = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if sw != 2:
        raise ValueError(f"{path}: only 16-bit PCM supported (got {sw * 8}-bit)")
    data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, fr


def _bandpass(x: np.ndarray, lo: float, hi: float, fs: int) -> np.ndarray:
    nyq = 0.5 * fs
    b, a = butter(4, [lo / nyq, hi / nyq], btype="band")
    return filtfilt(b, a, x)


def _phat_corr(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    nfft = 1 << int(np.ceil(np.log2(x.size + y.size - 1)))
    return _cross_spectrum_phat(x, y, nfft, _EPS)


def _lobe_half_widths(gcc: np.ndarray, peak_idx: int, max_half: int = 128) -> dict[str, int]:
    """Half-widths (samples) from the peak: -3 dB, -6 dB, and the first null."""
    n = gcc.size
    centered = np.roll(gcc, -peak_idx)  # peak now at index 0
    peak = centered[0]

    def half_at(frac: float) -> int:
        thresh = peak * frac
        for k in range(1, max_half + 1):
            if centered[k] < thresh and centered[n - k] < thresh:
                return k
        return max_half

    def first_null() -> int:
        for k in range(1, max_half):
            if centered[k + 1] > centered[k]:  # correlation started rising again
                return k
        return max_half

    return {
        "half_-3dB": half_at(10 ** (-3 / 20)),
        "half_-6dB": half_at(10 ** (-6 / 20)),
        "first_null": first_null(),
    }


def _report_lobe(title: str, x: np.ndarray, y: np.ndarray, plausible: int) -> int:
    gcc = _phat_corr(x, y)
    n = gcc.size
    idx = np.arange(n)
    offset = -np.where(idx > n // 2, idx - n, idx)
    peak_idx = int(np.argmax(np.where(np.abs(offset) <= plausible, gcc, -np.inf)))
    w = _lobe_half_widths(gcc, peak_idx)
    print(f"  {title}: peak offset {int(offset[peak_idx])} samp; half-width "
          f"-3dB={w['half_-3dB']} -6dB={w['half_-6dB']} first_null={w['first_null']} samples")
    return w["first_null"]


def _select_capture(sweep_dir: Path, explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else sweep_dir / explicit
    hits = sorted(sweep_dir.glob("conversational_armslength_faceup_none*.wav")) or \
        sorted(sweep_dir.glob("*.wav"))
    return hits[0] if hits else None


def _band_limited_mode(args: argparse.Namespace) -> int:
    ref, fs = _read_wav_mono(Path(args.reference))
    ref_bp = _bandpass(ref, args.lo, args.hi, fs)
    plausible = int(0.3 * fs)  # 0-300 ms plausible speaker->mic round-trip

    print(f"reference {len(ref)} samp @ {fs} Hz; band {args.lo:.0f}-{args.hi:.0f} Hz")
    print(f"theoretical main-lobe half-width ~ 1/(2*BW) = "
          f"{fs / (2 * (args.hi - args.lo)):.1f} samples\n")
    print("Main-lobe width:")

    delayed = np.zeros_like(ref_bp)
    d = args.delay
    delayed[d:] = ref_bp[:-d]
    null_auto = _report_lobe("ref autocorr (clean)", ref_bp, delayed, plausible)

    cap_path = _select_capture(Path(args.sweep_dir), args.capture)
    null_cap = null_auto
    cap_bp = None
    if cap_path is not None and cap_path.exists():
        cap, _ = _read_wav_mono(cap_path)
        cap_bp = _bandpass(cap, args.lo, args.hi, fs)
        null_cap = _report_lobe(f"ref-vs-capture ({cap_path.name})", ref_bp, cap_bp, plausible)

    recommended = max(null_auto, null_cap)
    print(f"\nRecommended psr_exclusion >= first-null half-width = {recommended} samples "
          f"(current gcc_phat default is 2).")

    if cap_bp is not None:
        print(f"\nPSR of {cap_path.name} vs psr_exclusion (lag_window 0-300 ms):")
        print(f"  {'exclusion':>9} {'psr_db':>8} {'offset_ms':>10}")
        seen = set()
        for ex in [2, max(1, recommended // 2), recommended, recommended * 2, recommended * 3]:
            if ex in seen:
                continue
            seen.add(ex)
            r = gcc_phat(ref_bp, cap_bp, fs=fs, psr_exclusion=ex, lag_window=(0, plausible))
            print(f"  {ex:>9} {r.psr_db:>8.1f} {r.offset_seconds * 1000:>10.2f}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--click-width", type=int, default=8, help="click width in samples (click mode)")
    parser.add_argument("--delay", type=int, default=250, help="injected delay in samples")
    parser.add_argument("--span", type=int, default=10, help="offsets to print either side (click mode)")
    parser.add_argument("--fs", type=float, default=DEFAULT_FS, help="sample rate (Hz, click mode)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="RNG seed (click mode)")
    # Band-limited real-signal mode:
    parser.add_argument("--reference", default=None, help="real reference WAV -> band-limited mode")
    parser.add_argument("--sweep-dir", default="sweep_data", help="dir of captures (band-limited mode)")
    parser.add_argument("--capture", default=None, help="specific capture (band-limited mode)")
    parser.add_argument("--lo", type=float, default=500.0, help="bandpass low edge (Hz)")
    parser.add_argument("--hi", type=float, default=4000.0, help="bandpass high edge (Hz)")
    args = parser.parse_args()

    if args.reference:
        return _band_limited_mode(args)
    return _click_train_mode(args)


if __name__ == "__main__":
    raise SystemExit(main())
