# CLAUDE.md

General-purpose guidance for Android audio development and testing in this repo, distilled from
a prior Android audio app project (noisedroid).

This file holds the always-on core rules. Deeper, situational detail lives in `doc/guides/` and is
listed under "Detailed guides" at the bottom — read the relevant guide when you start on that kind
of work (it is not auto-loaded).

## Real hardware is required for anything audio-related

The emulator does not reliably reproduce DAC latency, buffer underrun, or audio-focus behavior.
Any change touching playback, recording, focus, or routing needs verification on a physical
device via `adb`, not just an emulator or unit test pass.

## Testing methodology — three tiers

1. **JVM unit tests** (`gradlew test`) for pure-Kotlin logic with no Android framework dependency —
   DSP/math, gain curves, scheduling arithmetic, formatting. Fast, deterministic, run on every
   change. A seam between two pure-Kotlin units is already covered here (both sides are real
   objects on the JVM) — no separate tier needed.
2. **Instrumented component-integration tests** (`gradlew connectedDebugAndroidTest`, needs a
   connected device/emulator) for seams into real Android framework classes that can't be
   constructed on a plain JVM — e.g. a player class ↔ real `AudioTrack`/`VolumeShaper`, a service ↔
   real `NotificationManager`/`MediaSessionCompat`/`Handler`/`SystemClock`. Use the *real* framework
   objects, not Robolectric shadows or mocks — a test that fakes one side of a seam tests the fake,
   not the seam. These assert state-machine/wiring correctness (does `resume()` flip `isPlaying()`,
   does a `MediaController.pause()` reach the same code path as the in-app button), not audio
   quality or audibility.
3. **Manual on-device checkpoints** for what neither automated tier can honestly assert: actual
   audio quality/audibility, a *real* phone call or notification triggering focus loss (as opposed
   to calling the focus-change listener directly), real lockscreen UI, real screen-lock/backgrounding
   survival over time, overnight Doze/battery-management behavior.

Audio focus loss and `ACTION_AUDIO_BECOMING_NOISY` are private listeners triggered by real system
events — don't try to fake these in an automated test; it gives false confidence.

