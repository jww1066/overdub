# reference_track.wav — real reference recording (boots.wav) + calibration click

This is a **real recording** for the Test 2 condition sweep — `boots.wav` from the repo root,
brought to the Pixel 10's native rate (48kHz, 16-bit mono) — with a **1.000 s calibration lead-in
prepended** (added 2026-07-08, `doc/test2-step2-plan.md` item 11): 0.200 s silence, a 20 ms
Hann-windowed 500–4000 Hz linear chirp, then 0.780 s silence. Detecting the chirp in a capture
(matched filter, `overdub_analysis.calibration_click.detect_click`) gives the in-basis
ground-truth offset that Test 2's ±2ms bar is judged against (see `doc/prototype-plan.md`
"Ground-truth correction").

Layout (at 48kHz): click onset at sample **9600** (0.200 s); beatbox content starts at sample
**48000** (1.000 s); total 780139 frames, 16.25 s. The click's shape/placement constants live in
`analysis/src/overdub_analysis/calibration_click.py` — the single source of truth shared by the
generator and the detector; don't restate the numbers elsewhere.

To (re)create after a fresh checkout (neither `boots.wav`, the intermediate, nor this output is
committed — audio files are never committed to this repo, see `CLAUDE.md`/memory):

    cd analysis && .venv/Scripts/python.exe scripts/resample_wav.py \
        ../boots.wav ../boots_48k_mono.wav --rate 48000 --mono
    .venv/Scripts/python.exe scripts/prepend_calibration_click.py \
        ../boots_48k_mono.wav ../harness/src/main/assets/reference_track.wav --expect-rate 48000

(`prepend_calibration_click.py` self-checks by re-detecting the click in its own output; if a
future source arrives at a different rate, `resample_wav.py` performs a rational, anti-aliased
resample so there is no fractional-rate error.)

Then confirm the format with:

    .venv/Scripts/python.exe scripts/inspect_wav.py \
        ../harness/src/main/assets/reference_track.wav --expect-rate 48000 --expect-channels 1 --expect-bits 16

**Analysis pairing rule:** captures made with the *click-less* asset (the 36-cell sweep of
2026-07-05 and the timestamp study) must be analyzed against a click-less reference — regenerate
one with `resample_wav.py` alone and pass it via the sweep scripts' `--reference`. Against the
click version their offsets shift by the whole 1.0 s lead-in and land outside the (0, 300 ms) lag
window. Captures made with *this* asset can additionally be trimmed by 48000 samples (both
reference and capture equally — the lag is invariant) to correlate beatbox-only content, keeping
the chirp from contributing correlated energy to the GCC-PHAT result being judged.

Length: 16.25 s, within Components §1's suggested 10-20 s window. The earlier 5.89 s clip was
blessed as "less averaging, not a correctness issue" for GCC-PHAT; the longer clip simply buys
more averaging for a more confident offset/PSR.

The synthetic placeholder click track (`harness/scripts/generate_reference_track.py`) is the
fallback if `boots.wav` is unavailable (it has no calibration lead-in), but the trusted Tier-3
sweep uses this real recording.
