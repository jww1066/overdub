# Test 2 Step 2 — Real-Bleed Recording: Implementation Plan

Implementation plan for `prototype-plan.md`'s Test 2 step 2 ("Real-bleed recording, one phone"):
record the clean beatbox track, play it back through the phone's own speaker while simultaneously
recording the overdub mic, sweep playback volume / orientation / distance / obstruction, and hand
the captures to the GCC-PHAT implementation from step 1 to map where the correlation peak degrades.

## Sequencing dependencies (does not block starting)

Two things this step depends on aren't ready yet, but neither blocks *building* the harness below:

- **Test 1's ground-truth latency number.** Test 2's own pass bar (prototype-plan.md) is "PSR ≥ 6dB
  *and* recovered offset within ±2ms of the ground truth already established by Test 1's loopback
  measurement." The loopback rig has been ordered but hasn't arrived, so that ground truth doesn't
  exist yet. This blocks *judging* captured data, not capturing it — the harness, its reference
  track, and all automated tests below can be built and run now.
- **Test 2 step 1 (Python GCC-PHAT).** Now implemented and passing its synthetic-validation gate
  (`analysis/src/overdub_analysis/gcc_phat.py` + `synth.py`, 14 pytest cases green; 6 dB PSR floor
  ≈ −30 dB SNR for a broadband click train via `analysis/scripts/sweep_snr_floor.py`). The
  "is the code correct before using it to map anything" gate is met, so running real captures
  through it will be meaningful once they exist.

Net effect: everything in this doc up through "capture files exist on disk with correct
metadata" can proceed today. Only the final pass/fail judgment against real data waits on the two
items above.

## Implementation status (2026-07-05)

**Done — Stage 1 (Gradle scaffold + Tier 1, no device/NDK needed):**
- Root Gradle project and a new `:harness` module (`com.overdub.harness`) exist at the repo root —
  first Android code in the repo, per Components §2.
- Four of the pure-Kotlin pieces from Components §2/§3 are implemented and unit-tested (Tier 1,
  all passing): `wav/WavWriter.kt`, `metadata/ConditionMetadata.kt` (kotlinx.serialization JSON),
  `condition/ConditionMatrix.kt` (the fixed 36-condition matrix from Components §3), `dsp/Rms.kt`.
- A synthetic placeholder reference track (a generated click track, *not* a real beatbox
  recording) exists via `harness/scripts/generate_reference_track.py`, so the eventual
  playback/capture pipeline has something to play immediately — see the caveat in Components §1
  below; this still needs to be swapped for a real recording before Tier 3 runs.
- NDK 28.2.13676358 and CMake 3.31.6 are installed (via `sdkmanager`).

**Done — Stage 2 step 1 (NDK/CMake/Oboe wiring, no device needed):**
- `harness/build.gradle.kts` wires `externalNativeBuild`/`ndkVersion` to the installed NDK/CMake,
  enables `buildFeatures.prefab`, and adds `com.google.oboe:oboe:1.9.3` as a dependency. ABI filters
  are `arm64-v8a`/`armeabi-v7a` only (no x86/x86_64 — `CLAUDE.md` rules out the emulator for
  anything audio-related).
- `harness/src/main/cpp/CMakeLists.txt` + `native_bridge.cpp` and
  `harness/src/main/java/com/overdub/harness/NativeBridge.kt` are a minimal placeholder that calls
  into Oboe (`oboe::convertToText`), proving the dependency actually links rather than just resolving.
  This is *not* the real capture engine — see Stage 2 step 2 below.
- Verified via a clean `assembleDebug`: `liboboe.so`, `libc++_shared.so`, and `liboverdub_harness.so`
  all land in the APK for both ABIs; Tier 1 unit tests still pass. No device needed for this step.

**Done — Stage 2 step 2 + Tier-2 tests, verified on a real Pixel 10 (2026-07-05):**
- All eight Tier-2 instrumented tests pass on a physical Pixel 10 (arm64-v8a, API 36) via
  `connectedDebugAndroidTest` (`harness/src/androidTest/.../capture/CaptureEngineTest.kt`): streams
  open in LowLatency/Exclusive, zero XRuns, captured duration/format correct, capture non-silent
  (bleed reaches the mic: baseline RMS ~320-340), metadata tagged end-to-end, speaker route holds,
  and 5 back-to-back runs leak-free. Native output rate negotiated at 48000 Hz, 96-frame bursts.
