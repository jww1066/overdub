# reference_track.wav — real reference recording (boots.wav)

This is a **real recording** for the Test 2 condition sweep: `boots.wav` from the repo root,
brought to the Pixel 10's native rate (48kHz, 16-bit mono) via
`analysis/scripts/resample_wav.py --rate 48000 --mono`. The current source is 48kHz mono,
15.25s (732139 frames); since it is already at the target rate, the resample step copies it
through with no rate change. (If a future source arrives at a different rate, the same script
performs a rational, anti-aliased resample so there is no fractional-rate error.)

Length: 15.25s, within Components §1's suggested 10-20s window. The earlier 5.89s clip was
blessed as "less averaging, not a correctness issue" for GCC-PHAT; the longer clip simply buys
more averaging for a more confident offset/PSR.

To (re)create after a fresh checkout (neither `boots.wav` nor this output is committed — audio
files are never committed to this repo, see `CLAUDE.md`/memory):

    cd analysis && .venv/Scripts/python.exe scripts/resample_wav.py \
        ../boots.wav ../harness/src/main/assets/reference_track.wav --rate 48000 --mono

Then confirm the format with:

    .venv/Scripts/python.exe scripts/inspect_wav.py \
        ../harness/src/main/assets/reference_track.wav --expect-rate 48000 --expect-channels 1 --expect-bits 16

The synthetic placeholder click track (`harness/scripts/generate_reference_track.py`) is the
fallback if `boots.wav` is unavailable, but the trusted Tier-3 sweep uses this real recording.
