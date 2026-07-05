# overdub-analysis

Offline signal-processing prototyping and validation for the Overdub app — kept separate from the
Android/Kotlin app so Python tooling (venv, pytest, linters) doesn't collide with Gradle/Kotlin
tooling in the rest of the repo.

Scope for now: Test 2 (step 1) of [`../doc/prototype-plan.md`](../doc/prototype-plan.md) — synthetic
validation of GCC-PHAT time-delay estimation (FFT cross-spectrum + PHAT weighting) before any of it
is ported to (or re-verified against) real on-device behavior.

## What's here

- `src/overdub_analysis/gcc_phat.py` — the GCC-PHAT core: `gcc_phat(reference, mic, fs)` returns
  the estimated delay (samples + seconds) and a peak-to-sidelobe ratio (PSR) in dB.
- `src/overdub_analysis/synth.py` — synthetic helpers: a broadband click-train reference, an
  integer-sample `delay`, and `add_noise_at_snr` for controlled SNR.
- `tests/test_gcc_phat.py` — the step-1 correctness gate (≥20 dB SNR → ±1 sample, PSR ≥10 dB),
  the SNR-floor sweep, and edge cases. These fixtures double as port-correctness regression tests
  when the algorithm is later ported to Kotlin/C++ on-device.
- `scripts/sweep_snr_floor.py` — reusable CLI that sweeps SNR and reports the 6 dB PSR crossing.

The gate currently passes: at 30 dB SNR the offset is within ±1 sample with PSR ≥10 dB across all
tested delays, and the 6 dB PSR floor for a broadband periodic click train sits at ≈ −30 dB SNR
(ample margin below any realistic phone-bleed SNR). This validates the *algorithm*; whether real
phone-speaker/mic bleed clears the floor is Test 2 step 2's job, still pending the loopback rig
and a physical device.

## Setup

```
cd analysis
python -m venv .venv
.venv/Scripts/activate   # .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
```

## Test

```
pytest
```

## Reproduce the SNR-floor sweep

```
python scripts/sweep_snr_floor.py
```