Three traps that make a green suite lie — **details and worked cases in
`doc/guides/testing-and-debugging.md`**: (a) a warmup-sensitive hard-fail metric (XRun count,
first-frame latency) can pass by luck of alphabetical test order — run it cold and in isolation;
(b) a green suite on one reference-grade device is a favorable-case existence proof, not a
population guarantee — split "the criteria generalize" from "this hardware clears them," and probe
whether the OEM honors the requested low-processing `InputPreset`; (c) when a sweep axis is defined
relative to a physical referent, record the *referent/geometry* in metadata, not just the axis value;
(d) **a pass/fail gate derived from an estimator's own output cannot catch failures that estimator's
assumptions cause — validate with an independent instrument.** A GCC-PHAT alignment "passed" PSR ≥ 6 dB
and a plausible-offset lag window for a whole 36-cell sweep; an independent matched-filter calibration
click then showed every offset was a ~187 ms beat-period *alias* of the true (negative) offset, with a
sharp, in-window, high-PSR peak. The estimator's own quality metric (PSR) and a plausibility window
built on a sign prior ("a round-trip is positive") both blessed the alias — the prior was wrong for the
measurement basis (the captured WAV's sample 0 precedes input-frame 0, so the true offset is negative).
Two general rules: **establish the measurement basis's sign before constraining a search to it**, and
**judge an estimator against an instrument that does not share its failure mode** (here, an aperiodic
chirp has no beat-period ambiguity, so it sees the alias the correlator can't). Worked case:
`doc/guides/offline-dsp.md` (GCC-PHAT lessons) and `doc/test2-sweep-results.md` "Calibration click
cross-check." (e) **a remedy's arithmetic only covers the failure class it models — a different class
with the same symptom escapes it, so measure the failure-class distribution before trusting the remedy.**
A median-of-5-`getTimestamp`-reads remedy was binomially justified for *single-read* glitches (Test 3's
knife-edge); a 43-capture multi-read batch then measured that ~half the real anomalies were a
*session-level desync* — the input clock offset ~+35 ms for the whole session, the audio itself
misaligned 78.67 ms, the median wrong too, and silent to XRun/dropped/route gates (only the independent
calibration click caught it). The median fixes the isolated-glitch class; it cannot fix the session-level
class. A self-consistency check (residuals from a model fit to the suspect's *own* readings) is no
substitute either: a *uniform* whole-session offset shift leaves each stream's frame-vs-time line
internally consistent (slope still the sample rate, residuals ~0), indistinguishable from a
correctly-offset session without an independent anchor — a direct corollary of (d). Two general rules:
**discriminate the failure classes before betting on a remedy** (arithmetic that's correct for one class
says nothing about another class with the same symptom), and **a detector built from the suspect's own
readings cannot see a failure that shifts all of them together — only an independent anchor can.** Worked
case: `doc/test2-sweep-results.md` "Multi-read timestamp batch."

## Diagnose before re-implementing

When an on-device test reports unexpected behavior, first check whether the *test itself* actually
exercised the code path before writing a second implementation — ask what steps were used to
reproduce. (A prior project's audio-focus "swirling" survived two duck rewrites because the repro —
previewing a ringtone from Settings — never requested audio focus at all.) And when a symptom could
come from either side of a seam, **log each side separately before attributing the cause** — a
full-duplex XRun turned out to be entirely input-side once output and input counts were logged as
two distinct numbers. Full war-stories: `doc/guides/testing-and-debugging.md`.

## Main-thread discipline

- **Keep on the main thread**: UI work (Compose measure/layout/draw, state updates that trigger
  recomposition); framework lifecycle callbacks (`Activity`/`Service` lifecycle methods,
  `BroadcastReceiver.onReceive`, `ServiceConnection` callbacks — these run on the main thread by
  default and mutating shared state from them doesn't need extra synchronization as long as nothing
  else touches that state off-thread); genuinely fast calls to system services (`getSystemService`,
  building a `Notification`, registering a receiver).
- **Move off the main thread**: anything CPU-bound that isn't trivially fast (parsing, DSP/FFT,
  crypto — `Dispatchers.Default`) and anything I/O-bound (disk, DataStore/SharedPreferences,
  database, network — `Dispatchers.IO`). Rule of thumb: if it could plausibly take more than one
  frame (~16ms) or block on a resource, it doesn't belong inline on the thread that also has to draw
  the next frame.
- **Contention vs. sequencing** (reordering your own calls only fixes *sequencing*, not a slow op
  monopolizing the Looper) and the `Service.onCreate()` fast-setup-then-offload-slow-work pattern:
  see `doc/guides/on-device-audio.md`.

## Core audio behavior rules

Product/behavioral contracts — treat a deviation as a deliberate design change, not an incidental
bug fix. Implementation recipes (native sample rate, `AudioTrack` modes, click-free ramps,
loudness/headroom, the full-duplex startup-XRun fix, focus-ducking artifacts) are in
`doc/guides/on-device-audio.md`.

- **No auto-resume**: pausing (via UI, MediaSession/lockscreen, or audio focus loss) must never
  auto-resume on its own — resuming is always an explicit user action, so playback never
  unexpectedly continues through the phone speaker or restarts silently.
- **Audio focus**: decide early whether focus loss (transient-duckable, transient, or permanent)
  should duck or pause. Pausing uniformly on any focus loss is simpler and artifact-free (ducking
  several decorrelated tracks can "swirl"); also handle `ACTION_AUDIO_BECOMING_NOISY` (headphones
  unplugged / Bluetooth disconnect) the same way.
- **Foreground service + MediaSession are required**, not optional, for background audio — Android
  kills background audio without a foreground service, and lockscreen/notification transport
  controls need a `MediaSession` to attach to.
- **Single source of truth for playback state**: keep channel volumes / play-pause / timers in the
  Service, not duplicated into a `ViewModel`/Activity. Mirror service state into UI and re-sync on
  both `onServiceConnected` *and* `onResume()` — the lockscreen/notification transport can change
  playback while the Activity is backgrounded, so an `onServiceConnected`-only sync misses it.

## Repo hygiene

- **Never commit audio files** (`.wav`, `.flac`, `.mp3`, `.aac`, `.ogg`, `.m4a`) to Git, including
  test/placeholder assets — they're gitignored. If a component needs a bundled audio asset (e.g.
  the Test 2 harness's reference track), check in a script that generates it locally instead of the
  binary itself, with a README noting it must be (re)generated after a fresh checkout.

## Shell & Gradle invocation (Windows / Git Bash)

- The working shell is Git Bash (POSIX), and the working directory **persists between commands**
  in a session — a `./gradlew: No such file or directory` almost always means "wrong cwd" (e.g.
  still in `analysis/` from an earlier command), not a missing wrapper. Check `pwd` before
  re-diagnosing.
- Run Gradle as `sh ./gradlew <tasks>` from the repo root. Do **not** reach for
  `cmd //c gradlew.bat`: cmd spawned from a compound Git Bash command doesn't reliably inherit
  the intended working directory and fails with a misleading `'gradlew.bat' is not recognized` —
  a second wrong-cwd error wearing a different costume. Reserve `cmd //c` for genuinely
  Windows-only tools; Gradle ships a POSIX wrapper.
- **After editing native (C/C++) code, clean-rebuild before installing the instrumented APK.**
  `:harness:assembleDebugAndroidTest` can report UP-TO-DATE and repackage a stale `.so` (the
  native build's outputs are not always wired as a packaging input), so `adb install -r` of the
  APK that comes out can carry the *pre-edit* native lib — the test runs green but exercises old
  code, and the sidecar silently lacks whatever field the new native code was supposed to log.
  Run `sh ./gradlew :harness:clean :harness:assembleDebug :harness:assembleDebugAndroidTest` (or
  `:harness:externalNativeBuildDebug --rerun-tasks` then re-assemble) before trusting an on-device
  run after a `.cpp`/`.h` edit. This is the same stale-APK class that bit item 9 (a stale test APK
  whose sidecar lacked `reflector_geometry`); the native-lib path is its sibling — and like that
  one, the failure is *silent* (a green test + a missing sidecar field), so only a clean rebuild
  or an explicit sidecar-field check catches it.

## Workflow for staged/incremental work

1. Implement the change.
2. Run unit tests, then build (`gradlew test assembleDebug` or equivalent) — must pass before going
   further.
3. Install to a connected physical device (`adb install -r ...apk`) and exercise the on-device
   checkpoint relevant to the change.
4. Don't commit until the on-device checkpoint (if audio/UI-affecting) is explicitly confirmed —
   report what changed and what to check, then wait.
5. If a bug/artifact is reported back, verify on real hardware again after the fix before assuming
   it's resolved (see "Diagnose before re-implementing").

## Detailed guides (read on demand — not auto-loaded)

- **`doc/guides/testing-and-debugging.md`** — when writing/auditing tests or debugging an on-device
  symptom: warmup-sensitive hard-fails, favorable-case-vs-population + `InputPreset` AGC probe,
  sweep-axis referent metadata, the full diagnose-before-reimplementing cases, instrumented-test
  isolation for persisted storage.
- **`doc/guides/on-device-audio.md`** — when building/debugging the capture or playback engine:
  main-thread contention-vs-sequencing detail, and the audio pipeline implementation patterns
  (native rate, `AudioTrack` modes, `VolumeShaper` ramps, loudness/headroom, full-duplex XRun fix,
  and measuring true two-stream alignment with `getTimestamp()`).
- **`doc/guides/offline-dsp.md`** — when working in `analysis/`: the venv, ASCII-only output,
  reusable-scripts (no `python -c` / scratchpad temp files), validate-DSP-params-empirically, the
  negative-slice gotcha, and the GCC-PHAT lessons — band-limit / lag-window / PSR-doesn't-validate-
  offset, PSR-is-a-fragile-band-sensitive-label-while-offset-is-band-robust (don't re-tune the band
  to chase one cell), the two-opposite-spectral-causes (HF rolloff vs HF rattle), and
  offset-spread-can-be-a-measurement-artifact (decompose with timestamps before blaming the
  estimator).
- **`doc/guides/tooling-and-hygiene.md`** — when a Gradle/adb/git/instrumented-test command fails
  with a message that doesn't name the real cause (`--tests`, `MSYS_NO_PATHCONV`, XML-comment `--`,
  `RECORD_AUDIO` grant rule, Espresso vs API 36).
