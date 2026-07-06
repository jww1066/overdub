# Offline analysis / Python DSP — detailed guidance

Companion to `CLAUDE.md`. Read this when working in the `analysis/` package: the venv, the
scripting discipline, and the GCC-PHAT lessons from the Test 2 real-bleed sweep.

## Python analysis tooling

The `analysis/` package (Test 2 step 1's GCC-PHAT validation, and future offline DSP work) keeps
its own venv at `analysis/.venv` so Python tooling doesn't collide with Gradle/Kotlin. Set it up
with `cd analysis && python -m venv .venv && .venv/Scripts/python.exe -m pip install -e ".[dev]"`
on Windows, and run `pytest` and scripts through `.venv/Scripts/python.exe` (not the system
Python) so dependency versions stay pinned.

- **Keep Python scripts ASCII-only.** The Windows console defaults to the cp1252 code page, so a
  script printing a non-ASCII glyph (`≈`, `≥`, `−`) crashes with `UnicodeEncodeError` mid-run —
  discovered when `sweep_snr_floor.py` printed `≈` and died *after* the full sweep had completed
  but *before* printing the result. Use ASCII substitutes (`~`, `>=`, `-`) in script output, or
  set `PYTHONUTF8=1` before running. This is the actual-failure cousin of the harmless LF→CRLF
  `git add` warnings.
- **Write reusable scripts, not one-off `python -c` snippets or scratchpad temp files.** Anything
  worth computing once (an SNR sweep, a metric over a capture set) belongs in `analysis/scripts/` as
  a real file with argparse and a docstring, so it's re-runnable as the code or data changes and can
  be checked in. A `python -c "..."` that prints a finding evaporates with the shell session and has
  to be rewritten from scratch next time; a scratchpad temp file is not an escape hatch either. The
  `sweep_snr_floor.py` script is the template. This applies even to a quick ad-hoc edge-case check
  mid-task (e.g. spot-checking a function's behavior while reviewing code) — the impulse to verify a
  hunch inline is exactly the case this rule targets, not just deliberate analysis work.
- **Validate a DSP-parameter concern empirically before changing it, not by guessing.** When a
  default (e.g. a PSR exclusion window, a filter cutoff) is suspected to be miscalibrated against
  the actual signal shape, write a small diagnostic script that measures the real quantity (e.g.
  `measure_main_lobe_width.py` printing correlation magnitude around the peak) rather than
  reasoning about it in the abstract or "fixing" it speculatively — the measurement can just as
  easily show the original default was fine. Same spirit as "Diagnose before re-implementing"
  (`doc/guides/testing-and-debugging.md`), applied to offline DSP instead of on-device behavior. The
  band-limited-PHAT `psr_exclusion` re-check below is a worked example where the measurement *did*
  vindicate the default.
- **Python negative-slice gotcha:** a slice bound computed as `len - k` silently changes meaning if
  it goes negative — `out[: n - k]` is `out[:5]` when `n - k == 5`, but becomes `out[:-3]` (a large
  *positive*-length slice from the start, not an empty one) when `n - k == -3`. This bit
  `synth.py`'s `delay()`: for `abs(d) >= len(signal)` the computed bound went negative and the slice
  silently selected the wrong range instead of being empty, surfacing as a confusing
  `numpy` broadcast-shape `ValueError` rather than a clear error or correct result. When a slice
  bound is arithmetic (not a literal), explicitly guard the case where it could go negative rather
  than trusting Python's negative-index reinterpretation to do the right thing.

## GCC-PHAT lessons (Test 2 real-bleed sweep)

- **GCC-PHAT's PHAT weighting over-weights noise bands on real band-limited signals; band-limit
  to the usable-SNR band before concluding "not enough SNR."** PHAT divides the cross-spectrum by
  its own magnitude, weighting every frequency band equally — fine for a clean synthetic signal,
  but on real phone-speaker-to-mic bleed the speaker rolls off the bass and the HF bands are
  mic-noise-dominated (signal weak, noise floor wins). Equal weighting then amplifies the
  low-SNR bands and the correlation peak collapses (a 36-cell real-bleed sweep gave PSR 0.6-5.8
  dB with unphysical negative offsets, full-band), even though the reference itself is perfectly
  clean (reference-vs-delayed-reference autocorrelation PSR 38-67 dB). Diagnose before fixing: a
  reference autocorrelation PSR test rules out "the reference is too periodic," and a
  capture-vs-reference magnitude-spectrum comparison shows the usable-SNR band (here ~500-4000
  Hz). The fix is to bandpass both signals to that band before GCC-PHAT. Bandpassing recovers the
  peak *broadly* — a 36-cell real-bleed re-run went from 0/36 to 35/36 clearing the 6 dB bar (29
  at >=10 dB). A full-band PHAT failure on a real signal is usually a band-selection problem, not
  an overall-SNR verdict.
- **But a recovered PSR does NOT by itself validate the recovered offset — check the offset for
  physical plausibility separately, and constrain the lag search.** The same band-limited 36-cell
  re-run exposed the trap: one cell scored PSR 11.6 dB ("confident") on an offset of *-15.25 s* —
  a full-clip circular-correlation wraparound alias, physically impossible for a speaker->mic
  round-trip. PSR only measures how sharp the winning peak is relative to the rest of the
  correlation; a sharp *alias* still scores high. Two corollaries. (1) The recovered offsets were
  NOT a "consistent ~97 ms" as a single-cell spot-check had suggested — across the matrix they
  spanned +61 to +151 ms plus the -15 s outlier, too wide for a fixed round-trip, so the
  single-cell "+97 ms" was over-generalized (the +61-151 ms spread is plausibly per-capture
  playback/capture-start jitter, but can't be confirmed benign without a loopback ground truth).
  Gate alignment on PSR *and* a plausible-lag constraint (restrict argmax — and the sidelobe
  search — to e.g. 0-300 ms via `gcc_phat`'s `lag_window`), never PSR alone; constraining it turned
  the -15 s alias into a +65 ms recovery and left offsets at 97.2 +/- 17.5 ms.
- **"Measure, don't assume" catch on the fix:** the intuition that bandpassing *widens* the
  correlation main lobe (half-width ~ 1/(2*bandwidth) ~= 7 samples at 500-4000 Hz / 48 kHz), so a
  2-sample `psr_exclusion` would start measuring the filter's lobe shape instead of the true peak,
  is *wrong for PHAT*. PHAT divides out the magnitude spectrum, re-whitening it, so the peak stays
  impulse-sharp regardless of the band — `measure_main_lobe_width.py`'s band-limited mode measured
  a first-null half-width of **1 sample**, and PSR is insensitive to the exclusion (10.5 dB at
  exclusion 1/2/3). So the flat ~11 dB PSR across an 8x bleed range is a *genuine* peak-to-sidelobe
  ratio, not an exclusion artifact, and the 2-sample default was already fine. A textbook case of
  the "validate empirically before changing" rule above: the measurement showed the
  suspected-miscalibrated default was correct.
