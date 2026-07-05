#!/usr/bin/env python3
"""Sweep noise level and report the SNR at which GCC-PHAT's PSR crosses 6 dB.

This is the "SNR floor" output of Test 2 step 1 (`doc/prototype-plan.md`):
an *output of the test*, not a threshold to hit. Run it to record the floor
for the current synthetic signal and GCC-PHAT implementation, e.g. before
porting the algorithm to Kotlin/C++ and re-checking it there.

Usage:
    python scripts/sweep_snr_floor.py
    python scripts/sweep_snr_floor.py --delay 250 --from 40 --to -60 --step 2
"""

from __future__ import annotations

import argparse

import numpy as np

from overdub_analysis import (
    add_noise_at_snr,
    broadband_click_train,
    delay,
    gcc_phat,
)

DEFAULT_FS = 48_000.0
DEFAULT_DURATION_S = 1.0
DEFAULT_PERIOD = 1000
DEFAULT_CLICK_WIDTH = 8
DEFAULT_SEED = 0
DEFAULT_PSR_FLOOR_DB = 6.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delay", type=int, default=250, help="injected delay in samples")
    parser.add_argument("--from", dest="snr_hi", type=float, default=40.0, help="start SNR (dB)")
    parser.add_argument("--to", dest="snr_lo", type=float, default=-60.0, help="end SNR (dB)")
    parser.add_argument("--step", type=float, default=-2.0, help="SNR step (dB, negative to sweep down)")
    parser.add_argument("--floor", type=float, default=DEFAULT_PSR_FLOOR_DB, help="PSR crossing to find (dB)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="RNG seed")
    parser.add_argument("--fs", type=float, default=DEFAULT_FS, help="sample rate (Hz)")
    args = parser.parse_args()

    if args.step >= 0:
        parser.error("--step must be negative to sweep downward (or rewrite to sweep up)")

    n = int(round(args.fs * DEFAULT_DURATION_S))
    ref = broadband_click_train(
        n, period=DEFAULT_PERIOD, click_width=DEFAULT_CLICK_WIDTH, rng=np.random.default_rng(args.seed)
    )
    mic_clean = delay(ref, args.delay)

    snrs = np.arange(args.snr_hi, args.snr_lo - 0.001, args.step)
    print(f"{'SNR (dB)':>10} {'PSR (dB)':>10} {'offset':>8}  correct?")
    crossing: float | None = None
    for snr in snrs:
        mic = add_noise_at_snr(mic_clean, float(snr), np.random.default_rng(args.seed))
        result = gcc_phat(ref, mic, fs=args.fs)
        correct = abs(result.offset_samples - args.delay) <= 1
        print(f"{snr:10.1f} {result.psr_db:10.1f} {result.offset_samples:8d}  {correct}")
        if crossing is None and result.psr_db < args.floor:
            crossing = float(snr)

    print()
    if crossing is None:
        print(f"PSR never crossed {args.floor} dB down to {snrs[-1]:.1f} dB SNR "
              f"(algorithm extremely robust for this signal class).")
        return 0
    print(f"PSR crossed {args.floor} dB at SNR ~ {crossing:.1f} dB.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
