#!/usr/bin/env python3
"""Diagnose why GCC-PHAT fails on real-bleed captures (test2-sweep-results.md, "GCC-PHAT
offline pass"). Splits two candidate causes empirically rather than guessing which fix to try:

  (a) Reference quasi-periodicity -- the beatbox clip has strong rhythmic autocorrelation
      sidelobes that collapse PSR and let a sidelobe win argmax, independent of the capture.
  (b) Band-limited bleed -- the phone speaker rolls off highs, so PHAT's equal-per-band
      weighting amplifies noise-dominated high bands and corrupts the correlation.

Two measurements, both read-only over the existing reference + a representative capture:

  1. Reference autocorrelation PSR. Correlate the reference against a synthetically delayed
     copy of ITSELF (no mic, no speaker) at several ms-scale delays. If PSR is already low
     here, cause (a) is confirmed -- the reference is too periodic for GCC-PHAT regardless of
     the capture. If PSR is high, cause (a) is ruled out and the problem is the capture path.

  2. Spectral envelope: capture vs reference. Compute the mean power per band for the
     reference and for a real capture, and print the per-band ratio (capture/ref) in dB. This
     is the approximate speaker x room x mic transfer-function magnitude. If the ratio drops
     sharply at high frequencies, the bleed is band-limited -- cause (b).

Usage (from analysis/ via the venv):
    .venv/Scripts/python.exe scripts/diagnose_gcc_phat.py \\
        --reference ../harness/src/main/assets/reference_track.wav \\
        --sweep-dir sweep_data

If --capture is omitted, the baseline cell (conversational_armslength_faceup_none) is
auto-selected from --sweep-dir; failing that, the first .wav alphabetically.
"""

from __future__ import annotations

import argparse
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, filtfilt

from overdub_analysis.gcc_phat import gcc_phat

_PSR_CONFIDENT_DB = 10.0
_PSR_MINIMUM_DB = 6.0

# ms-scale synthetic delays (samples at 48 kHz) spanning the plausible speaker->mic
# round-trip range and a bit beyond. A real alignment offset would sit somewhere in here.
_DEFAULT_DELAYS_MS = [5, 10, 20, 40, 80, 120]

# Octave-ish bands (Hz) for the spectral-envelope comparison.
_BAND_EDGES_HZ = [0, 250, 500, 1000, 2000, 4000, 8000, 16000, 24000]

# Candidate bandpass bands (Hz) for the band-limited PHAT validation. The spectral envelope
# above showed the usable-SNR band is roughly 500 Hz - 4 kHz; these bracket it.
_BANDPASS_BANDS_HZ = [(500, 4000), (300, 4000), (250, 4000), (500, 8000), (1000, 4000)]


def _read_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        framerate = w.getframerate()
        raw = w.readframes(w.getnframes())
    if sampwidth != 2:
        raise ValueError(f"{path}: only 16-bit PCM is supported (got {sampwidth * 8}-bit)")
    data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, framerate


def _delay_signal(x: np.ndarray, d: int) -> np.ndarray:
    """Return x shifted right by d samples (positive delay / lag), zero-filled at the start."""
    if d <= 0:
        return x.copy()
    out = np.zeros_like(x)
    out[d:] = x[:-d]
    return out


def _verdict(psr_db: float) -> str:
    if psr_db >= _PSR_CONFIDENT_DB:
        return "confident"
    if psr_db >= _PSR_MINIMUM_DB:
        return "minimum"
    return "below"


def _band_powers(spec: np.ndarray, freqs: np.ndarray) -> list[tuple[str, float]]:
    """Mean power (10*log10) per band, given an rfft magnitude spectrum and its freqs."""
    power = spec**2
    out: list[tuple[str, float]] = []
    for lo, hi in zip(_BAND_EDGES_HZ, _BAND_EDGES_HZ[1:]):
        mask = (freqs >= lo) & (freqs < hi)
        p = float(power[mask].mean()) if mask.any() else 1e-30
        p = max(p, 1e-30)
        label = f"{lo//1000}k-{hi//1000}k" if lo >= 1000 else f"{lo}-{hi}"
        out.append((label, 10.0 * np.log10(p)))
    return out


def _autocorr_psr_section(ref: np.ndarray, fs: int, delays_ms: list[float]) -> None:
    print("=== 1. Reference autocorrelation PSR (ref vs delayed ref, no capture path) ===")
    print("If PSR is low here, cause (a): the reference is too periodic for GCC-PHAT.")
    print("If PSR is high, cause (a) ruled out -- the problem is the capture path.")
    print()
    print(f"{'delay_ms':>9} {'delay_samp':>11} {'off_samp':>9} {'psr_db':>8} {'verdict':<10}")
    print("-" * 55)
    for ms in delays_ms:
        d = int(round(ms * 1e-3 * fs))
        delayed = _delay_signal(ref, d)
        res = gcc_phat(ref, delayed, fs=fs)
        print(f"{ms:>9.1f} {d:>11} {res.offset_samples:>9} {res.psr_db:>8.1f} {_verdict(res.psr_db):<10}")
    print()


