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
  single-cell "+97 ms" was over-generalized (the +61-151 ms spread was later confirmed to be mostly
  per-capture playback/capture-start jitter via the hardware-timestamp decomposition — see the
  final bullet below).
  Gate alignment on PSR *and* a plausible-lag constraint (restrict argmax — and the sidelobe
  search — to e.g. 0-300 ms via `gcc_phat`'s `lag_window`), never PSR alone; constraining it turned
  the -15 s alias into a +65 ms recovery and left offsets at 97.2 +/- 17.5 ms.
  **Sharpened 2026-07-08 (calibration-click cross-check, `test2-sweep-results.md`): PSR *and* a
  plausible-lag window are STILL not enough.** The +97.2 ms "population mean" and the whole
  +61..+151 ms family turned out to be **+187 ms beat-period aliases** of *negative* true offsets
  (the baseline cell's true offset is -79.62 ms by matched-filter click detection; GCC-PHAT
  reported +107.12 ms at PSR 12.1 dB "confident" — ~187 ms off, essentially one reference beat
  period). The beat-period alias sat *inside* the (0, 300 ms) plausible window with a high PSR, so
  both gates blessed it. The positivity prior ("a round-trip is positive") was wrong *for the
  harness's measurement basis* (the captured WAV's sample 0 precedes input-stream frame 0, so the
  true offset is negative), which pointed the window the wrong way — and even a signed window would
  not have rejected an alias at *any* plausible magnitude. **The only gate that caught it was an
  independent aperiodic reference signal** (a prepended chirp, detected by matched filter — no
  beat-period ambiguity). Lesson upgraded: against a *rhythmic* reference, GCC-PHAT can alias by a
  whole beat with high PSR and an in-window offset; validate with an aperiodic ground-truth signal,
  not with PSR + a lag window. `analysis/scripts/check_reference_periodicity.py` maps a reference's
  self-similarity peaks (plain autocorrelation — PHAT-of-self is always a perfect impulse and hides
  the periodicity) so the alias risk is visible before trusting any correlation.
  **Sharpened again (2026-07-08, alias-gate remedy decision): the alias peak can be genuinely
  LARGER than the true peak — then no lag window of any sign can save the argmax.** Measured with
  `evaluate_alias_gate.py` (via `gcc_phat_correlation`, which exposes the raw correlation so
  competing peaks are rankable): on the baseline capture the beat-period alias outranked the true
  peak by **~12 dB**; a correctly-signed wide window still returned the alias. The only correlator
  remedy is an *anchored* window narrower than half the alias period, centered on an independent
  estimate (the calibration click for validation; the `getTimestamp` stream offset for the
  product-shaped path — its ~15 ms anchor error is far inside a ±90 ms half-width). Trimming the
  reference to reduce self-similarity flipped the ranking by only 0.4 dB — a coin flip, not a
  remedy.
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
  **Caveat (2026-07-08): that impulse-sharpness was measured at the *alias* peak — a
  self-similarity feature of the clean reference. The genuinely *acoustic* true peak is NOT
  sharp: it is a multipath cluster** (near-equal sub-peaks at 0 and +6 samples, ~±0.13 ms spread,
  measured with `evaluate_alias_gate.py`'s peak-shape output), so small-exclusion PSR reads
  **~0 dB at a perfectly correct alignment** (0.6 dB even at a 16-sample exclusion). Corollary:
  PSR is not a usable gate for a real reverberant acoustic path at all — gate on
  `|offset - independent ground truth|` and keep PSR as a diagnostic. Which peak you measured
  the lobe on matters as much as measuring it.
- **PSR is a fragile, band-sensitive *label*; the recovered offset is the robust quantity -- don't
  re-tune the band to chase one cell's PSR.** After the 500-4000 Hz sweep left one cell below the
  6 dB bar (`loud_far_facedown_none`, PSR 5.1 dB), narrowing to 1000-4000 Hz rescued it (12.6 dB)
  but was *not* a strict win across the matrix: it cleared 36/36 yet demoted 8 cells and, decisively,
  dropped the gate-critical baseline cell from confident (10.5) to minimum (9.0). Meanwhile the
  recovered-offset population stats were *identical* between the two bands (mean 97.2, std 17.5 ms) --
  band choice relabels which cells read "confident" without moving the alignment at all. So gate the
  *decision* on the offset (and the gate-critical baseline cell), not on maximizing a headline
  confident-count; a single edge cell below the PSR floor with a *band-robust* offset is a documented
  UX-constraint condition, not an alignment failure. (Diagnose the cell first --
  `diagnose_gcc_phat.py --capture <that_cell>.wav` -- before touching the global band.)
  **Caveat added 2026-07-08: "the offset is the robust quantity" inverts when the offset is an
  alias.** The band-robustness of the +87-/+97-/+107 ms family was robustness *of the beat-period
  alias*, not of the true alignment — the offset was identical across bands because the alias is a
  real reference feature, and that very robustness made the alias more convincing. "Gate on the
  offset, not the PSR" is only safe once the offset has been *validated* against an independent
  ground truth (the calibration click); until then a band-robust offset can be a band-robust alias.
- **A full-band GCC-PHAT failure has two opposite spectral causes; the diagnostic tells them apart.**
  The population failure was HF *rolloff* (speaker rolls off signal, HF is mic-noise). But the lone
  loud+facedown edge cell was the inverse -- HF *excess*: driven hard into the resting surface with
  the acoustic bleed weakest (far), the mic heard broadband chassis/surface **rattle** (capture minus
  reference +27.5 dB at 8-16k) uncorrelated with the reference. Same symptom (low PSR), opposite fix
  direction (exclude the *low* band vs the *high*). The capture-vs-reference magnitude-spectrum
  section of `diagnose_gcc_phat.py` distinguishes them; don't assume every real-bleed PSR miss is the
  same band-limit problem.
- **A run-to-run spread in a correlation-measured offset can be a *measurement artifact*, not
  algorithm error -- decompose it with hardware timestamps before blaming the algorithm.** The
  61-151 ms cross-cell offset spread (std 17.5 ms, > the whole 15 ms drift budget) looked alarming,
  but each cell is an *independently-started* output+input stream pair: offset = (acoustic round-trip,
  ~constant on one device) + (per-session start misalignment between the two streams). That second
  term is jitter of the *harness*, and the product (one continuous full-duplex session, self-measured
  once) does not have it -- so the spread confounds *validation*, not the alignment mechanism. The
  clean decomposition needs no loopback rig: both streams expose `getTimestamp()` (a
  `(framePosition, nanoTime)` pair on a common clock, with DAC/ADC latency folded in), so subtracting
  the timestamp-derived stream offset from the GCC-PHAT offset isolates the harness jitter from the
  fixed latency. **Confirmed empirically** (2026-07-05, Pixel 10): the cleanest isolation is to
  capture the *same* cell N times with the phone untouched -- the acoustic path is then constant, so
  *all* run-to-run offset variation is start-jitter, with no acoustic differences confounding it (a
  varied-cell set mixes the two). 9 same-cell repeats swung 73-119 ms in GCC-PHAT offset (std 13.4 ms)
  even unmoved; subtracting `stream_offset_ms` collapsed the std to 5.5 ms (59%) -- the timestamps
  track the jitter and remove most of it. Two calibration notes the naive "residual = acoustic flight"
  prediction misses: (1) the residual *mean* was a large fixed **~201 ms constant**, not sub-ms -- a
  measurement-basis offset (the captured WAV's sample 0 does not equal input-stream frame 0 once the
  maxed input buffer + startup drain gap fold in), which is constant, hence calibration not jitter,
  and irrelevant to the benign-vs-real verdict (that turns on the *std* collapse). (2) The collapse is
  partial, not total (5.5 ms residual std remains from getTimestamp granularity + correlation
  quantization) -- report it as "most of the spread," not "fully explained." Confirming the fixed
  constant is *honest* is the loopback rig's separate job -- platform-reported latency has anecdotal
  device-specific inaccuracy (a single ~100 ms discrepancy reported on a moto g(20); `design-summary.md`
  flags it as thin evidence), so the reported timestamps can't be assumed honest without an
  independent acoustic check.
  General lesson: when a measured offset comes from correlating two independently-scheduled streams,
  attribute the run-to-run spread to the measurement rig (and measure it with the platform's own
  clock) before attributing it to the estimator. See `doc/guides/on-device-audio.md` for the
  full-duplex timestamp mechanism.
