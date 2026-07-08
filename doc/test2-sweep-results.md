# Test 2 — Tier-3 condition-sweep results

Capture log for the manual 36-cell condition sweep (test2-step2-plan.md Components Sec 3),
**complete 36/36 as of 2026-07-05**. The on-device WAV + JSON captures are gitignored (audio
is never committed to this repo -- see `CLAUDE.md`/memory); this file is the durable, tracked
record of what was captured and what the RMS data shows. The offline GCC-PHAT pass (Test 2
step 1, `analysis/`) will fill in PSR / recovered offset per cell now that the matrix is down.

## Run conditions (constant across all 36)

- **Device:** Google Pixel 10 (`device_model` in every JSON sidecar; `stream_volume_index` = 25,
  i.e. STREAM_MUSIC pinned to max).
- **Reference track:** `boots.wav` resampled to 48 kHz / 16-bit / mono, 15.25 s (732 139 frames)
  -- see `harness/src/main/assets/reference_track_README.md`. Matches the device's native rate,
  so no HAL resampling.
- **Capture:** full-duplex Oboe, LowLatency/Exclusive, input preset `voice_recognition`, output
  forced to the built-in speaker, input to the built-in mic. 48 kHz throughout.
- **Geometry (corrected):** wall is the reflecting surface for the distance axis; phone on a
  stand in free air (face-up) or on a small pad (face-down), at 15 cm / 50 cm / 2 m from the
  wall. The face-down resting pad is a *separate* object from the wall reflector -- this is what
  keeps the distance and orientation axes independent. (The first six cells were captured with
  the desk-below-as-reflector geometry and were discarded; see "Discarded captures" below.)
- **Held constant:** same room, same wall, same resting-surface material, low/stable ambient
  noise, no other audio sources, phone on a stand/pad (not held), no headset connected.
- **Driver:** `harness/scripts/run_sweep_cell.sh <condition_id>` -> `am instrument` against the
  persistently installed app+test APK (NOT `gradlew connectedAndroidTest`, which uninstalls and
  wipes the captures). The 36 cells are run as **12 physical arrangements x 3 programmatic
  volumes** -- volume costs no phone movement, so the operator repositions 12 times, not 36.
- **Hard-fail bars (per `ConditionSweepTest`):** xrun_count == 0, dropped_frame_count == 0,
  route is `builtin_speaker`. A sub-floor RMS (RMS_SANITY_FLOOR = 50.0, int16 scale) is NOT a
  failure for edge cells -- it is recorded as a finding.
- **Engine endurance: 36/36 clean.** Zero XRuns, zero dropped frames, route held at
  `builtin_speaker`, 48 kHz throughout, across ~9 minutes of total capture (36 cold and warm
  starts). The cold-start input-underrun fix (output stream started first, drain-all-available
  per callback, enlarged buffers; see `CLAUDE.md`) held across every cell.

## Results (36 / 36 -- complete)

All 36 cells: sanity = PASS, xrun = 0, dropped = 0, route = builtin_speaker, rate = 48000 Hz.
RMS is int16 scale.

### `near` distance (~15 cm from wall)

| Orientation | Obstruction | quiet (0.2) | conv (0.6) | loud (1.0) |
|---|---|---|---|---|
| face-up   | none     | 1734.8 | 4450.5 | 6561.3 |
| face-up   | pocketed | 1511.7 | 3991.3 | 5992.7 |
| face-down | none     | 3616.7 | 8259.1 | 11103.4 |
| face-down | pocketed | 2956.3 | 7059.3 | 9847.6 |

### `armslength` distance (~50 cm from wall)

| Orientation | Obstruction | quiet (0.2) | conv (0.6) | loud (1.0) |
|---|---|---|---|---|
| face-up   | none     | 1567.2 | **4126.2** (baseline) | 6153.0 |
| face-up   | pocketed | 1577.2 | 4132.9 | 6160.7 |
| face-down | none     | 3732.3 | 8394.3 | 11240.8 |
| face-down | pocketed | 3766.7 | 8529.6 | 11416.8 |

### `far` distance (~2 m from wall)

