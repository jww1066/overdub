# reference_track.wav — placeholder

This is a **synthetic click track**, not a real beatbox recording: a 15s, 120bpm alternating
kick/hihat click pattern at 48kHz/16-bit mono, generated with a stdlib-only Python script (no real
performer, no real audio content).

It exists so the harness's playback/capture/WAV-write/metadata pipeline can be built and tested
end-to-end before a real reference track is available. **Replace this file with an actual clean, dry
beatbox recording** (per test2-step2-plan.md Components §1) before running the real condition sweep
(Tier 3) — GCC-PHAT correlation quality and the pass/fail thresholds in `prototype-plan.md` are only
meaningful against the real signal this app will actually use.

**Not committed to Git** (audio files never are — see `CLAUDE.md`). This file is gitignored; run
`python harness/scripts/generate_reference_track.py` to (re)generate it locally after a fresh
checkout, before building/running the harness.
