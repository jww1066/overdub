# reference_track.wav — real reference recording (boots.wav) + calibration click + riser

This is a **real recording** for the Test 2 condition sweep — `boots.wav` from the repo root,
brought to the Pixel 10's native rate (48kHz, 16-bit mono) — with a **1.000 s calibration lead-in
prepended** (added 2026-07-08, `doc/test2-step2-plan.md` item 11) carrying **two ground-truth
instruments**:

- the **calibration click** (0.200 s in): a 20 ms Hann-windowed 500–4000 Hz linear chirp. Detecting
  it in a capture (matched filter, `overdub_analysis.calibration_click.detect_click`) gives the
  in-basis ground-truth offset that Test 2's ±2ms bar is judged against (see
  `doc/prototype-plan.md` "Ground-truth correction").
- the **selected calibration signal** (added 2026-07-09, `doc/prototype-plan.md` item 1): the
  log-sweep riser (`SELECTED_CANDIDATE_FACTORY`, 300 ms, 500→4000 Hz log sweep, peak −18 dBFS),
  mixed into the post-click silence at 0.550 s. This is the signal under test for the riser
  on-device capture — detect it with `analysis/scripts/detect_calibration_signal.py`, which judges
  the pass bar (≥10 dB detection quality, ≤2 ms onset recovery **vs the click**, the
  already-validated instrument in the same capture).

Layout (at 48kHz): click onset at sample **9600** (0.200 s); riser onset at sample **26400**
(0.550 s), ending at 40800 (0.850 s); beatbox content starts at sample **48000** (1.000 s); total
780139 frames, 16.25 s. The riser sits *inside* the click lead-in, so every analysis that trims
`LEAD_IN_S` (1.0 s) as "the lead-in" stays valid unchanged, and its onset is outside the click
detector's ±300 ms search window. Shape/placement constants live in
`analysis/src/overdub_analysis/calibration_click.py` (click) and
`analysis/src/overdub_analysis/calibration_candidates.py` (riser: `SELECTED_CANDIDATE_FACTORY`,
`SELECTED_MIX_ONSET_S`) — the single sources of truth shared by generators and detectors; don't
restate the numbers elsewhere.

To (re)create after a fresh checkout (neither `boots.wav`, the intermediates, nor this output is
committed — audio files are never committed to this repo, see `CLAUDE.md`/memory):

    cd analysis && .venv/Scripts/python.exe scripts/resample_wav.py \
        ../boots.wav ../boots_48k_mono.wav --rate 48000 --mono
    .venv/Scripts/python.exe scripts/prepend_calibration_click.py \
        ../boots_48k_mono.wav ../harness/src/main/assets/reference_track.wav --expect-rate 48000
    .venv/Scripts/python.exe scripts/mix_calibration_signal.py \
        ../harness/src/main/assets/reference_track.wav \
        ../harness/src/main/assets/reference_track.wav --expect-rate 48000

(Both generation scripts self-check by re-detecting their instruments in their own output;
`mix_calibration_signal.py`'s silence guard makes running it twice a hard error, so the chain is
safe to re-run from the top. If a future source arrives at a different rate, `resample_wav.py`
performs a rational, anti-aliased resample so there is no fractional-rate error.)

Then confirm the format with:

    .venv/Scripts/python.exe scripts/inspect_wav.py \
        ../harness/src/main/assets/reference_track.wav --expect-rate 48000 --expect-channels 1 --expect-bits 16

**Analysis pairing rule:** captures must be analyzed against the same generation of reference.
Captures made with the *click-less* asset (the 36-cell sweep of 2026-07-05 and the timestamp
study) need a click-less reference (regenerate with `resample_wav.py` alone, pass via the sweep
scripts' `--reference`); captures made with the click-only asset (2026-07-08, Session A, the
headset session) need the click-only reference (first two steps of the chain above) — against a
different generation their offsets shift by the whole lead-in (or the riser contributes correlated
energy on one side only). Captures made with *this* asset can additionally be trimmed by 48000
samples (both reference and capture equally — the lag is invariant) to correlate beatbox-only
content, keeping the click **and the riser** from contributing correlated energy to the GCC-PHAT
result being judged.

Length: 16.25 s, within Components §1's suggested 10-20 s window. The earlier 5.89 s clip was
blessed as "less averaging, not a correctness issue" for GCC-PHAT; the longer clip simply buys
more averaging for a more confident offset/PSR.

The synthetic placeholder click track (`harness/scripts/generate_reference_track.py`) is the
fallback if `boots.wav` is unavailable (it has no calibration lead-in), but the trusted Tier-3
sweep uses this real recording.
