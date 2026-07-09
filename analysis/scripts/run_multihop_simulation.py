#!/usr/bin/env python3
"""Test 3 — multi-hop alignment-error Monte Carlo (doc/prototype-plan.md Test 3, revised).

Gate: the 95th percentile of the max pairwise offset between any two tracks
(the original included, at zero error) must stay <= 15 ms at N=4 hops.

Because per-hop noise does not chain under align-to-original (see the model
rationale in overdub_analysis/multihop.py), the interesting outputs are:

  1. **Correlator mechanism** (speaker-bleed sessions, click/timestamp-anchored
     GCC-PHAT): measured per-hop noise std 0.31 ms (Session A), flat
     interference schedule (the vocal study: uncorrelated in-band interference
     does not move the offset). The unknown is the cross-device systematic-bias
     distribution — a placeholder until a second device is measured — so the
     headline output is the **critical uniform bias half-range** at which the
     N=4 gate fails: a requirement on the unknown, not a verdict about it.
  2. **Timestamp mechanism** (headphone sessions, platform-reported latency):
     Session A saw 1-in-9 sessions return a ~+40 ms `getTimestamp` outlier
     (clean reads cluster at ~0.25 ms std). This section sweeps the outlier
     rate (one observation = huge uncertainty) x reads-per-track (median
     taken), and reports where the gate holds. This quantifies the
     "read timestamps repeatedly / take a median" remedy.

Usage (from analysis/ via the venv per CLAUDE.md):
    .venv/Scripts/python.exe scripts/run_multihop_simulation.py
    .venv/Scripts/python.exe scripts/run_multihop_simulation.py --trials 50000
"""

from __future__ import annotations

import argparse

import numpy as np

from overdub_analysis.multihop import HopModel, max_pairwise_offset, simulate_track_errors

GATE_N_HOPS = 4
CHAIN_LENGTHS = (2, 3, 4, 5, 6)


def _p95(model: HopModel, n_tracks: int, trials: int, seed: int) -> float:
    e = simulate_track_errors(model, n_tracks, trials, np.random.default_rng(seed))
    return float(np.percentile(max_pairwise_offset(e), 95))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=20_000, help="Monte Carlo trials per point")
    parser.add_argument("--ceiling-ms", type=float, default=15.0, help="top-level drift ceiling")
    parser.add_argument("--noise-std-ms", type=float, default=0.31,
                        help="per-hop alignment noise std (Session A correlator error std)")
    parser.add_argument("--outlier-ms", type=float, default=39.6,
                        help="timestamp outlier displacement (Session A: +24.5 vs -15.1 cluster)")
    parser.add_argument("--read-noise-std-ms", type=float, default=0.25,
                        help="per-read timestamp noise std (Session A clean-read cluster)")
    parser.add_argument("--bias-max-ms", type=float, default=12.0,
                        help="upper end of the bias half-range scan")
    parser.add_argument("--bias-step-ms", type=float, default=0.25,
                        help="bias half-range scan step for the critical-value search")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    ceiling = args.ceiling_ms

    print("Test 3 multi-hop Monte Carlo -- max pairwise offset, 95th percentile (ms)")
    print(f"gate: p95 <= {ceiling} ms at N={GATE_N_HOPS} hops; trials per point: {args.trials}")
    print()

    # --- Section 1: correlator mechanism, cross-device bias sweep ------------
    print("[1] Correlator mechanism (bleed sessions): per-hop noise std "
          f"{args.noise_std_ms} ms (flat schedule), uniform per-device bias in [-b, +b]")
    print(f"{'b (ms)':>7} " + " ".join(f"{f'N={n}':>8}" for n in CHAIN_LENGTHS) +
          f"   gate at N={GATE_N_HOPS}")
    for b in (0.0, 1.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0):
        model = HopModel(bias_half_range_ms=b, noise_std_ms=args.noise_std_ms)
        p95s = {n: _p95(model, n, args.trials, args.seed) for n in CHAIN_LENGTHS}
        verdict = "PASS" if p95s[GATE_N_HOPS] <= ceiling else "FAIL"
        print(f"{b:>7.2f} " + " ".join(f"{p95s[n]:>8.2f}" for n in CHAIN_LENGTHS) +
              f"   {verdict}")

    # Critical bias half-range at the gate chain length (fine scan).
    critical = None
    last_pass = 0.0
    for b in np.arange(0.0, args.bias_max_ms + 1e-9, args.bias_step_ms):
        model = HopModel(bias_half_range_ms=float(b), noise_std_ms=args.noise_std_ms)
        if _p95(model, GATE_N_HOPS, args.trials, args.seed) <= ceiling:
            last_pass = float(b)
        else:
            critical = float(b)
            break
    print()
    if critical is None:
        print(f"critical bias half-range: > {args.bias_max_ms} ms (gate never failed in scan)")
    else:
        print(f"critical bias half-range at N={GATE_N_HOPS}: gate holds through b = "
              f"{last_pass:.2f} ms, fails at b = {critical:.2f} ms")
        print("=> REQUIREMENT on cross-device bias (placeholder distribution -- uniform): "
              f"per-device systematic biases must stay within ~+/-{last_pass:.1f} ms of each "
              "other for the gate to hold with no calibration step. A moto-g(20)-class "
              "~100 ms bias fails it outright; heterogeneous chains need per-device "
              "calibration/self-check (already contemplated in design-summary.md).")

    # --- Section 2: timestamp mechanism, outlier rate x reads-per-track ------
    print()
    print("[2] Timestamp mechanism (headphone sessions): read noise std "
          f"{args.read_noise_std_ms} ms, outlier displacement +/-{args.outlier_ms} ms "
          "(random sign), median of m reads; zero cross-device bias (isolates the outlier "
          f"effect); N={GATE_N_HOPS}")
    print(f"{'outlier p':>10} " + " ".join(f"{f'm={m}':>8}" for m in (1, 3, 5, 7)))
    for p in (1.0 / 9.0, 1.0 / 20.0, 1.0 / 50.0, 1.0 / 100.0):
        cells = []
        for m in (1, 3, 5, 7):
            model = HopModel(
                noise_std_ms=args.noise_std_ms,
                outlier_prob=p,
                outlier_ms=args.outlier_ms,
                outlier_signed=True,
                reads_per_track=m,
                read_noise_std_ms=args.read_noise_std_ms,
            )
            p95 = _p95(model, GATE_N_HOPS, args.trials, args.seed)
            cells.append(f"{p95:>8.2f}")
        print(f"{p:>10.4f} " + " ".join(cells))
    print("(cells are p95 max pairwise offset in ms; PASS means <= "
          f"{ceiling} ms. The Session A observed rate is 1/9 from a single "
          "occurrence -- treat the rate axis as the uncertainty, not a measurement.)")

    print()
    print("Caveats: bias distribution is a PLACEHOLDER (uniform) until a second device is "
          "measured; the outlier rate rests on one observation; interference growth is "
          "modeled flat per the vocal study (uncorrelated interference does not move the "
          "anchored offset) -- correlated multi-stem bleed is unmeasured and would need "
          "the growth knob revisited.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