- **XRun finding + fix (diagnosed on-device, per CLAUDE.md "Diagnose before re-implementing").** The
  first cold runs showed non-zero XRuns, and the hard-fail zero-XRun assertion was flaky depending on
  test order (it ran last, after the audio path was warm). Logging each stream separately isolated it
  to the *input* stream during warmup, not the output. Root cause: the output callback only drained
  one burst of input per call and the input stream was started before its drainer (the output
  callback) was live, so the input buffer backed up and overran at startup. Fixed by (a) starting the
  output stream first so the drainer is running before input data arrives, gating input reads behind
  an `mInputStarted` flag; (b) draining *all* available input each callback, not one burst;
  (c) growing the output buffer to 4 bursts and maxing the input buffer. Five consecutive cold runs
  then showed output=0/input=0 XRuns deterministically.
- Still pending for step 2's data to be *judged* (not blocking the engine itself): Tier-3 manual
  sanity-listen, the real beatbox reference track, and Test 1's ground-truth latency number.

**Superseded detail — original build-only verification of step 2:**
- The Oboe/CMake/JNI full-duplex native audio engine now exists:
  `harness/src/main/cpp/native_engine.{h,cpp}` (the `FullDuplexEngine` — output+input streams in
  LowLatency/Exclusive, `InputPreset::VoiceRecognition`, `setDeviceId()` speaker/mic forcing, a
  lock-free SPSC ring buffer drained by a dedicated thread, per-sample playback gain, XRun latching,
  ring-overflow drop counting), `native_bridge.cpp` (rewritten from the linkage placeholder into the
  full JNI lifecycle), and `NativeBridge.kt` (the matching `external` lifecycle functions).
