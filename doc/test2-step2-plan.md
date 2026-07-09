# Test 2 Step 2 — Real-Bleed Recording: Implementation Plan

Implementation plan for `prototype-plan.md`'s Test 2 step 2 ("Real-bleed recording, one phone"):
record the clean beatbox track, play it back through the phone's own speaker while simultaneously
recording the overdub mic, sweep playback volume / orientation / distance / obstruction, and hand
the captures to the GCC-PHAT implementation from step 1 to map where the correlation peak degrades.

**Status (2026-07-08): the step-2 pass bar is met.** Session A of the click-gated re-capture
passed 11/11 (baseline cell × 9 repeats plus both known-worst extreme cells) under the honest
click-anchored gate. Remaining work is confirmatory or optional — see "Next steps" at the end.
Detailed measurements and findings live in `doc/test2-sweep-results.md`; this doc holds the
harness design, the physical protocol, and the item-by-item work log.

## Sequencing dependencies (both resolved)

Two dependencies were open when this plan was written:

- **The ±2 ms ground-truth referent.** Originally "Test 1's loopback measurement"; that comparison
  is invalid — the rig measures the wired-USB route (not speaker→mic) and lives in a different
  measurement basis than the harness's captures. The bar is judged against an **in-basis
  calibration click** embedded in the reference track (item 11 below; see prototype-plan.md's
  "Ground-truth correction"). The rig's remaining role is the independent `getTimestamp` honesty
  check.
- **Test 2 step 1 (Python GCC-PHAT):** implemented and passed its synthetic-validation gate
  (`analysis/src/overdub_analysis/gcc_phat.py` + `synth.py`).

## Implementation status (condensed; full history in git and `test2-sweep-results.md`)

All build-out stages are done and verified on a physical Pixel 10:

- **Harness module** (`:harness`, `com.overdub.harness`) — the repo's first Android code.
  Pure-Kotlin pieces (Tier-1 unit-tested): `wav/WavWriter.kt` + `WavReader.kt`,
  `metadata/ConditionMetadata.kt` (kotlinx.serialization JSON sidecar),
  `condition/ConditionMatrix.kt` (the 36-cell matrix + `conditionFromId()`), `dsp/Rms.kt`,
  `timestamp/StreamOffset.kt` (`computeStreamOffset`, mic-lags-positive convention). Build: NDK
  28.2.13676358, CMake 3.31.6, Oboe 1.9.3 via prefab; ABI filters `arm64-v8a`/`armeabi-v7a` only
  (no emulator for audio, per `CLAUDE.md`).
- **Native full-duplex engine** (`harness/src/main/cpp/native_engine.{h,cpp}` + `native_bridge.cpp`
  + `NativeBridge.kt`): output+input streams in LowLatency/Exclusive,
  `InputPreset::VoiceRecognition`, `setDeviceId()` speaker/mic route forcing, a lock-free SPSC
  ring buffer drained by a dedicated writer thread (never the audio callback), per-sample playback
  gain, XRun latching, ring-overflow drop counting, `getTimestamp` single-read-at-`stop()` plus
  multi-read sampling from the drain thread (item 13 (b)). `capture/CaptureEngine.kt` pins
  STREAM_MUSIC volume, queries the native rate, forces the built-in speaker/mic route, runs the
  RMS sanity gate to Logcat, and writes the WAV + JSON sidecar via the Tier-1 pieces.
- **Tier-2 instrumented tests: 8/8 green on the Pixel 10** (API 36; 48000 Hz native, 96-frame
  bursts, LowLatency/Exclusive granted; baseline capture RMS ~320–340). The initial cold-run XRun
  flakiness was diagnosed on-device (input-side only, during warmup — the input stream started
  before its drainer was live) and fixed by starting output first, gating input reads behind an
  `mInputStarted` flag, draining all available input per callback, and growing the buffers; five
  consecutive cold runs then showed 0/0 XRuns deterministically. **Open caveat:** the green
  `speakerRouteHolds` ran with *no headset connected* — the headset-connected override variant
  (Tier 2 list below) has **never run**, so whether `setPreferredDevice()` can demote an active
  headset route is unverified, which also gates the feasibility of design-summary.md's
  forced-chirp fallback.
