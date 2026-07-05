#!/usr/bin/env python3
"""Measure the width of the GCC-PHAT main correlation lobe around its peak.

`gcc_phat`'s PSR metric treats everything outside a `psr_exclusion`-sample
window around the peak as "sidelobe." If the main lobe itself is wider than
that window, genuine main-lobe shoulder samples get miscounted as the
sidelobe, artificially depressing PSR. This script prints the (clean,
noise-free) correlation magnitude at each offset around the peak so the
`psr_exclusion` default in `gcc_phat.py` can be sized against the real lobe
shape for the click-train signal class the tests use, rather than guessed.

Usage:
    python scripts/measure_main_lobe_width.py
    python scripts/measure_main_lobe_width.py --click-width 8 --span 10
"""

from __future__ import annotations

import argparse

import numpy as np

from overdub_analysis import broadband_click_train, delay
from overdub_analysis.gcc_phat import _cross_spectrum_phat

DEFAULT_FS = 48_000.0
DEFAULT_DURATION_S = 1.0
DEFAULT_PERIOD = 1000
DEFAULT_SEED = 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--click-width", type=int, default=8, help="click width in samples")
    parser.add_argument("--delay", type=int, default=250, help="injected delay in samples")
    parser.add_argument("--span", type=int, default=10, help="offsets to print either side of the peak")
    parser.add_argument("--fs", type=float, default=DEFAULT_FS, help="sample rate (Hz)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="RNG seed")
    args = parser.parse_args()

    n = int(round(args.fs * DEFAULT_DURATION_S))
    ref = broadband_click_train(
        n,
        period=DEFAULT_PERIOD,
        click_width=args.click_width,
        rng=np.random.default_rng(args.seed),
    )
    mic = delay(ref, args.delay)

    nfft = 1 << int(np.ceil(np.log2(ref.size + mic.size - 1)))
    gcc = _cross_spectrum_phat(ref, mic, nfft, eps=1e-12)
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


if __name__ == "__main__":
    raise SystemExit(main())