def _spectrum_section(ref: np.ndarray, cap: np.ndarray, fs: int, cap_name: str) -> None:
    print("=== 2. Spectral envelope: capture vs reference (speaker x room x mic transfer) ===")
    print(f"capture: {cap_name}")
    print("Per-band mean power (dB), and capture-minus-reference (a negative drop at HF =")
    print("band-limited bleed -> cause (b)).")
    print()
    n = min(len(ref), len(cap))
    # Truncate to the same length and window (Hann) to reduce edge/leakage artifacts.
    win = np.hanning(n)
    x = ref[:n] * win
    y = cap[:n] * win
    nfft = 1 << int(np.ceil(np.log2(n)))
    X = np.abs(np.fft.rfft(x, n=nfft))
    Y = np.abs(np.fft.rfft(y, n=nfft))
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
    ref_bands = dict(_band_powers(X, freqs))
    cap_bands = dict(_band_powers(Y, freqs))
    print(f"{'band_Hz':<12} {'ref_dB':>8} {'cap_dB':>8} {'cap-ref_dB':>11}")
    print("-" * 45)
    for band in ref_bands:
        r = ref_bands[band]
        c = cap_bands[band]
        print(f"{band:<12} {r:>8.1f} {c:>8.1f} {c - r:>11.1f}")
    # Summary: HF (>= 8 kHz) vs mid (1-4 kHz) drop.
    hf_ref = ref_bands.get("8k-16k", 0.0)
    hf_cap = cap_bands.get("8k-16k", 0.0)
    mid_ref = ref_bands.get("1k-2k", 0.0)
    mid_cap = cap_bands.get("1k-2k", 0.0)
    ref_hf_drop = hf_ref - mid_ref
    cap_hf_drop = hf_cap - mid_cap
    print()
    print(f"ref  HF(8-16k) minus mid(1-2k): {ref_hf_drop:+.1f} dB (reference's own HF content)")
    print(f"cap  HF(8-16k) minus mid(1-2k): {cap_hf_drop:+.1f} dB (capture's HF content)")
    print(
        f"extra HF rolloff in capture vs ref: {cap_hf_drop - ref_hf_drop:+.1f} dB "
        f"(large negative => speaker band-limits the bleed => cause (b))"
    )


def _bandpass(x: np.ndarray, lo: float, hi: float, fs: int) -> np.ndarray:
    """Zero-phase Butterworth bandpass (4th-order), filtfilt for no group-delay offset."""
    nyq = 0.5 * fs
    wn = [lo / nyq, hi / nyq]
    b, a = butter(4, wn, btype="band")
    return filtfilt(b, a, x)


def _bandlimited_phat_section(ref: np.ndarray, cap: np.ndarray, fs: int, cap_name: str) -> None:
    print("=== 3. Band-limited PHAT validation (fix candidate for cause (b)) ===")
    print("Bandpass both signals to each candidate band, then run GCC-PHAT. If PSR recovers to")
    print(">= 6 dB and the offset is a consistent positive value across bands, the fix is")
    print("validated: restrict the correlation to the usable-SNR band.")
    print(f"capture: {cap_name}")
    print()
    print(f"{'band_Hz':<12} {'off_samp':>9} {'off_ms':>8} {'psr_db':>8} {'verdict':<10}")
    print("-" * 55)
    for lo, hi in _BANDPASS_BANDS_HZ:
        try:
            rf = _bandpass(ref, lo, hi, fs)
            cf = _bandpass(cap, lo, hi, fs)
            res = gcc_phat(rf, cf, fs=fs)
            off_ms = (res.offset_seconds or 0.0) * 1000.0
            print(f"{f'{lo}-{hi}':<12} {res.offset_samples:>9} {off_ms:>8.2f} {res.psr_db:>8.1f} {_verdict(res.psr_db):<10}")
        except Exception as e:  # noqa: BLE001 - report and continue to the next band
            print(f"{f'{lo}-{hi}':<12}  ERROR: {e}")
    print()


def _select_capture(sweep_dir: Path, explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.exists() and not p.is_absolute():
            p = sweep_dir / explicit
        if not p.exists():
            raise FileNotFoundError(f"capture not found: {explicit}")
        return p
    # Prefer the baseline realistic cell.
    for p in sorted(sweep_dir.glob("conversational_armslength_faceup_none*.wav")):
        return p
    wavs = sorted(sweep_dir.glob("*.wav"))
    if not wavs:
        raise FileNotFoundError(f"no .wav in {sweep_dir}")
    return wavs[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference",
        default="../harness/src/main/assets/reference_track.wav",
        help="reference track WAV",
    )
    parser.add_argument("--sweep-dir", default="sweep_data", help="dir of captures")
    parser.add_argument(
        "--capture",
        default=None,
        help="specific capture WAV (default: baseline cell from --sweep-dir)",
    )
    parser.add_argument(
        "--delays-ms",
        default=",".join(str(d) for d in _DEFAULT_DELAYS_MS),
        help="comma-separated synthetic delays in ms for the autocorrelation PSR test",
    )
    args = parser.parse_args()

    delays_ms = [float(s) for s in args.delays_ms.split(",") if s.strip()]

    ref, ref_rate = _read_wav_mono(Path(args.reference))
    print(f"reference: {args.reference}  {len(ref)} samples  {ref_rate} Hz  {len(ref)/ref_rate:.2f}s")
    print()

    cap_path = _select_capture(Path(args.sweep_dir), args.capture)
    cap, cap_rate = _read_wav_mono(cap_path)
    if cap_rate != ref_rate:
        print(f"  WARN capture rate {cap_rate} Hz != reference {ref_rate} Hz -- spectral comparison still computed but rates should match")
    print(f"capture:   {cap_path.name}  {len(cap)} samples  {cap_rate} Hz  {len(cap)/cap_rate:.2f}s")
    print()

    _autocorr_psr_section(ref, ref_rate, delays_ms)
    _spectrum_section(ref, cap, ref_rate, cap_path.name)
    _bandlimited_phat_section(ref, cap, ref_rate, cap_path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
