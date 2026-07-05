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
- **Test 2 step 1 (Python GCC-PHAT).** `analysis/src/overdub_analysis/__init__.py` is currently
  empty. The synthetic validation gate ("is the code correct before using it to map anything") needs
  to pass before running it against real captures means anything. Build it in parallel; don't block
  harness work on it.

Net effect: everything in this doc up through "capture files exist on disk with correct
metadata" can proceed today. Only the final pass/fail judgment against real data waits on the two
items above.

## Components to build

### 1. Reference track asset

A short (10-20s), clean, dry beatbox recording, bundled as a raw PCM WAV asset at the device's
native output sample rate (queried via `AudioManager.PROPERTY_OUTPUT_SAMPLE_RATE`, per `CLAUDE.md`'s
audio pipeline guidance — don't hardcode 44.1/48kHz). Reuse whatever rate Test 1 confirms as the
device's native rate, so ground-truth and real-bleed data aren't confounded by a resampling
mismatch between tests.

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

### 4. Data pull + analysis integration

- `adb pull` the WAV+JSON pairs off-device to a working directory under `analysis/`.
- Once Test 2 step 1 lands, feed each file through the validated GCC-PHAT implementation, recording
  PSR and recovered offset per condition into a results table alongside each file's metadata.

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

## What this doesn't cover

Echo cancellation, onset detection, cross-device variance (second phone), and chain-of-forwarding
drift (Test 3) are all out of scope here, per `prototype-plan.md`'s existing scoping — this plan
covers only the capture-and-measure step for a single device.
