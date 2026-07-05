# Test 2 — Tier-3 condition-sweep results

In-progress capture log for the manual 36-cell condition sweep (test2-step2-plan.md Components
Sec 3). The on-device WAV + JSON captures are gitignored (audio is never committed to this
repo -- see `CLAUDE.md`/memory); this file is the durable, tracked record of what was captured
and what the RMS data already shows. The offline GCC-PHAT pass (Test 2 step 1, `analysis/`)
will fill in PSR / recovered offset per cell once the full matrix is down.

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

## Results so far (18 / 36)

All 18 cells: sanity = PASS, xrun = 0, dropped = 0, route = builtin_speaker, rate = 48000 Hz.
RMS is int16 scale.

### `near` distance (~15 cm from wall) -- 12 cells

| Orientation | Obstruction | quiet (0.2) | conv (0.6) | loud (1.0) |
|---|---|---|---|---|
| face-up   | none     | 1734.8 | 4450.5 | 6561.3 |
| face-up   | pocketed | 1511.7 | 3991.3 | 5992.7 |
| face-down | none     | 3616.7 | 8259.1 | 11103.4 |
| face-down | pocketed | 2956.3 | 7059.3 | 9847.6 |

### `armslength` distance (~50 cm from wall) -- 6 cells

| Orientation | Obstruction | quiet (0.2) | conv (0.6) | loud (1.0) |
|---|---|---|---|---|
| face-up   | none     | 1567.2 | **4126.2** (baseline) | 6153.0 |
| face-up   | pocketed | 1577.2 | 4132.9 | 6160.7 |

### `far` distance (~2 m from wall) -- 0 cells (pending)

### File manifest (18 pairs on-device under `/sdcard/Android/data/com.overdub.harness/files/sweep/`)

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

## Findings so far (from RMS; GCC-PHAT PSR pending)

1. **Orientation is the dominant lever at near.** Face-down gives ~1.7-2.1x the bleed of face-up
   at every volume and obstruction (e.g. loud/near/none: 11103 face-down vs 6561 face-up). The
   Pixel 10's bottom + earpiece speakers couple strongly into the resting pad, redirecting
   energy back at the mic.

2. **Volume scales sub-linearly everywhere -- a device-level compression.** Captured RMS
   compresses the gain ratio by ~15-40% (conv/quiet measured 2.3-2.6x vs 3.0x expected; loud/quiet
   3.1-3.8x vs 5.0x). This is the CLAUDE.md gain-ratio probe result: residual AGC / speaker-amp
   nonlinearity is flattening the volume-axis SNR gradient despite the `voice_recognition` input
   preset. Compression is worse face-down than face-up (see finding 3), so it has two
   superimposed components -- a device-level one and a coupling-path one. A dedicated AGC-probe
   script (to be written in `analysis/scripts/`) should decompose these properly by subtracting
   the noise floor in the power domain before fitting RMS vs gain.

3. **Face-down coupling is mechanically nonlinear.** The face-down/face-up ratio *falls* with
   volume (2.08x at quiet -> 1.69x at loud), and within-arrangement gain ratios compress harder
   face-down (loud/quiet 61% of linear) than face-up (76%). The speaker-pad coupling saturates:
   doubling drive does not double the coupled bleed.

4. **The face-up bleed cleanly decomposes into chassis-direct + wall-reflected.** At armslength,
   pocketed vs none is +/-0.6% (the fabric does nothing), and pocketed near vs pocketed
   armslength is within noise (~3-4%). So the fabric and the distance move attack the *same*
   wall-reflected airborne component, and whichever removes it leaves a residual of
   ~1570 / 4130 / 6160 (quiet/conv/loud) that is **distance- and obstruction-independent** --
   the chassis-direct speaker->mic path (vibrational / non-reflected), which neither repositioning
   nor pocketing can beat. Actionable UX constraint: at face-up, moving or covering the phone
   buys almost nothing past the chassis floor; orientation and volume are the levers that matter.

5. **Distance-to-wall is a weak lever at face-up.** 15 cm -> 50 cm dropped face-up/none bleed by
   only ~6-10% (1734.8 -> 1567.2 at quiet). Whether it drops sharply at `far` (2 m) or only
   matters at face-down is still open -- arrangements 7-8 and 9-12 will tell.

6. **Fabric attenuation is geometry-dependent, not a constant.** Pocketed vs none: ~9-13% at
   near/face-up, ~0% at armslength/face-up, ~11-18% at near/face-down. The discarded desk-below
   geometry showed ~25-34% -- so the pocketed effect is heavily confounded with reflection
   geometry, and a single "pocketed attenuates X%" number is misleading.

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
valid cell. **Follow-up:** add a `reflector_geometry` (or free-text `setup_notes`) field to
`ConditionMetadata` so this class of silent contamination cannot recur.