| Orientation | Obstruction | quiet (0.2) | conv (0.6) | loud (1.0) |
|---|---|---|---|---|
| face-up   | none     | 1648.5 | 4272.7 | 6332.6 |
| face-up   | pocketed | 1429.4 | 3781.9 | 5691.0 |
| face-down | none     | 4035.3 | 8899.8 | 11782.3 |
| face-down | pocketed | 3813.1 | 8537.2 | 11444.4 |

### File manifest (36 pairs on-device under `/sdcard/Android/data/com.overdub.harness/files/sweep/`)

| condition_id | timestamp | RMS |
|---|---|---|
| quiet_near_faceup_none | 1783294237383 | 1734.8 |
| conversational_near_faceup_none | 1783294255660 | 4450.5 |
| loud_near_faceup_none | 1783294274047 | 6561.3 |
| quiet_near_faceup_pocketed | 1783294342934 | 1511.7 |
| conversational_near_faceup_pocketed | 1783294361483 | 3991.3 |
| loud_near_faceup_pocketed | 1783294380217 | 5992.7 |
| quiet_near_facedown_none | 1783294528896 | 3616.7 |
| conversational_near_facedown_none | 1783294547470 | 8259.1 |
| loud_near_facedown_none | 1783294565742 | 11103.4 |
| quiet_near_facedown_pocketed | 1783294647429 | 2956.3 |
| conversational_near_facedown_pocketed | 1783294666141 | 7059.3 |
| loud_near_facedown_pocketed | 1783294684757 | 9847.6 |
| quiet_armslength_faceup_none | 1783294858650 | 1567.2 |
| conversational_armslength_faceup_none | 1783294877308 | 4126.2 |
| loud_armslength_faceup_none | 1783294895907 | 6153.0 |
| quiet_armslength_faceup_pocketed | 1783294991390 | 1577.2 |
| conversational_armslength_faceup_pocketed | 1783295010159 | 4132.9 |
| loud_armslength_faceup_pocketed | 1783295028989 | 6160.7 |
| quiet_armslength_facedown_none | 1783295486875 | 3732.3 |
| conversational_armslength_facedown_none | 1783295505495 | 8394.3 |
| loud_armslength_facedown_none | 1783295524159 | 11240.8 |
| quiet_armslength_facedown_pocketed | 1783295600532 | 3766.7 |
| conversational_armslength_facedown_pocketed | 1783295619662 | 8529.6 |
| loud_armslength_facedown_pocketed | 1783295638242 | 11416.8 |
| quiet_far_faceup_none | 1783295907535 | 1648.5 |
| conversational_far_faceup_none | 1783295926564 | 4272.7 |
| loud_far_faceup_none | 1783295945442 | 6332.6 |
| quiet_far_faceup_pocketed | 1783296027773 | 1429.4 |
| conversational_far_faceup_pocketed | 1783296046628 | 3781.9 |
| loud_far_faceup_pocketed | 1783296065502 | 5691.0 |
| quiet_far_facedown_none | 1783296209689 | 4035.3 |
| conversational_far_facedown_none | 1783296229829 | 8899.8 |
| loud_far_facedown_none | 1783296248876 | 11782.3 |
| quiet_far_facedown_pocketed | 1783296314370 | 3813.1 |
| conversational_far_facedown_pocketed | 1783296333407 | 8537.2 |
| loud_far_facedown_pocketed | 1783296352838 | 11444.4 |

## Findings (from RMS; GCC-PHAT PSR pending the offline pass)

1. **Orientation is the dominant lever.** Face-down gives ~1.7-2.4x the bleed of face-up at every
   distance, volume, and obstruction (e.g. loud/near/none: 11103 face-down vs 6561 face-up; the
   face-down floor is ~1.8-2.4x the face-up floor, a ratio that *shrinks* with volume). The
   Pixel 10's bottom + earpiece speakers couple strongly into the resting pad, redirecting
   energy back at the mic. The orientation choice moves the needle more than any other axis.

2. **Volume scales sub-linearly everywhere -- a device-level compression.** Captured RMS compresses
   the gain ratio by ~15-42% (conv/quiet measured 2.2-2.7x vs 3.0x expected; loud/quiet 2.9-3.9x
   vs 5.0x). This is the CLAUDE.md gain-ratio probe result: residual AGC / speaker-amp
   nonlinearity is flattening the volume-axis SNR gradient despite the `voice_recognition` input
   preset. Compression is worse face-down than face-up, so it has two superimposed components --
   a device-level one and a coupling-path one. A dedicated AGC-probe script (to be written in
   `analysis/scripts/`) should decompose these properly by subtracting the noise floor in the
   power domain before fitting RMS vs gain per orientation.

