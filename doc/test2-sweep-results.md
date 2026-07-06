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

## Next steps (post-sweep)

- **Diagnose the GCC-PHAT failure** (see "GCC-PHAT offline pass" above) before changing the
  reference or the correlator -- measure the reference's autocorrelation PSR and the capture's
  spectrum vs the reference to split cause (a) from cause (b).
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