- **The manual 36-cell Tier-3 sweep ran 2026-07-05**: 36/36 clean captures (0 XRuns, 0 dropped,
  `builtin_speaker`, 48 kHz), driven per-cell by `harness/scripts/run_sweep_cell.sh` as 12
  physical arrangements × 3 programmatic volumes. The first six cells were captured with a
  desk-below-as-reflector geometry, discarded, and redone with the canonical wall-as-reflector
  setup (the origin of item 9's `reflector_geometry` field). Full matrix, manifest, and findings:
  `test2-sweep-results.md`.
- **Analysis integration** (Components §4) is built and exercised. The analysis history — full-band
  GCC-PHAT failing 0/36, the band-limited (500–4000 Hz) recovery, the discovery that the recovered
  offsets were ~+187 ms beat-period *aliases*, and the click-anchored gate that produced the
  Session A pass — is logged under items 7, 10, and 11 in "Next steps" below, with full write-ups
  in `test2-sweep-results.md`.

## Components to build

### 1. Reference track asset

A short (10-20s), clean, dry beatbox recording, bundled as a raw PCM WAV asset at the device's
native output sample rate (queried via `AudioManager.PROPERTY_OUTPUT_SAMPLE_RATE`, per `CLAUDE.md`'s
audio pipeline guidance — don't hardcode 44.1/48kHz). Reuse whatever rate Test 1 confirms as the
device's native rate, so ground-truth and real-bleed data aren't confounded by a resampling
mismatch between tests.

**Status:** done. The real `boots.wav` (48 kHz mono, 15.25 s) is bundled as
`harness/src/main/assets/reference_track.wav`, since item 11 with a 1.000 s calibration lead-in
prepended (total 16.25 s; click onset at sample 9600, beatbox content from sample 48000). Neither
the source recording nor the bundled asset is committed (audio never in Git — regenerate after a
fresh checkout per `reference_track_README.md`, which also records the pairing rule: click-less
legacy captures must be analyzed against a click-less reference).

### 2. Android capture harness (new Gradle module — first Android code in this repo)

A minimal debug-only harness app, not a feature of the eventual product (explicitly out of scope
per `prototype-plan.md`: "Sharing/forwarding flow," "UI" are downstream). Scope it as throwaway
prototype code that's expected to be deleted or heavily rewritten once the real app starts.

- **Full-duplex Oboe stream**, following Oboe's recommended full-duplex pattern (one callback —
  attached to the output stream — that also synchronously pulls from the input stream each call),
  the same "single continuous stream, no independently-scheduled players" principle Test 1 is
  validating, so this harness doesn't introduce its own version of the seam risk Test 1 exists to
  catch. `PerformanceMode::LowLatency`, `SharingMode::Exclusive`, matching `CLAUDE.md`/Test 1
  conventions. The callback itself must stay non-blocking and allocation-free — no file I/O on this
  thread (see "Input side," below) — since anything that stalls it risks producing the exact
  underruns Tier 2's zero-XRun test exists to detect, as a harness artifact rather than a real
  device/config finding.
- **Output side**: plays the bundled reference track through the built-in speaker (force via
  `setPreferredDevice()` if a headset happens to be connected, so a stray Bluetooth auto-route
  doesn't silently invalidate a capture — log the active route into metadata either way).
- **Input side**: set an explicit low-processing `InputPreset` (Oboe: `InputPreset::VoiceRecognition`,
  or AAudio's equivalent) rather than accepting the platform default — default mic sources on many
  OEMs enable Automatic Gain Control and/or Noise Suppression, either of which would auto-compensate
  for a quieter bleed signal and mask exactly the SNR degradation this volume/distance/obstruction
  sweep exists to map. Log the selected preset into metadata (`input_preset`), same rigor as
  `output_route`. The callback pushes captured frames into a lock-free ring buffer; a dedicated
  writer thread (never the audio callback) drains it and performs the actual WAV file write to
  app-private storage.
- **Condition tagging**: each run takes a condition id (e.g. `quiet_armslength_facedown`) as an
  input (instrumentation argument or harness-UI field) and writes a JSON sidecar next to the WAV
  containing: `condition_id`, `playback_volume` (see below), `distance_cm`, `orientation`,
  `obstruction`, `output_route`, `input_preset`, `sample_rate`, `xrun_count`, `device_model`,
  `timestamp` (plus, added later: `stream_volume_index`, the six stream-timestamp fields of
  item 10, `reflector_geometry` of item 9, and the `timestamp_samples` multi-read list of
  item 13 (b) — all nullable, omitted rather than faked when unavailable). The WAV/JSON filenames
  are keyed on `{condition_id}_{timestamp}` (or a run index), not `condition_id` alone — a retry
  after a bad run must not silently overwrite the prior attempt's files before anyone's had a
  chance to compare them.
- **Playback volume**: control via `AudioTrack.setVolume()` (a programmatic gain fraction) rather
  than relying on the human to set the OS media-volume slider — makes the volume axis of the sweep
  exactly repeatable across conditions and re-runs. `setVolume()` is a gain applied on top of the
  device's `STREAM_MUSIC` volume index, not a replacement for it — if that index drifts between
  sessions, the same gain fraction produces a different actual output level. The harness must pin it
  to a fixed value (`AudioManager.setStreamVolume(STREAM_MUSIC, <fixed index>, 0)`, e.g. max) once at
  startup and log the index into metadata, so `playback_volume` is reproducible across runs and
  devices rather than only reproducible relative to whatever the slider happened to be at. Tradeoff:
  this bypasses the OS's own volume-curve/loudness compression, so it's a controlled proxy for
  "playback volume," not identical to a user manually turning the phone's volume rocker — worth a
  one-line caveat in the results, not a blocker.
- **XRun logging**: call `AAudioStream_getXRunCount()` (or Oboe's equivalent) on both streams after
  each capture, same as Test 1. A non-zero count doesn't need to hard-fail the whole harness, but
  must be written into that capture's metadata so a contaminated file is never silently fed into
  analysis as if it were clean.
- **On-device sanity gate**: compute RMS of the captured buffer before writing the file and log it,
  so an operator tailing `adb logcat` on the host machine — the channel they're already watching,
  since each run is triggered via `adb shell am instrument` — gets immediate pass/fail-style
  feedback ("bleed reached the mic," not "let me find out days later during offline analysis")
  *regardless of phone orientation*. An on-screen toast can fire in addition for conditions where
  the screen happens to be visible, but logcat, not the toast, is the relied-upon channel — a
  toast-only design would be silently unavailable for exactly the facedown/pocketed/obstructed
  conditions the matrix deliberately includes.

### 3. Condition-sweep driver

Drive the matrix (volume × distance × orientation × obstruction) as a parameterized instrumented
test rather than free-form manual button-pressing, so every run is automated except the physical
step of positioning the phone.

**Concrete matrix values** (fixed here so the condition-matrix generator test below and the
"baseline realistic condition" referenced throughout this doc have one unambiguous definition):

| Axis | Values |
|---|---|
| Volume (gain fraction, see "Playback volume" above) | quiet (0.2), conversational/**baseline** (0.6), loud (1.0) |
| Distance | near (~15cm), arm's length (~50cm, **baseline**), far (~2m) |
| Orientation | face-up (**baseline**), face-down |
| Obstruction | none (**baseline**), pocketed (denim/fabric layer) |

3 × 3 × 2 × 2 = **36 conditions**. The **baseline realistic condition** referenced in Tier 2, Tier 3,
and the exit criteria is the single cell where every axis takes its baseline value: conversational
volume (0.6), arm's length, face-up, unobstructed.

- Each condition is one test invocation, taking the condition id as an instrumentation argument
  (`adb shell am instrument -e condition <id> ...`) or iterating a `@Parameterized` list if driven
  from within a single test class.
- The human's job per condition: position the phone (distance/orientation/obstruction), adjust real
  ambient noise if relevant, then trigger the run. Everything downstream of "trigger" — playback,
  capture, WAV write, metadata tagging, XRun check, RMS sanity check — is automated.
- This maximizes automation without pretending the physical arrangement itself can be automated —
  consistent with `CLAUDE.md`'s standing rule not to fake real acoustic/physical conditions in
  automated tests.

**Physical setup and positioning protocol.** Because playback and capture are on the *same* phone,
the speaker↔mic spacing is fixed by the chassis and the *direct* bleed path never changes — the four
axes vary the *reflected/reverberant and mechanically-coupled* component layered on top of it. That
makes the `distance` axis ambiguous unless its referent is pinned, so it is fixed here:

- **Distance referent:** `distance_cm` is the distance from the phone to the nearest large reflecting
  surface (wall, or the operator's body), measured with a tape, the phone otherwise in free air on a
  stand/tripod. "Near" (~15cm) is a strongly-reflective placement, "far" (~2m) a near-anechoic one —
  that reflection/reverberation gradient is what this axis maps. (It is *not* varying speaker↔mic
  distance; that is fixed on a single device.)
- **Orientation:** face-up = speaker/mic firing into open air; face-down = firing into the resting
  surface (on the Pixel 10's bottom + earpiece speakers this couples strongly into whatever it rests
  on).
- **Obstruction — pocketed:** one consistent denim/fabric layer laid over the phone (same fabric,
  same layer count, same coverage every run), not an actual worn garment — a worn pocket is too
  variable to reproduce.
- **Volume:** nothing physical — it is the programmatic gain (0.2 / 0.6 / 1.0) with `STREAM_MUSIC`
  pinned to max. The operator must **not touch the volume rocker** during the sweep, or the pinned
  index desyncs from `stream_volume_index` in the metadata and the volume axis stops being
  reproducible.

**Environmental assumptions held constant across all 36 cells** — the matrix deliberately varies four
things, so everything else must be constant or the cells aren't comparable to each other or to the
baseline: same room (reverb geometry is a hidden variable that would confound the distance axis),
stable low ambient noise floor (a passing noise burst quietly lowers *that* capture's SNR, and the RMS
sanity gate assumes a steady floor), no other audio sources, the same resting-surface material, the
phone physically still during capture (a stand beats a hand — handling noise adds non-reproducible
energy the correlation then has to fight), and **no headset connected** (the baseline sweep assumes
built-in-speaker routing; `output_route` in metadata is the check that this held — the
headset-override case is a separate Tier-2 test, not part of the 36-cell sweep).

**Operator loop per cell:** (1) physically arrange the phone for the condition — the only manual step;
(2) trigger the run (`adb shell am instrument -e condition <id> ...`); (3) watch `adb logcat` for the
`RESULT`/RMS sanity line — the relied-upon feedback channel, since a facedown/pocketed phone can't
show a toast; (4) if the RMS reads as silence or the placement was fumbled, retry — timestamped
filenames (`{condition_id}_{timestamp}`) mean a retry never overwrites the bad attempt, so both
survive for comparison.

### 4. Data pull + analysis integration

- `adb pull` the WAV+JSON pairs off-device to a working directory under `analysis/`. Verified working
  on the Pixel 10:
  `adb pull /sdcard/Android/data/com.overdub.harness/files/sweep <dest>` pulls the pairs directly —
  the harness installs to the **personal profile (user 0)** by default and its app-private external
  dir is shell-readable and pullable (no scoped-storage or work-profile obstacle). **The one real
  gotcha: `gradlew connectedAndroidTest` uninstalls the harness on completion, which wipes app-private
  storage and deletes the captures.** So drive the real sweep with `am instrument` against a
  persistently installed app+test APK (`adb install -r` both, then
  `adb shell am instrument -w -e condition <id> -e class ...ConditionSweepTest#sweepOneCondition
  com.overdub.harness.test/androidx.test.runner.AndroidJUnitRunner`), not the gradle connected-test
  task, or the data is gone before it can be pulled.
- Feed each capture through the click-gated analysis pipeline
  (`analysis/scripts/run_click_gated_sweep.py` — the honest gate per item 11; the earlier
  `run_gcc_phat_sweep.py`/`run_bandlimited_gcc_phat_sweep.py` are the alias-era predecessors),
  recording the click-anchored offset, `|gcc − click|` error, and diagnostics per condition
  alongside each file's metadata.

## Test plan

### Tier 1 — JVM unit tests (no device, run on every change)

Pure-Kotlin logic with no Android framework dependency:

- **WAV writer correctness**: given a sample buffer, header fields (sample rate, bit depth, channel
  count, byte order, data-chunk size vs. actual sample count) are correct. Write this as a pure
  function (`ByteArray`/`ShortArray` in, WAV bytes out) specifically so it's testable without any
  framework object.
- **Condition metadata JSON round-trips** (encode → decode → equals original) including edge cases
  (missing optional fields, unusual condition-id strings).
- **Condition-matrix generator** produces the expected cross-product of volume × distance ×
  orientation × obstruction (the 3 × 3 × 2 × 2 values fixed in Components §3) with no duplicates and
  exactly 36 entries.
- **RMS/noise-floor calculation** against known synthetic buffers (silence, full-scale sine, a buffer
  with an injected floor) returns the expected values — basic DSP math, no device needed.

### Tier 2 — Instrumented, on-device automated tests (`connectedDebugAndroidTest`, real hardware, real Oboe/AudioRecord/AudioTrack — no mocks, per `CLAUDE.md`)

All green on the Pixel 10 except the last (never run — needs a headset physically connected):

- **Full-duplex stream opens successfully** in `LowLatency`/`Exclusive` mode on the target device.
- **Zero XRuns during a short real capture** of the bundled reference track — hard-fail assertion,
  same bar Test 1 uses, since an underrun during a real-bleed capture invalidates that capture's data
  the same way it would invalidate Test 1's offset measurement.
- **Captured file duration matches expected playback duration** within a defined tolerance.
- **Captured file is non-silent** (RMS above a defined noise floor) at a fixed default condition
  (known volume, phone at arm's length, unobstructed) — an automated smoke test that bleed reaches
  the mic at all, without requiring a human to judge audio quality. This is a proxy check for one
  condition, not a substitute for the full physical sweep, which deliberately varies conditions to
  find where this stops holding.
- **Captured file format matches expectations** — same sample rate as the device's queried native
  rate, correct bit depth and channel count.
- **Condition metadata is correctly tagged end-to-end**: given an input condition id (as an
  instrumentation argument), the resulting filename/JSON sidecar contains the expected values —
  confirms the tagging pipeline on-device, not just the JVM-level encoder in isolation.
- **Repeated captures show no resource leak or crash across N back-to-back runs** — streams open and
  close cleanly each time. This matters concretely here since a human will be running this dozens of
  times across the real condition matrix; a leak that only shows up on run 15 would otherwise
  surface as a confusing mid-sweep failure.
- **Speaker-route override actually holds with a real headset connected** — **not yet run** (manual
  precondition: a wired or Bluetooth headset physically paired/plugged in before this specific test
  method). `setPreferredDevice()` is called on the assumption it can demote an active headset route
  for one stream (Components §2), but that assumption is unverified. If it fails on the target
  device, that's a real finding: the baseline-condition sweep is only valid with no headset
  connected until this is resolved, and the headphone-monitoring alignment path falls back to
  Test 1a/design-summary.md's other options.

### Tier 3 — Manual on-device checkpoints (what neither tier above can honestly assert, per `CLAUDE.md`)

- **The physical condition sweep itself** — positioning the phone at each real
  distance/orientation/obstruction combination and adjusting real ambient conditions. No automated
  test can honestly assert "this represents a realistic bleed condition"; this requires a human
  operator, same reasoning `CLAUDE.md` already applies to audio-focus/real-notification testing.
- **Sanity-listening to a sample of captured files** (at minimum the baseline realistic condition)
  for gross artifacts — clipping, dropout, glitch — that RMS/duration checks wouldn't necessarily
  catch.
- **Running the Python analysis** against each captured file, recording the click-anchored offset
  and gate verdict per condition, and comparing against the thresholds already fixed in
  `prototype-plan.md`.
- **Judging the overall pass/fail bar**: per `prototype-plan.md`, the baseline realistic condition
  must clear the gate — this judgment call is inherently manual, decided in advance by the existing
  threshold section rather than made after seeing the data. Edge conditions (quiet volume, phone in
  a pocket) failing is an acceptable outcome that becomes a documented UX constraint, not a test
  failure.

## Exit criteria

Reiterating `prototype-plan.md`'s bar (not redefining it here): the baseline realistic condition
must clear a recovered offset within ±2ms of the in-basis calibration-click ground truth (PSR
demoted to a diagnostic after the alias finding — see item 11). Edge-condition failures are
documented as UX constraints (e.g., "app enforces a minimum playback volume"), not grounds to fail
the test outright. **Met 2026-07-08 (Session A: 9/9 baseline repeats plus both extreme cells
inside ±2 ms).**

## Cross-device generalization of the Pixel 10 results

The Tier-2 numbers above (zero XRuns after the warmup fix, baseline capture RMS ~320-340, 48000 Hz /
96-frame bursts, streams granted `LowLatency`/`Exclusive`) are gathered on a *single* Pixel 10, and
should be read as a **favorable-case existence proof, not a population estimate**. The Pixel is close
to a best case for this approach — clean near-AOSP audio stack, well-behaved AAudio, good transducers.
Preset honesty is *not* established even on the Pixel: sweep finding 2 in `test2-sweep-results.md`
shows gain-ratio compression despite `VoiceRecognition`, so the AGC-linearity probe below is what
would decide it. `prototype-plan.md`'s Test 2 "Cross-device generalization" carries the full
analysis; the harness-specific points:

- **What generalizes** is the algorithm and the pass/fail *criteria* — they're device-independent,
  validated by the synthetic step 1 with no phone in the loop. The ±2ms bar is measured against
  *that device's own* in-basis ground truth (the calibration click), so it's self-relative and
  transfers even though the absolute latency does not.
- **What does *not* generalize** is whether a given device's real bleed clears that floor — an
  empirical per-device question dominated by (a) speaker/mic hardware SNR (the Pixel 10's baseline RMS
  is a Pixel-10 number) and, the bigger wildcard, (b) whether the OEM actually honors the requested
  `InputPreset::VoiceRecognition`. Residual OEM AGC/NS would auto-compensate a quiet bleed and flatten
  the very volume/distance SNR gradient this sweep exists to map. Secondary unknowns: whether
  LowLatency/Exclusive is granted at all, the native sample rate (affects sample-count arithmetic, not
  physics), and route-forcing quirks.
- **The harness is already built to re-measure this with no code change:** the JSON sidecar logs
  `device_model`, `sample_rate`, `input_preset`, `xrun_count`, and `stream_volume_index`, so pointing
  the same sweep at a second device is "run it again, compare tables." Cross-device variance stays out
  of scope for *this* step (single device, per `prototype-plan.md`), but the instrumentation is ready
  and `armeabi-v7a` is already in the ABI filters for an older second phone.
- **Not yet built: the on-device AGC-linearity probe.** Play a fixed tone at two known gains (e.g.
  0.3 and 0.9) and check whether captured RMS preserves the ~9.5dB ratio or compresses it;
  compression = AGC still active on that device = its SNR-mapping is compromised. Required before
  trusting a *non-Pixel* sweep, since it isolates the single biggest cross-device wildcard rather
  than discovering it from confusing PSR data later. (The *offline* decomposition over existing
  captures is item 8, done; this on-device tone probe is its remaining half.)

## What this doesn't cover

Echo cancellation, onset detection, cross-device variance (second phone), and chain-of-forwarding
drift (Test 3) are all out of scope here, per `prototype-plan.md`'s existing scoping — this plan
covers only the capture-and-measure step for a single device.

## Next steps (Stage 2)

Item numbers are historical and preserved because other docs and the analysis scripts' docstrings
cite them (e.g. `test2-sweep-results.md` cites "item 10"; `run_click_gated_sweep.py` cites
"item 11c"). Completed items are collapsed to their outcome plus a pointer; the full write-ups
live in `test2-sweep-results.md`.

### Open

- **Item 11 (c), Session B — the remaining ~9 physical arrangements → the full 36-cell map.**
  Confirmatory-only: Session A passed cleanly on the gate cell and both known-worst extremes, so
  Session B restores the per-cell alignment/UX-constraint map under the honest gate when
  convenient. (Had an extreme failed, B would instead have been needed to locate the failure
  boundary.) Judge with `run_click_gated_sweep.py`; also re-run item 12's injection against the
  new captures (confirmatory).
- **Item 13 (c) — optional headset-route timestamp batch**, if a wired USB-C headset is on hand:
  timestamp variance/outlier statistics on the exact route Test 1a targets (the click won't anchor
  without bleed, but pure timestamp statistics don't need it; honesty still waits for the rig).
- **Item 8, remaining half — the on-device two-gain AGC tone probe** (see "Cross-device
  generalization" above). Needed before any non-Pixel sweep is trusted.
- Optional cleanup: fold the band-pass into `run_gcc_phat_sweep.py` as a `--band-pass` flag so
  there's one sweep script instead of two, now that the correlator has settled.

### Done (work log)

1. **NDK/CMake wiring into `harness/build.gradle.kts`** — done 2026-07-05.
2. **Full-duplex native engine + JNI bridge** — done 2026-07-05; on-device verification via
   Tier 2 (see "Implementation status").
3. **Condition-sweep driver** (`ConditionSweepTest.kt` + `conditionFromId()`) — done 2026-07-05.
   XRun/ring-overflow/non-speaker-route hard-fail as retry signals; sub-floor RMS recorded as an
   edge-cell finding, not a failure.
4. **Tier-2 instrumented tests** — done, 8/8 green on the Pixel 10 (2026-07-05), including the
   startup-XRun diagnosis/fix. The headset-override test remains un-run (see Tier 2).
5. **Real reference track** — done 2026-07-05: `boots.wav` bundled (later regenerated with the
   item-11 calibration lead-in). See Components §1.
6. **Tier-3 manual sweep + data pull + first analysis pass** — done 2026-07-05: 36/36 clean
   captures; full-band GCC-PHAT failed 0/36 (PHAT over-weighting noise-dominated HF / bass-rolled
   LF, diagnosed with `diagnose_gcc_phat.py`; the reference itself was fine).
7. **Band-limited pass trustworthiness** — done in four sub-items:
   - **7a — lag window:** `gcc_phat` gained an optional `lag_window` restricting argmax and PSR
     sidelobe search; killed the −15.25 s wraparound alias. (The alias-era `(0, 300 ms)` default
     was later superseded by item 11a's click-anchored ±90 ms window.)
   - **7b — PSR exclusion vs. post-bandpass lobe width:** measured first-null half-width is
     1 sample (PHAT re-whitens, keeping the peak impulse-sharp); `psr_exclusion=2` was already
     adequate — a "measure before changing, the default was fine" outcome.
   - **7c — per-cell table** (`gcc_phat_bandlimited_results.csv`, offsets 61–151 ms, mean 97.2,
     std 17.5): recorded, and later revealed by item 11 to be an *alias-era* table, not a pass.
   - **7d — edge cell + band decision:** the lone below-6 dB cell (`loud_far_facedown_none`) is
     HF-rattle contamination, not an alignment failure; the narrower 1000–4000 Hz band was
     **rejected** (clears 36/36 but demotes the gate-critical baseline cell) — **keep 500–4000**.
     Lesson: PSR is a fragile, band-sensitive *label* while the offset is band-robust; don't
     re-tune the band to chase one cell.
8. **Offline AGC-probe decomposition** (`analysis/scripts/probe_agc.py`) — done 2026-07-08 over
   the existing 36 captures: device-level compression exponent 0.850 ± 0.011 (face-up), coupling
   path adds ~0.15 (face-down 0.702 ± 0.025); floor-robust, so the compression is real. The
   input-AGC vs output-amp split needs the on-device tone probe (open, above).
9. **`reflector_geometry` metadata field** — done 2026-07-08: nullable, null = *unknown* (never
   defaulted to a geometry the operator didn't assert); `run_sweep_cell.sh` asserts the canonical
   `wall`, overridable via `REFLECTOR_GEOMETRY=<label>`. The on-device plumbing check caught a
   **stale test APK** whose sidecar silently lacked the field — the incident behind `CLAUDE.md`'s
   native-clean-rebuild rule.
10. **Per-stream hardware timestamps + offset-spread decomposition** (Test 1a pulled forward) —
    done: `readStreamTimestamps()` at `stop()` (latched), pure-Kotlin `computeStreamOffset`, six
    nullable sidecar fields, `decompose_offset.py`. The same-cell ×9 study showed subtracting the
    `getTimestamp` stream offset collapses the run-to-run offset std 13.4 → 5.5 ms — most of the
    61–151 ms spread was benign per-session harness start-jitter (which the product, self-measuring
    within one continuous session, does not have). The leftover "~201 ms constant" was later
    decomposed by item 11's cross-check as ~14–15 ms of genuine measurement-basis residual plus a
    ~187 ms correlator *alias*. Write-ups: `test2-sweep-results.md` "Stream-timestamp decomposition
    confirmed" and "Calibration click cross-check."
11. **In-basis calibration click + honest gate + staged re-capture** — done except Session B
    (open, above). The pieces, in order:
    - **The click:** a 20 ms Hann-windowed 500–4000 Hz linear chirp inside a 1.000 s lead-in,
      detected by a polarity-insensitive matched filter (`overdub_analysis/calibration_click.py`;
      `prepend_calibration_click.py` regenerates the asset with a round-trip self-check — onset
      sample 9600, quality 20.5 dB).
    - **The cross-check that paid for everything:** the click survived the real speaker→mic path
      and exposed the whole +61..+151 ms offset family — "confident" PSR included — as **~+187 ms
      beat-period aliases** of negative true offsets (true baseline −79.62 ms vs. GCC-PHAT's
      +107.12 ms). PSR and the positivity lag window both blessed the alias.
      `check_reference_periodicity.py` maps the reference's self-similarity (plain band-limited
      autocorrelation — PHAT-of-self hides the beat-period peak).
    - **11a — alias-gate remedy:** the alias peak is genuinely ~12 dB larger than the true peak,
      so no wide lag window can reject it. The gate: a click-anchored **±90 ms window** (narrower
      than half the ~187 ms beat period — a one-beat alias excluded by construction) plus
      **`|gcc − click| ≤ 2 ms`**, PSR diagnostic-only (the true acoustic peak is a multipath
      cluster that can read ~0 dB PSR even when correct). Pipeline: `run_click_gated_sweep.py`.
      A stream-timestamp-anchored window recovered the same true offset — validating the
      product-shaped mechanism (no click at runtime, but `getTimestamp` is available).
    - **11b** — item 9's `reflector_geometry`, landed before the re-capture.
    - **11c — staged re-capture. Session A complete 2026-07-08: 11/11 PASS.** Baseline ×9:
      correlator error mean −1.18 / std 0.25 / max 1.35 ms (the budget error-std); basis residual
      −15.1 ms stable on 8/9 runs, one ~40 ms `getTimestamp` outlier (a Test 1a tail-risk
      finding). Min-bleed cell PASS at −1.21 ms (the SNR failure mode did not materialize; click
      quality *above* baseline). HF-rattle cell PASS at −0.46 ms — its true offset −120.90 ms
      finally replaces the alias-era "band-robust 87.10 ms". Session B: open, above.
12. **Vocal-interference injection study** (Test 2 step 3) — done 2026-07-08:
    - **Record-only vocal-take mode** so the take is in the *same measurement basis* as the bleed
      (same phone, same `VoiceRecognition` chain, speaker emitting silence): `CaptureSpec` /
      `VOCAL_TAKE_SPEC` / `run_vocal_take.sh`, writing to `files/vocal`. Verified zero reference
      bleed (gain-0 RMS 23.7 = bare room floor vs. 1652 at the min-bleed sweep cell).
    - **Take vetting** (`vet_vocal_take.py`): format / no-clip / continuously-active / no-leak,
      with two leak layers — the click matched filter, plus a leak-vs-performance discriminator
      (`leak_detect.py`: a genuine headphone leak is machine-stable to <1 ms per segment; human
      timing jitters by tens of ms). 3/3 takes OK. Protocol learning: the performer must monitor
      the *click-bearing* reference or the click leak-gate is voided (take 1's lesson).
    - **The ratio pin, decided before any PSR results: −12.2 dB** vocal-to-bleed (takes 2 and 3
      agree exactly at realistic close-mic loudness) — the vocal lands *below* the bleed, opposite
      the "loud vocal" assumption.
    - **The injection result** (`vocal_inject.py` + `run_vocal_injection.py`): alignment is
      **immune** — the click-anchored offset unchanged by even 1 sample from +0 to +24 dB in-band
      ratio; the failure mode at +24–30 dB is the vocal burying the *calibration click* (anchor
      lost), not alignment pulling. ~36 dB of margin above the realistic ratio; cross-take robust.
    - **Folded-in synthetic SNR-floor re-measurement**
      (`sweep_snr_floor_real_reference.py`): with the production pipeline the floor is
      **−27..−30 dB in-band SNR, set entirely by click burial** — the anchored correlator posts
      0.00 ms error at every SNR where the click anchors. (The old click-train −30 dB floor did
      not transfer; this replaces it.)
13. **Interim timestamp-variance study** (Test 1a pulled further forward; rig delayed) —
    (a) and (b) done, (c) open (above):
    - **(a) Offline outlier decomposition** (`timestamp_decompose.py` /
      `decompose_timestamp_outlier.py`) — done 2026-07-08: **no reliable single-component
      attribution.** The only cross-run referents available jitter by as much as the 40 ms anomaly
      (frame_delta benign cluster ±24 ms, wall anchors ±40 ms), so single-read sidecars
      under-determine the culprit and no cheap single-read sanity check is validated. This made
      (b)'s multi-read logging load-bearing.
    - **(b) Multi-read logging + unattended batch** (`timestamp_multiread.py` /
      `analyze_timestamp_multiread.py`; ~11 reads/session, 43 baseline captures) — done
      2026-07-08. **The glitch-vs-session-state question is settled: median-of-k is NOT a blanket
      fix.** Two anomalous runs, two different classes: an *isolated glitch* (median of 11 reads
      recovered the true offset; click gate PASSED) — median-of-k works here — and a
      **session-level desync** (input clock ~+35 ms off all session, audio itself misaligned
      78.67 ms, median wrong too, silent to XRun/dropped/route gates — only the click caught it).
      So the product's timestamp mechanism needs median-of-k **plus** a per-capture rejection
      gate; a uniform whole-session shift is invisible even to a line-fit consistency check on the
      reads, so only an independent anchor (click on the speaker route, rig on the headphone
      route) sees the second class. Read-noise std over clean runs ~0.4 ms; outlier rate 2/43
      (thin, but the two-class split doesn't depend on it). Write-up: `test2-sweep-results.md`
      "Multi-read timestamp batch."
