# reference_track.wav — real reference recording (boots.wav)

This is a **real recording** for the Test 2 condition sweep: `boots.wav` from the repo root,
resampled to the Pixel 10's native rate (48kHz, 16-bit mono) via
`analysis/scripts/resample_wav.py --rate 48000 --mono`. Source is 44.1kHz mono, 5.89s;
the resample is rational (160/147, anti-aliased), so there is no fractional-rate error.

Caveat: it is 5.89s, shorter than Components §1's suggested 10-20s. GCC-PHAT still correlates
fine on a shorter clip (less averaging, not a correctness issue); noted here so the length is a
known quantity, not a surprise.

To (re)create after a fresh checkout (neither `boots.wav` nor this output is committed — audio
files are never committed to this repo, see `CLAUDE.md`/memory):

    cd analysis && .venv/Scripts/python.exe scripts/resample_wav.py \
        ../boots.wav ../harness/src/main/assets/reference_track.wav --rate 48000 --mono

Then confirm the format with:

    .venv/Scripts/python.exe scripts/inspect_wav.py \
        ../harness/src/main/assets/reference_track.wav --expect-rate 48000 --expect-channels 1 --expect-bits 16

The synthetic placeholder click track (`harness/scripts/generate_reference_track.py`) is the
fallback if `boots.wav` is unavailable, but the trusted Tier-3 sweep uses this real recording.
