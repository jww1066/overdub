#!/usr/bin/env python3
"""Map a reference track's self-similarity peaks (alias risk for GCC-PHAT).

Why: the 2026-07-08 calibration-click cross-check (`doc/test2-sweep-results.md`)
showed band-limited GCC-PHAT against a rhythmic beatbox reference can lock onto a
*beat-period alias* -- a self-similarity peak of the reference offset ~one
inter-onset period from the true alignment, with a high PSR that PSR/lag-window
gates do not reject. This script measures that risk directly: it computes the
band-limited *autocorrelation* of the reference and prints the largest off-zero
peaks (lag, magnitude relative to the zero-lag peak). A strong peak at lag L
means any correlation-based alignment against this reference can alias by +/-L,
so a lag window alone is insufficient and an independent aperiodic ground truth
(the calibration click) must gate the alignment. Useful when choosing/qualifying
a reference recording, not just for boots.wav.

Uses the **plain (non-PHAT) autocorrelation**, deliberately: PHAT of a signal
with itself divides the cross-spectrum by its own magnitude, yielding a
mathematically perfect impulse regardless of how periodic the signal is
(measured: sidelobes at -152 dB for boots.wav) -- it can never reveal alias
risk. Rhythmic self-similarity shows up in the ordinary autocorrelation, which
is what competes with the true peak once the capture side is noisy/band-limited.

Usage:
    python scripts/check_reference_periodicity.py ../boots_48k_mono.wav
    python scripts/check_reference_periodicity.py ref.wav --lo 500 --hi 4000 --top 8
"""

from __future__ import annotations

import argparse
import wave

import numpy as np
from scipy.signal import butter, sosfiltfilt


def read_wav_mono(path: str) -> tuple[np.ndarray, int]:
    with wave.open(path, "rb") as w:
        channels = w.getnchannels()
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
        sampwidth = w.getsampwidth()
    if sampwidth != 2:
        raise ValueError(f"{path}: expected 16-bit PCM")
    data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", help="reference WAV (mono or downmixed)")
    parser.add_argument("--lo", type=float, default=500.0, help="bandpass low edge (Hz)")
    parser.add_argument("--hi", type=float, default=4000.0, help="bandpass high edge (Hz)")
    parser.add_argument("--top", type=int, default=8, help="how many off-zero peaks to print")
    parser.add_argument(
        "--max-lag-ms", type=float, default=500.0, help="scan lags up to this (either sign)"
    )
    parser.add_argument(
        "--exclusion-ms",
        type=float,
        default=5.0,
        help="half-width excluded around zero lag and around each reported peak",
    )
    args = parser.parse_args()

    ref, rate = read_wav_mono(args.reference)
    sos = butter(4, [args.lo, args.hi], btype="bandpass", fs=rate, output="sos")
    ref_bp = sosfiltfilt(sos, ref)

    nfft = 1 << int(np.ceil(np.log2(2 * ref_bp.size - 1)))
    X = np.fft.fft(ref_bp, n=nfft)
    ac = np.real(np.fft.ifft(X * np.conj(X)))
    idx = np.arange(nfft)
    lag = np.where(idx > nfft // 2, idx - nfft, idx)

    max_lag = round(args.max_lag_ms * 1e-3 * rate)
    excl = round(args.exclusion_ms * 1e-3 * rate)
    in_scan = (np.abs(lag) <= max_lag) & (np.abs(lag) > excl)

    zero_peak = float(ac[0])
    mag = np.abs(ac).copy()
    mag[~in_scan] = 0.0

    print(f"reference: {args.reference}  {ref.size} samples  {rate} Hz  band {args.lo:.0f}-{args.hi:.0f} Hz")
    print(f"zero-lag peak: {zero_peak:.4f}  (off-zero peaks below are relative to it)")
    print(f"{'rank':>4} {'lag_samples':>12} {'lag_ms':>9} {'rel_dB':>8}")
    for rank in range(1, args.top + 1):
        i = int(np.argmax(mag))
        if mag[i] <= 0:
            break
        rel_db = 20.0 * np.log10(mag[i] / zero_peak)
        print(f"{rank:>4} {int(lag[i]):>12} {1000.0 * lag[i] / rate:>9.2f} {rel_db:>8.1f}")
        lo_i = max(0, i - excl)
        mag[lo_i : i + excl + 1] = 0.0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