- The Kotlin half of the bridge is `capture/CaptureEngine.kt`: it pins STREAM_MUSIC volume, queries
  the native sample rate, resolves+forces the built-in speaker/mic route, drives the native capture,
  runs the on-device RMS sanity gate to Logcat, and writes the WAV + JSON sidecar by reusing the
  Stage-1 `writeWav`/`ConditionMetadata`/`rms` rather than duplicating that logic in C++. A pure
  `wav/WavReader.kt` was added to decode the bundled reference asset. `ConditionMetadata` gained a
  nullable `stream_volume_index` field (Components §2's "log the index into metadata"); `RECORD_AUDIO`
  + `MODIFY_AUDIO_SETTINGS` were added to the manifest.
- Verified via a clean `gradlew test assembleDebug`: Tier-1 unit tests still pass, both ABIs compile
  and link, and `liboverdub_harness.so`/`liboboe.so`/`libc++_shared.so` land in the APK for both.
  **Everything acoustic in it is unverified** — no physical device has been connected to this repo,
  so stream-open in LowLatency/Exclusive, the speaker-route hold, XRun behavior, and whether bleed
  clears the sanity floor are all untested. That is exactly what Tier 2/3 below exist to check.

**Done — Stage 2 step 3 (condition-sweep driver, code + build only; the sweep itself needs a device):**
- `ConditionSweepTest.kt` (the driver) and `conditionFromId()` (Tier-1-tested id→cell lookup) are
  written and build-verified. The physical positioning protocol and the distance-axis referent are now
  pinned in Components §3, and the cross-device meaning of the Pixel 10 numbers is documented (see
  "Cross-device generalization" below). The *manual* 36-cell on-device sweep has not run.

**Not started — Stage 2 steps 4+ (needs a physical device):**
- Data pull + analysis integration (Components §4) — Test 2 step 1 (Python GCC-PHAT) is now
  implemented and gated (see "Sequencing dependencies" above), so this is no longer blocked on
  it; it's blocked on having real captures to feed through the validated implementation.
- All Tier 2 (instrumented) and Tier 3 (manual on-device) tests below — none of these have run
  since no native capture code exists yet and no physical device has been used against this repo.

See "Next steps," at the end of this doc, for the concrete sequencing of the above.

## Components to build

### 1. Reference track asset

A short (10-20s), clean, dry beatbox recording, bundled as a raw PCM WAV asset at the device's
native output sample rate (queried via `AudioManager.PROPERTY_OUTPUT_SAMPLE_RATE`, per `CLAUDE.md`'s
audio pipeline guidance — don't hardcode 44.1/48kHz). Reuse whatever rate Test 1 confirms as the
device's native rate, so ground-truth and real-bleed data aren't confounded by a resampling
mismatch between tests.

**Status:** a synthetic placeholder (click track, not a real recording) exists today via
`harness/scripts/generate_reference_track.py`, gitignored and regenerated locally rather than
committed (audio files are never committed to this repo — see `CLAUDE.md`). It unblocks pipeline
work but must be replaced with an actual beatbox recording at the confirmed native sample rate
before Tier 3's real condition sweep is run.

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
  `timestamp`. The WAV/JSON filenames are keyed on `{condition_id}_{timestamp}` (or a run index), not
  `condition_id` alone — a retry after a bad run (e.g. operator misplaced the phone, or the sanity
  gate showed silence) must not silently overwrite the prior attempt's files before anyone's had a
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

**Concrete matrix values** (previously unspecified — fixed here so the condition-matrix generator
test below and the "baseline realistic condition" referenced throughout this doc have one
unambiguous definition):

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
  on the Pixel 10 (2026-07-05):
  `adb pull /sdcard/Android/data/com.overdub.harness/files/sweep <dest>` pulls the pairs directly —
  the harness installs to the **personal profile (user 0)** by default and its app-private external
  dir is shell-readable and pullable (no scoped-storage or work-profile obstacle). **The one real
  gotcha: `gradlew connectedAndroidTest` uninstalls the harness on completion, which wipes app-private
  storage and deletes the captures.** So drive the real sweep with `am instrument` against a
  persistently installed app+test APK (`adb install -r` both, then
  `adb shell am instrument -w -e condition <id> -e class ...ConditionSweepTest#sweepOneCondition
  com.overdub.harness.test/androidx.test.runner.AndroidJUnitRunner`), not the gradle connected-test
  task, or the data is gone before it can be pulled.
- Once real captures exist, feed each file through the validated GCC-PHAT implementation
  (`analysis/`), recording PSR and recovered offset per condition into a results table alongside each
  file's metadata.

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
- **Speaker-route override actually holds with a real headset connected**: with a wired or Bluetooth
  headset physically paired/plugged in before this specific test method runs, trigger a capture and
  assert the logged `output_route` is the built-in speaker, not the headset. `setPreferredDevice()`
  is called on the assumption it can demote an active headset route for one stream (Components §2),
  but that assumption is unverified — this closes the loop instead of only logging the route "either
  way" and finding out from stale data later. If it fails on the target device, that's a real
  finding: the baseline-condition sweep is only valid with no headset connected until this is
  resolved, and the headphone-monitoring alignment path falls back to Test 1a/design-summary.md's
  other options.

### Tier 3 — Manual on-device checkpoints (what neither tier above can honestly assert, per `CLAUDE.md`)

- **The physical condition sweep itself** — positioning the phone at each real
  distance/orientation/obstruction combination and adjusting real ambient conditions. No automated
  test can honestly assert "this represents a realistic bleed condition"; this requires a human
  operator, same reasoning `CLAUDE.md` already applies to audio-focus/real-notification testing.
- **Sanity-listening to a sample of captured files** (at minimum the baseline realistic condition)
  for gross artifacts — clipping, dropout, glitch — that RMS/duration checks wouldn't necessarily
  catch.
- **Running the Python GCC-PHAT analysis** (once step 1 exists) against each captured file, recording
  PSR and recovered offset per condition, and comparing against the thresholds already fixed in
  `prototype-plan.md`.
- **Judging the overall pass/fail bar**: per `prototype-plan.md`, the baseline realistic condition
  (comfortable conversational volume, arm's reach, unobstructed) must clear PSR ≥ 6dB and offset
  within ±2ms of Test 1's ground truth. Edge conditions (quiet volume, phone in a pocket) failing is
  an acceptable outcome that becomes a documented UX constraint, not a test failure — this judgment
  call is inherently manual, decided in advance by the existing threshold section rather than made
  after seeing the data.

## Exit criteria

Reiterating `prototype-plan.md`'s existing bar (not redefining it here): the baseline realistic
condition must clear PSR ≥ 6dB and recovered offset within ±2ms of Test 1's loopback ground truth.
Edge-condition failures are documented as UX constraints (e.g., "app enforces a minimum playback
volume"), not grounds to fail the test outright.

## Cross-device generalization of the Pixel 10 results

The Tier-2 numbers above (zero XRuns after the warmup fix, baseline capture RMS ~320-340, 48000 Hz /
96-frame bursts, streams granted `LowLatency`/`Exclusive`) are gathered on a *single* Pixel 10, and
should be read as a **favorable-case existence proof, not a population estimate**. The Pixel is close
to a best case for this approach — clean near-AOSP audio stack, well-behaved AAudio, good transducers,
and (likely) honest `InputPreset` handling. `prototype-plan.md`'s Test 2 "Cross-device generalization"
note carries the full analysis; the harness-specific points:

- **What generalizes** is the algorithm and the pass/fail *criteria* — they're device-independent,
  validated by the synthetic step 1 with no phone in the loop (the SNR→PSR mapping, ±1-sample accuracy,
  the 6dB PSR floor, and the PSR≥6dB / offset-within-±2ms bars). The ±2ms bar is measured against
  *that device's own* loopback ground truth, so it's self-relative and transfers even though the
  absolute latency does not.
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
- **Proposed future diagnostic (not built here): an AGC-linearity probe.** Play a fixed tone at two
  known gains (e.g. 0.3 and 0.9) and check whether captured RMS preserves the ~9.5dB ratio or
  compresses it; compression = AGC still active on that device = its SNR-mapping is compromised. Worth
  adding to the harness before trusting a *non-Pixel* sweep, since it isolates the single biggest
  cross-device wildcard rather than discovering it from confusing PSR data later.

## What this doesn't cover

Echo cancellation, onset detection, cross-device variance (second phone), and chain-of-forwarding
drift (Test 3) are all out of scope here, per `prototype-plan.md`'s existing scoping — this plan
covers only the capture-and-measure step for a single device.

## Next steps (Stage 2)

In rough dependency order, picking up from "Implementation status" above:

1. ~~**Wire NDK/CMake into `harness/build.gradle.kts`**~~ — done (see "Implementation status" above).
2. ~~**Implement the full-duplex native engine + JNI bridge**~~ — code written and build-verified (see
   "Implementation status" above); still needs on-device verification, which happens as part of the
   Tier 2 instrumented tests in item 4 (no device connected yet, so that gate is open).
3. ~~**Build the condition-sweep driver**~~ (Components §3) — **code written and build-verified**
   (`harness/src/androidTest/.../capture/ConditionSweepTest.kt` + a pure-Kotlin `conditionFromId()`
   lookup in `ConditionMatrix.kt`, Tier-1 tested). One `am instrument -e condition <id>` invocation
   drives one `CaptureEngine.runCapture(condition, outputDir)` cell into a persistent app-private
   external `getExternalFilesDir("sweep")` directory (never a wiped cache dir; it's `adb pull`-able —
   the one gotcha is that `gradlew connectedAndroidTest` uninstalls-and-wipes on completion, so run the
   real sweep via `am instrument`, per Components §4); XRun/ring-overflow/non-speaker
   route hard-fail as retry signals while a sub-floor RMS is recorded as an acceptable edge-cell
   finding, not a failure. Still needs the *manual* 36-cell on-device sweep to actually run (the
   per-cell physical positioning is the operator's job, per Components §3's positioning protocol) —
   that is Tier-3 work below, gated on the real reference track (item 5).
4. ~~**Write and run the Tier 2 instrumented tests**~~ — done and green on a real Pixel 10 (see
   "Implementation status" above), including the XRun diagnosis/fix that surfaced there.
5. **Replace the synthetic placeholder reference track** with a real clean, dry beatbox recording
   before any Tier 3 work.
6. **Tier 3 manual checkpoints and Components §4's data-pull/analysis integration** — the latter
   needs real captures to feed through the now-implemented Python GCC-PHAT (`analysis/`), so it's
   blocked on items 2–4 above, not on step 1.