3. **Face-down coupling is mechanically nonlinear.** The face-down/face-up ratio falls with
   volume, and within-arrangement gain ratios compress harder face-down (loud/quiet 58-61% of
   linear) than face-up (76-79%). The speaker-pad coupling saturates: doubling drive does not
   double the coupled bleed.

4. **Distance-to-wall is a weak lever end-to-end, at both orientations.** The chassis-direct
   (face-up) and pad-coupling (face-down) floors are distance-independent across the full
   15 cm -> 2 m range. `far` is NOT lower than `armslength` -- it is ~3-5% higher at face-up and
   ~5-8% higher at face-down, because at 2 m the phone sits in the room's diffuse/reverberant
   field (a different room position with different multi-surface geometry) rather than near a
   single early-reflection wall. The "near = strongly reflective -> far = near-anechoic" gradient
   the plan hypothesized does not materialize for the bleed, because the bleed is dominated by
   the chassis/pad path that wall distance cannot touch. **UX constraint: you cannot escape the
   bleed by moving the phone away from the wall.** Orientation and volume are the only levers
   that move the needle; distance-to-wall is effectively decorative for the bleed path.

5. **Obstruction (fabric) attenuation is U-shaped in distance, not monotonic.** Pocketed vs none:
   ~9-18% at near, ~0% at armslength, ~3-13% at far -- at both orientations (face-up: -13/-0/-13;
   face-down: -18/+1/-5). The simple "fabric removes the wall-reflected component, present at
   near -> absent at distance" decomposition proposed mid-sweep was disconfirmed by the far
   cells. The honest read: at 2 m the phone is in a different reverberant context (other walls,
   ceiling, furniture), and the fabric catches reverberant energy from those surfaces again,
   which is why the attenuation returns. The armslength ~0% looks like the anomaly -- the 50 cm
   position appears to have the least reverberant return of the three. **Consequence: the
   distance axis in a real room is confounded by multi-surface geometry** -- "2 m from the wall"
   also means "closer to other surfaces," so a clean single-wall reflection model does not
   survive contact with a real room. The fabric attenuation is geometry-dependent, not a
   constant (a single "pocketed attenuates X%" number is misleading).

6. **The two floors.** Each orientation has a distance- and (mostly) obstruction-independent
   floor: face-up chassis-direct ~1570/4130/6160 (quiet/conv/loud), face-down pad-coupling+chassis
   ~3700/8350/11250. Neither repositioning nor pocketing beats the floor at armslength; the
   fabric only ever removes the small reverberant component that's present at near and far but
   absent at armslength.

7. **Best/worst across the matrix.** Max bleed = `far / face-down / none / loud` (11782) -- the
   worst case is far + face-down + unobstructed + loud, not near. Min bleed (best isolation) =
   `far / face-up / pocketed / quiet` (1429). The worst case is ~8.2x the best case -- that is
   the dynamic range of the bleed across the 36-cell matrix, and the headroom the cancellation
   algorithm has to operate over.

## GCC-PHAT offline pass (2026-07-05)

Ran `analysis/scripts/run_gcc_phat_sweep.py` over the 36 captures vs the bundled reference track.
**Result: 0/36 pass** -- 0 confident (>= 10 dB), 0 minimum (>= 6 dB), 36 below. PSR ranges
0.6-5.8 dB. Recovered offsets are negative (-65 to -126 ms) and vary cell-to-cell, both wrong:
the mic must lag the reference by a roughly constant system round-trip (a few ms, positive), not
lead it by a varying ~100 ms. That signature means the GCC-PHAT argmax is landing on
sidelobes/noise, not the true alignment peak; the low PSR confirms no sharp peak exists.

The script's RMS matches the on-device logged RMS exactly per cell (e.g. quiet_near_faceup_none
= 1734.8 in both), so the WAV/JSON I/O is correct and the issue is the correlation itself, not
the script. This is a real finding, not a script bug: the synthetic GCC-PHAT validation (Test 2
step 1) used a broadband click train (sharp autocorrelation, clean peak) and passed; the real
beatbox reference plus real band-limited phone-speaker bleed do not satisfy GCC-PHAT's
assumptions. Two candidate causes, to be diagnosed empirically (per CLAUDE.md, not guessed):

