# Test 3 — Do we still need a multi-hop Monte Carlo? (2026-07-08)

## Short answer

Probably not. Test 3 is a leftover from the review's original worry ("does per-hop
error compound into drift?"), and the 2026-07-08 model correction already killed
the interesting version of that question analytically: under align-to-original,
misalignment between any two tracks is the difference of two independent draws,
not a random walk. What the revised test proposes to simulate is the residue —
bias differences plus position-dependent noise — and each piece has since become
either trivial (closed-form) or unsimulatable (no data to drive it).

## The three terms, examined

### 1. Noise term — closed-form, and measured tiny

Max pairwise offset among N tracks with iid noise is the **range of N draws** —
standard order statistics (the expected range of N iid normals is σ times a
tabulated constant, ~2.06 at N=4; Tippett-1925-era textbook material, no
simulation needed). With Session A's measured per-session correlator error std of
**0.31 ms** (`test2-sweep-results.md`, Session A: 11/11 PASS), the noise
contribution at N=4 is well under 1 ms against the 15 ms ceiling. A 1000-trial
Monte Carlo would rediscover multiplication.

### 2. Interference-growth term — mostly evaporated

Test 3's revised spec has per-hop variance growing with chain position, magnitude
to be supplied by the vocal-injection study (Test 2 step 3). But that study's
headline was that the offset is **immune**: unchanged by even one sample through
+24 dB in-band vocal-to-bleed ratio, with ~36 dB of margin at the realistic ratio
(−12.2 dB). The variance schedule Test 3 was going to consume is approximately
flat at zero; the failure mode that does appear at extreme ratios is click
burial, not alignment pulling — a calibration-anchor concern, not a chain-length
one.

**Caveat:** the injection study used one vocal over one stem's bleed, not the
k−1 stacked stems hop k would actually hear. Stacked stems are the same class of
tempo-correlated, waveform-uncorrelated interference, so the same immunity is
expected — but that is an inference, not a measurement.

### 3. Per-device bias term — the real risk, and Monte Carlo can't touch it

Pairwise misalignment between heterogeneous devices is dominated by
(b_i − b_j), and bias data exists for exactly one device. Simulating draws from
a placeholder distribution just returns the placeholder: assume bias spread R,
get max pairwise ≈ R. Once a second device's data exists, "does the measured
cross-device bias spread exceed ~15 ms" is answered by **subtraction**, not
simulation.

## The one thing worth salvaging: the timestamp fat tail

Session A's 1-in-9 ~40 ms `getTimestamp` outlier means a product mechanism
trusting a *single* timestamp read gives

> P(≥ 1 bad track in a 4-hop chain) ≈ 1 − (8/9)⁴ ≈ **38%**

on the best-case device. That alone mandates repeated reads / median-of-reads —
and it, too, is arithmetic (a binomial), not a simulation result.

## Recommendation

Replace Test 3 with:

1. **A half-page closed-form budget note** — range-of-N noise (order statistics
   on the measured 0.31 ms std) + a bias-difference bound + the outlier
   binomial above.
2. **A hard gate on measured cross-device bias spread** once device #2 exists
   (pairwise |b_i − b_j| ≤ 15 ms budget check by direct subtraction).
3. **Monte Carlo held in reserve** only if the eventual error model turns
   genuinely non-analytic — e.g. mixed mechanisms per hop (bleed on some
   devices, timestamps on others) with correlated failure modes.

## Confidence

High on the statistics — range-of-N and the binomial are standard results, not
modeling choices. The soft spot is the stacked-stem extrapolation from the
single-vocal injection study (inference, not measurement); if it matters, a
stacked-stem variant of `run_vocal_injection.py` is cheaper than a Monte Carlo
and would measure the actual quantity.

## Disposition (2026-07-08) — accepted; applied to the plan docs

The Monte Carlo had already been built and run by the time of this assessment
(`overdub_analysis/multihop.py` + `run_multihop_simulation.py`, committed
d52deb9); its outputs match the closed forms point-for-point — noise
3.63σ ≈ 1.13 ms at N=4; critical bias half-range 15/1.80 ≈ 8.3 ms vs. the
scan's 8.25–8.50 bracket; the timestamp binomials above — and
`tests/test_multihop.py` asserts the simulation against those same closed
forms, so note and simulation agree by construction. Applied per the
recommendation:

1. `prototype-plan.md` Test 3 now rests its verdict on the arithmetic, with
   the Monte Carlo demoted to a cross-check and **kept in reserve** for the
   mixed-mechanism case (recommendation 3) rather than deleted.
2. The median-of-5 framing was corrected to a **knife-edge** pass (chain
   outlier rate ~4.5% vs. the gate's 5%, on a one-observation rate) — the
   sim's 1.3 ms cell had hidden the cliff this note's binomial exposes.
3. The device-#2 bias gate is recorded as **subtraction** against the ~±8 ms
   budget, not re-simulation.
4. The stacked-stem caveat is recorded in Test 3 with the cheap measurement
   path (a stacked-stem `run_vocal_injection.py` variant).
5. The outlier-rate measurement this note's binomial makes load-bearing is
   folded into the interim timestamp-variance plan (`prototype-plan.md`
   Test 1a; `test2-step2-plan.md` item 13), runnable while the rig is
   delayed.
