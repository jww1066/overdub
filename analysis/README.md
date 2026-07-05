# overdub-analysis

Offline signal-processing prototyping and validation for the Overdub app — kept separate from the
Android/Kotlin app so Python tooling (venv, pytest, linters) doesn't collide with Gradle/Kotlin
tooling in the rest of the repo.

Scope for now: Test 2 (step 1) of [`../doc/prototype-plan.md`](../doc/prototype-plan.md) — synthetic
validation of GCC-PHAT time-delay estimation using `scipy.signal.correlate` plus an FFT-based phase
transform, before any of it is ported to (or re-verified against) real on-device behavior.

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