- **(a) Reference quasi-periodicity** -- a beatbox clip has strong rhythmic autocorrelation
  sidelobes that collapse PSR and let a sidelobe win argmax.
- **(b) Band-limited bleed** -- a phone speaker rolls off highs, so the bleed has little HF
  energy; PHAT's equal-per-band weighting then amplifies noise-dominated high bands and
  corrupts the correlation.

A reusable diagnostic script (autocorrelation PSR of the reference; magnitude spectrum of a
capture vs the reference) will determine which dominates before choosing a fix -- a less-periodic
reference, onset/transient-only correlation, or band-limited PHAT weighting. The per-cell CSV is
at `analysis/sweep_data/gcc_phat_results.csv` (gitignored; regeneratable via the script).

### Band-limited PHAT diagnosis + population re-run (2026-07-05, revised)

`analysis/scripts/diagnose_gcc_phat.py` split the two candidate causes on the **baseline cell only**:

- **Cause (a) ruled out.** Reference-vs-delayed-reference autocorrelation PSR was 38-67 dB at
  5-120 ms synthetic delays, offset recovered exactly. (Caveat: this correlates the reference
  against a zero-padded *identical* copy of itself, so a sharp peak is nearly guaranteed -- it
  rules out "literally periodic," which is weaker evidence than the crisp dB range reads.)
- **Cause (b) confirmed.** The capture-vs-reference spectral envelope shows the speaker rolls off
  the bass (-17 to -19 dB below 500 Hz) and the 4-16 kHz bands are mic-noise-dominated (capture
  +12 to +18 dB above the weak reference). Usable-SNR band ~500-4000 Hz.
- On that one cell, bandpassing both signals to 500-4000 Hz recovered PSR 10.5 dB with +97 ms.

**The single-cell result was over-read as "fix validated." The population re-run tells a more
nuanced story.** `analysis/scripts/run_bandlimited_gcc_phat_sweep.py` applies the same
bandpass+GCC-PHAT to all 36 cells:

- **Recovery is real and broad:** 29/36 confident (>= 10 dB), 6/36 minimum (>= 6 dB), **1/36
  below** -- i.e. 35/36 clear the 6 dB bar, up from 0/36 full-band. The band-limiting insight holds
  across the matrix, not just the baseline cell.
- **But the offsets are NOT a consistent +97 ms round-trip.** Across cells they span **+61 to
  +151 ms** -- a ~90 ms (2.5x) spread, too wide for a fixed speaker->mic latency on one device.
  The "consistent +97 ms" claim was consistency across *bandpass choices on one cell*,
  mis-generalized to imply cross-cell consistency.
- **A "confident" PSR does not imply a correct offset.** `conversational_far_faceup_pocketed`
  scored **PSR 11.6 dB (confident)** with an offset of **-15,253 ms** -- essentially the full
  reference length: a circular-correlation wraparound alias, physically impossible. High PSR only
  means the winning peak is sharp; it can be a sharp *alias*. So PSR alone is not a trustworthy
  alignment gate as currently used.
- PSR is also suspiciously flat (~9.6-12.5 dB) across the full 8x bleed dynamic range -- the
  quietest cell scores like the loudest -- consistent with the post-bandpass PSR largely
  reflecting the filter's own autocorrelation main-lobe shape against the fixed 2-sample
  `psr_exclusion`, rather than the true peak's sharpness. See "Next steps" for the exclusion-window
  re-check.

**Honest status: band-limiting rescues the correlation peak broadly, but the recovered offset is
not yet trustworthy** (unconstrained argmax lands on wraparound/noise aliases that PSR still
blesses). Per-cell CSV: `analysis/sweep_data/gcc_phat_bandlimited_results.csv` (gitignored;
regeneratable). This is *not* the Test 2 step 2 pass -- the ±2 ms-vs-ground-truth bar also still
lacks its referent (per the 2026-07-08 correction: an in-basis calibration click, not Test 1's
loopback number -- see the lag-window section below).

### Lag-window fix + PSR-exclusion re-check (2026-07-05, items 7a/7b)

- **7a -- lag-window constraint (done).** `gcc_phat` gained an optional `lag_window`
  (samples-of-offset bounds; default `None` = unchanged) that restricts both the argmax and the
  PSR sidelobe search to a plausible offset range. `run_bandlimited_gcc_phat_sweep.py` now applies
  `(0, 300 ms)` by default. Re-run with it: the `-15,253 ms` wraparound cell
  (`conversational_far_faceup_pocketed`) now recovers **+65 ms at PSR 12.8 dB**, and verdicts
  improve to **33 confident / 2 minimum / 1 below** (removing the alias also stops it competing as
  a sidelobe elsewhere). Offsets now sit in **61-151 ms, mean 97.2, std 17.5 ms** -- the original
  single-cell "+97 ms" is the *population mean*, with real per-capture spread. Unit tests added
  (`test_gcc_phat.py`: window recovers in-window delay, forces result into window, rejects an
  empty window, `None` matches default).
- **7b -- PSR exclusion re-check (done; the suspected miscalibration was NOT real).**
  `measure_main_lobe_width.py` gained a band-limited real-signal mode. Measured post-bandpass
  main-lobe first-null half-width = **1 sample** for both the clean reference autocorrelation and
  the baseline capture -- *not* the ~7 samples the `1/(2*BW)` rule predicts, because **PHAT
  re-whitens the spectrum and keeps the peak impulse-sharp even after bandpassing.** So the fixed
  `psr_exclusion=2` was already adequate; PSR is insensitive to it (10.5 dB at exclusion 1/2/3).
  The flat ~11 dB PSR across the bleed range is therefore a *genuine* peak-to-sidelobe ratio, not
  an exclusion artifact -- the earlier hypothesis is disconfirmed. (A textbook "measure before
  changing -- the default was fine" outcome; no change made.)
- **What still blocks calling this a pass:** whether 97 ms is the *correct* round-trip (the ±2 ms
  bar) needs Test 1's loopback ground truth, which doesn't exist yet. The 61-151 ms spread is
  plausibly per-capture playback/capture-start jitter (separate un-sample-synced recordings), but
  cannot be confirmed as such -- or ruled out as residual misalignment -- without that ground truth.
  **Correction (2026-07-08):** the loopback number cannot be that ground truth -- it measures the
  wired-USB route in a different measurement basis than these captures (see the ~201 ms constant in
  the timestamp study below). The ±2 ms referent is now an **in-basis calibration click** embedded
  in the reference track (`test2-step2-plan.md` Next steps item 11); the spread question itself was
  since resolved by the timestamp decomposition below.

### Edge-cell diagnosis, band trade-off, and the start-jitter decomposition path (2026-07-05, item 7c follow-up)

Three linked findings from re-examining the one below-bar cell and the offset spread.

**1. The single below-6 dB cell is a mechanical-rattle edge case, not an alignment failure.**
`loud_far_facedown_none` (band-limited PSR 5.1 dB, the lone <6 dB cell) was diagnosed with
`diagnose_gcc_phat.py --capture loud_far_facedown_none_1783296248876.wav`. Its failure mode is the
*opposite* of the population failure:
- Reference autocorrelation PSR 38-67 dB -> reference fine (cause (a) ruled out), as everywhere.
- The spectral envelope shows an HF *excess*, not a rolloff: capture-minus-reference is **+13 dB at
  2-4k, +17 dB at 4-8k, +27.5 dB at 8-16k**. In the loud+far+facedown condition the speaker is
  driven hard *into the resting surface* while the acoustic bleed is weakest (far ~ near-anechoic),
  so the mic hears mostly chassis/surface rattle -- broadband HF energy uncorrelated with the
  reference -- layered over a faint real bleed. This is the inverse of the baseline cell's
  speaker-bass-rolloff / HF-mic-noise problem.
- Critically, the *offset* is band-robust: 500-4000, 300-4000, 250-4000, and 1000-4000 all recover
  the identical **4181 samples (87.10 ms)**; only 500-8000 (which readmits the rattle band) flips to
  a -96.73 ms alias. So the alignment for this cell is correct -- only the PSR margin in the default
  band dips below 6 dB.

**2. Narrowing the global band to 1000-4000 Hz is NOT a strict improvement -- rejected.**
Because 1000-4000 recovered the rattle cell to 12.6 dB, we tested it across all 36
(`run_bandlimited_gcc_phat_sweep.py --lo 1000 --hi 4000`, output
`gcc_phat_1000_4000_results.csv`):

| Band | confident (>=10) | minimum (6-10) | below (<6) | clears 6 dB |
|---|---|---|---|---|
| 500-4000 (current) | 33 | 2 | 1 | 35/36 |
| 1000-4000 | 25 | 11 | 0 | 36/36 |

It removes the one sub-6 dB cell but demotes 8 cells confident->minimum and -- decisively -- drops
the **gate-critical baseline** cell `conversational_armslength_faceup_none` from 10.5 (confident) to
9.0 (minimum). The demoted cells are the faceup/none ones whose real acoustic bleed carries
correlated energy in 500-1000 Hz that 1000-4000 discards; no fixed band is optimal for both the
acoustic-bleed regime and the rattle regime. **Decision: keep 500-4000.** (Decision basis,
clarified 2026-07-08: the band is carried by the *spectral diagnosis* -- the measured usable-SNR
band is ~500-4000 Hz, speaker bass rolloff below it, mic-noise domination above it -- not by which
band keeps the baseline cell "confident." The baseline demotion under 1000-4000 is corroboration
that 500-1000 Hz carries real correlated bleed energy, not the selection criterion; picking a band
by whether the gate cell stays above the line would be post-hoc fitting on the gate metric.) The
rattle cell failing the *confidence* margin (not the alignment) is exactly the kind of edge
condition the plan documents as a UX constraint, not a test failure. Key by-product: the recovered-offset population stats are
*identical* between the two bands (min 61.1 / max 151.2 / mean 97.2 / std 17.5 ms), so band choice
relabels PSR verdicts without moving the alignment -- reinforcing that PSR is a fragile label and the
offset is the robust quantity.

**3. The 61-151 ms offset spread is a harness measurement artifact, decomposable now WITHOUT the
loopback rig.** Mechanistically the spread is *not* GCC-PHAT error. Each of the 36 cells is an
independent capture session with its own output+input stream start; the two streams are not
sample-synchronized, so the recovered offset = (acoustic round-trip, ~constant on one device) +
(per-session start misalignment between the two streams). That second term is jitter of the
*measurement*, and the **product does not have it**: the app aligns within one continuous full-duplex
session and self-measures that session's own offset once, so cross-session spread is irrelevant to
alignment and only confounds *validation*.

The principled decomposition uses the hardware timestamps both streams already expose
(`AAudioStream_getTimestamp()` / Oboe `getTimestamp()`), a `(framePosition, nanoTime)` pair against a
common monotonic clock. The output timestamp folds in DAC latency (when a frame is *heard*), the
input timestamp folds in ADC latency (when a frame is *captured*), so subtracting the
timestamp-derived stream offset from the GCC-PHAT offset should leave only the tiny near-constant
acoustic flight time. This is decisive either way: residual collapses to a constant -> the spread was
jitter (benign, now removable); residual stays wide -> it is real alignment error and the benign
reading is dead. **This needs the device but NOT the loopback rig** -- the rig's separate role is to
later confirm the device's reported timestamps aren't *lying* (the moto g(20) counter-example). It
cannot be applied retroactively (the 36 WAVs logged no timestamps), so it needs a re-capture of a few
cells with timestamp logging added -- which is also **Test 1a's mechanism pulled forward** (the
design's device-agnostic alignment hedge, `prototype-plan.md`). See `test2-step2-plan.md` "Next
steps."

### Stream-timestamp decomposition confirmed: run-to-run spread is largely harness jitter (2026-07-05, item 10)

The `getTimestamp()` logging is now implemented (`FullDuplexEngine::readStreamTimestamps()` ->
`stream_offset_ms` in the sidecar; derivation `computeStreamOffset` unit-tested; offline
`decompose_offset.py`), verified on the Pixel 10, and the decomposition study was run.

**Method (needs no loopback rig, no repositioning):** capture the **same** baseline cell
`conversational_armslength_faceup_none` **9 times back-to-back**
(`harness/scripts/repeat_sweep_cell.sh <id> 8`, plus one earlier run) with the phone untouched, so the
acoustic round-trip is held constant and *any* run-to-run offset variation must be per-session
harness start-jitter. All 9 captures were clean (RMS ~7760-7785, 0 XRun, `builtin_speaker`), and
`getTimestamp` succeeded on both streams every time (not a moto-g(20) failure). Analyzed via
`run_bandlimited_gcc_phat_sweep.py --sweep-dir timestamp_study` then `decompose_offset.py`.

**Result:**

| Quantity (same cell, phone unmoved, n=9) | mean | std | min..max |
|---|---|---|---|
| GCC-PHAT offset (band-limited 500-4000) | 105.3 ms | **13.4 ms** | 73.1..119.1 |
| `getTimestamp` stream offset | -95.9 ms | ~13 ms | -124.9..-80.2 |
| Residual = GCC-PHAT - stream offset | 201.1 ms | **5.5 ms** | 191.3..209.2 |

Two things this establishes:

1. **The run-to-run spread is a measurement artifact, confirmed empirically, not just argued.** With
   the phone *never moved*, the recovered GCC-PHAT offset still swings 73-119 ms (std 13.4 ms) --
   comparable to the whole 61-151 ms *cross-cell* spread that had looked alarming. So a large share of
   that cross-cell spread was per-session start jitter, not the estimator disagreeing about alignment
   or real acoustic differences between positions. This is exactly the
   `doc/guides/offline-dsp.md` "run-to-run spread can be a measurement artifact" lesson, now with a
   number behind it.
2. **The hardware timestamps track that jitter and remove most of it.** Subtracting `stream_offset_ms`
   collapses the std from 13.4 ms to **5.5 ms (a 59% reduction)** -- the stream offset moves run-to-run
   *with* the GCC-PHAT offset, which is the sign the two share a cause. The remaining 5.5 ms (getTimestamp
   granularity + band-limited-correlation quantization at these PSRs) is inside the 15 ms drift budget
   (but see the budget check below -- the margin is thinner than "inside the budget" reads).

**Caveat -- a large fixed constant remains, and that is the loopback rig's job, not this study's.** The
residual *mean* is +201 ms, not the ~sub-ms pure acoustic flight the naive derivation predicts. That
~200 ms is a fixed measurement-basis offset between the two clocks (e.g. the captured WAV's sample 0
does not correspond to input-stream frame 0 once the maxed input buffer + startup drain gap are folded
in, and/or a systematic getTimestamp latency-reporting convention). It is **constant** (residual std is
small), so it is a calibration term, not jitter -- irrelevant to the "is the spread benign" question,
which turns on the std collapse. Confirming that constant is *honest* (that the Pixel's reported
timestamps aren't lying) is precisely the independent loopback check, still pending the rig. So the
verdict: the spread is substantially removable harness jitter (validated), on top of a fixed offset the
loopback will later pin down.

**Budget check (added 2026-07-08).** "Inside the 15 ms budget" undersells how tight this is. If the
5.5 ms residual std were all real alignment error, a *single* overdub pair (two tracks, each with an
independent ~5.5 ms-std error vs. the shared reference) has a pairwise-difference std of ~7.8 ms --
95th percentile ~15 ms, the entire top-level ceiling consumed at one hop, before any chain. It also
exceeds Test 1a's ≤5 ms allowance as a raw number. How much of the 5.5 ms is correlator/timestamp
quantization (harness measurement noise) vs. real product-path error is therefore load-bearing; the
in-basis calibration click (`test2-step2-plan.md` item 11) gives per-capture truth in the same
measurement basis and is what decomposes it. See `prototype-plan.md` "Quantitative thresholds"
point 4 for the full reconciliation.

Study captures live in the gitignored `analysis/timestamp_study/` (durable record is this section).
Not yet done: repeating the decomposition across *varied* physical cells (the cross-cell spread also
carries real acoustic differences the same-cell study deliberately excludes), and the loopback honesty
check.

## Next steps (post-sweep)

- ~~**Diagnose the GCC-PHAT failure**~~ -- done (see "Band-limited PHAT diagnosis + population
  re-run" above): cause (b), band-limited bleed, confirmed; band-limiting recovers 35/36.
- ~~**Constrain the GCC-PHAT lag search to a plausible window**~~ -- done (item 7a above): `gcc_phat`
  `lag_window`, `(0, 300 ms)` default in the sweep script; the -15.25 s wraparound is gone.
- ~~**Re-check the PSR sidelobe-exclusion vs the post-bandpass main-lobe width**~~ -- done (item 7b
  above): measured lobe is 1 sample (PHAT keeps the peak sharp); `psr_exclusion=2` was already
  adequate, the suspected miscalibration was not real, no change made.
- ~~**Diagnose the lone below-6 dB cell**~~ -- done (see "Edge-cell diagnosis" above):
  `loud_far_facedown_none` is HF-rattle-contaminated (loud+facedown into the resting surface), an
  edge condition, not an alignment failure; its offset is band-robust at 87.10 ms.
- ~~**Test whether a narrower band (1000-4000 Hz) is a strict improvement**~~ -- done, **rejected**
  (see "band trade-off" above): it clears 36/36 but demotes the gate-critical baseline confident ->
  minimum. Keep 500-4000. `gcc_phat_1000_4000_results.csv` retained for the record.
- ~~**Decompose the 61-151 ms offset spread with hardware timestamps (no loopback rig needed).**~~ --
  **done (see "Stream-timestamp decomposition confirmed" above).** Same-cell x9 study: subtracting the
  `getTimestamp` stream offset collapses the run-to-run std 13.4 -> 5.5 ms (59%), confirming most of the
  spread is per-session harness start-jitter, benign and removable. A fixed ~201 ms residual constant
  remains for the loopback rig to calibrate. Still to do: repeat across *varied* cells, and the loopback
  honesty check.
- ~~**Establish Test 1's loopback ground-truth latency** so the ±2 ms half of the pass bar can be
  judged~~ -- **superseded (2026-07-08): the loopback number cannot judge that bar** (wrong route --
  wired USB, not speaker->mic -- and wrong measurement basis vs. these captures' ~201 ms constant).
  Replaced by: **embed an in-basis calibration click in the reference track** and judge the GCC-PHAT
  offset against the click-derived per-capture offset in the same WAV (`test2-step2-plan.md` Next
  steps item 11). The rig's remaining job is the `getTimestamp` honesty check. Until either exists,
  the 97 ms offset is internally consistent but unverified against truth.
- **Vocal-interference injection study (added 2026-07-08; Test 2 step 3 in `prototype-plan.md`).**
  Mix a dry close-mic vocal take into the existing 36 captures at controlled vocal-to-bleed ratios
  and re-run the band-limited GCC-PHAT: this sweep measured bleed against a quiet room, but
  production correlates through a loud vocal sitting exactly in the 500-4000 Hz analysis band. Pin
  the realistic ratio *before* running; the baseline cell at that ratio must still clear the bar.
  Pure Python + existing captures; no device time.
- Write the dedicated AGC-probe script (`analysis/scripts/probe_agc.py` or similar) that
  decomposes the gain-ratio compression per orientation (subtract noise floor in the power
  domain, fit RMS vs gain, separate device-level from coupling-path compression).
- Add a `reflector_geometry` (or free-text `setup_notes`) field to `ConditionMetadata` so the
  class of silent contamination that forced the redo (desk-below vs wall geometry) cannot recur
  on a future sweep -- see "Discarded captures" below.

## Discarded captures (do NOT feed into analysis)

The first six cells of the session were captured with the phone ~15 cm *above a desk surface*,
the desk treated as the "large reflecting surface." That geometry collapses the distance and
orientation axes (the desk is both the distance referent and the face-down resting surface) and
cannot extend to `far` (2 m above a desk is not feasible indoors). They were pulled aside to
`analysis/sweep_discarded_desk_geometry/` (gitignored) with their own README, and the on-device
sweep dir was wiped before the redo. A pre-session `conversational_armslength_faceup_none`
capture (timestamp 1783290866442) was also discarded -- it used the old 5.89 s reference asset
before the APK was rebuilt with the 15.25 s clip. All seven are clean captures (the contamination
axis held); the discard is purely about geometry + asset consistency, since `ConditionMetadata`
records no `reflector_geometry` field that would let a future reader tell them apart from a
valid cell.
