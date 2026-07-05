# CLAUDE.md

General-purpose guidance for Android audio development and testing in this repo, distilled from
a prior Android audio app project (noisedroid).

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
events — don't try to fake these in an automated test; it gives false confidence (see "Diagnose
before re-implementing" below for a concrete case where this bit a prior project).

**A hard-fail metric that depends on warmup state can pass by luck of test order.** A zero-XRun
hard-fail assertion passed in the full instrumented suite only because it ran last (alphabetically),
after seven prior captures had warmed the audio path — run cold in isolation it failed with input
underruns every time. A green suite is not evidence the assertion is robust if the quantity it
checks (XRun count, first-frame latency, cold-cache timing) is sensitive to how warm the device is.
For anything warmup-sensitive, run the specific test *cold and in isolation* (single-method
`-Pandroid.testInstrumentationRunnerArguments.class=Class#method`, repeated several times) before
trusting the pass — don't let ordering hide a startup defect that a real cold-start run in the field
will hit.

**A green instrumented suite on one device is a favorable-case existence proof, not a population
guarantee.** Low-latency capture numbers (XRun-free, bleed SNR/RMS, whether LowLatency/Exclusive is
granted, native rate/burst size) are gathered on whatever phone is on the desk, and a reference-grade
device (a Pixel, clean near-AOSP audio stack) is close to a *best case* — generalizing its numbers
downward to budget or heavy-OEM-skin hardware should be expected to get worse, not better. Split what
you claim: the algorithm and the pass/fail *criteria* generalize (device-independent, ideally
validated with a no-device synthetic gate); whether real hardware clears them does not. The single
biggest cross-device wildcard for a capture path is whether the OEM actually honors the requested
low-processing `InputPreset` (e.g. `VoiceRecognition`) — residual AGC/NS silently auto-compensates
level and flattens any SNR gradient you're trying to measure. It's directly detectable (play a fixed
tone at two known gains, check whether captured RMS preserves the gain ratio or compresses it) and
worth probing before trusting a sweep on a new device. Log `device_model`/`sample_rate`/`input_preset`/
`xrun` into each capture's metadata so re-measuring on another device is "run it again, compare
tables," not a rewrite.

## Diagnose before re-implementing

When an on-device test reports unexpected behavior, don't jump straight to a second implementation
attempt — check whether the *test itself* actually exercised the code path first. In one prior
project, an audio-focus "swirling" artifact survived two different duck implementations (framework
default, then a manual synchronized attenuation) before it turned out the test method — previewing
a ringtone/alarm from Android's Settings — doesn't request audio focus at all in most Android
versions, so neither implementation was ever actually invoked. The real fix was retesting with a
genuine notification/call. Ask what steps were used to reproduce before writing more code.

A corollary for symptoms that could come from either side of a seam: **log each side separately
before attributing the cause.** A full-duplex capture reported non-zero XRuns, and the instinct is
to reach for the output stream (the usual underrun suspect). Logging the output and input XRun counts
as two distinct numbers showed output was always 0 and the entire problem was on the input side —
which pointed straight at the input warmup/startup ordering (see "Audio pipeline patterns") instead
of at a wrong-but-plausible output-buffer fix. Cheap instrumentation that disambiguates *which*
component failed beats guessing from a single aggregated number.

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
- **Contention vs. sequencing**: two independently-scheduled async operations sharing one Looper
  (e.g. a bound `Service`'s `onCreate()` arriving via a Binder-callback `Handler` message, and
  Compose's Choreographer-driven first frame) don't have a deterministic order just because your own
  code calls one before the other. Reordering your calling code only helps if the problem is
  *sequencing* (things happening in the wrong order); if it's *contention* (something slow
  monopolizing the thread once it starts running), reordering doesn't touch the root cause — move
  the slow work off-thread instead.
- If audio buffer synthesis or decoding happens in a `Service.onCreate()` that shares a process with
  the UI `Activity`, do the fast setup (notification, `MediaSession`, `startForeground()`)
  synchronously first, then kick off the slow work on `Dispatchers.Default` and install the result
  back on `Dispatchers.Main` once ready. Make sure every method that touches the not-yet-ready state
  tolerates an empty/missing value via safe calls, so a call that arrives before setup finishes is a
  no-op rather than a crash.

## Instrumented test isolation for persisted storage

Self-instrumented tests (the common Android setup) run inside the same app process/package as a
manually installed debug build, sharing its real on-device data directory. A test that writes
against the same DataStore/SharedPreferences file the real app uses can silently corrupt or wipe
real user data installed on the same device the moment `connectedDebugAndroidTest` runs. Any test
touching persisted storage (DataStore, SharedPreferences, files under `filesDir`, a database, etc.)
must redirect it to an isolated name/path first — e.g. a settable `companion object` var
(null/production by default, overridden by the test before the real class's `onCreate()` runs).
Don't assume "instrumented" implies "sandboxed" — it doesn't.

**Gotcha inside that pattern**: a Compose test rule that launches the real Activity as part of the
`@Rule` itself (e.g. `createAndroidComposeRule<MainActivity>()`) does so *before* that test class's
own `@Before` methods run — setting the override in `@Before` is too late, since the Activity (and
any Service it starts/binds) is already created by then. Use a JUnit `@BeforeClass`
(`companion object` + `@JvmStatic @BeforeClass fun ...()`) instead, which runs before any `@Rule` is
even constructed. A test that starts a service manually inside its own `@Before` doesn't need this —
only a test whose `@Rule` launches the Activity does.

## Audio pipeline patterns

- **Query the device's native sample rate** at startup (`AudioManager.PROPERTY_OUTPUT_SAMPLE_RATE`)
  rather than hardcoding one — avoids HAL resampling overhead.
- **`AudioTrack` mode**: `MODE_STATIC` for precomputed/looping buffers is viable even at sizes larger
  than its traditional short-clip use case, but confirm reliability on real target hardware, not
  just in principle — `MODE_STREAM` (app feeds the buffer via a write-ahead loop) is the fallback if
  a device/format combination proves otherwise.
- **Click-free start/stop**: starting/stopping a track mid-waveform can produce an audible pop.
  Prefer a short gain ramp via `AudioTrack.setVolumeShaper()` (`VolumeShaper`, API 26+) over an
  instant `play()`/`stop()` or a manually-timed `setVolume()` sequence — the framework interpolates
  the ramp on the audio render thread, avoiding main-thread timer jitter. Multiple simultaneous
  shapers on one `AudioTrack` (e.g. a UI fade and a separate scheduled fade-out) multiply rather than
  conflict, so they can coexist.
- **Loudness/headroom**: normalize synthesized/decoded buffers to a common RMS target with headroom
  reserved for the crest factor of the material (broadband noise needs more headroom than a sine),
  rather than relying solely on a per-channel gain cap to prevent clipping. If multiple decorrelated
  channels are mixed by the OS/HAL (one `AudioTrack` per channel rather than app-side summing),
  remember they sum in *power*, not amplitude — e.g. four uncorrelated channels each attenuated by
  -6dB sum to roughly the same RMS as one unattenuated channel. AudioFlinger's mixer applies no
  limiter of its own, so headroom must be conservative enough to absorb statistical peaks with
  several channels active at once.
- **Full-duplex Oboe startup XRuns are an input-side warmup artifact, not steady-state.** When one
  output data callback also drives capture (the recommended full-duplex pattern — the callback reads
  the input stream synchronously each call), a cold start reliably overran the *input* stream on a
  Pixel 10 while the output side stayed clean. Two independent causes, both at startup: (a) the input
  stream was started *before* its only drainer — the output callback — was live, so it backed up and
  overran in the gap; (b) the callback drained just one burst per call, never catching up on a
  backlog. Fixes that made cold XRuns deterministically zero: **start the output stream first** (so
  the drainer is running before input data arrives; gate the callback's input reads behind an atomic
  "input started" flag so it never touches a not-yet-started stream), **drain *all* available input
  each callback** (loop `read(..., timeout=0)` until it returns short, not a single burst-sized
  read), and **enlarge the buffers** — AAudio `LowLatency` opens the buffer at a single burst (lowest
  latency, most underrun-prone), so `setBufferSizeInFrames()` to several bursts on the output and max
  out the input buffer when capture latency doesn't matter (GCC-PHAT recovers the offset by
  correlation regardless of how deep the input is buffered). The looped drain and flag check stay
  callback-safe: bounded by available data, allocation-free, no locking.
- **Audio focus**: decide early whether focus loss (transient-duckable, transient, or permanent)
  should duck or pause. Ducking multiple simultaneous tracks via either the framework default or a
  manual synchronized attenuation can produce an audible "swirling"/artifact with several
  concurrent, decorrelated tracks — if that happens, pausing uniformly on any focus loss (same as a
  manual pause) is simpler and artifact-free, at the cost of the whole mix stopping rather than
  ducking for something brief like a notification chime. Also handle
  `ACTION_AUDIO_BECOMING_NOISY` (headphones unplugged / Bluetooth disconnect) the same way.
- **No auto-resume**: pausing (via UI, MediaSession/lockscreen, or audio focus loss) should not
  auto-resume on its own — resuming should always be an explicit user action, so playback never
  unexpectedly continues through the phone speaker or restarts silently. Treat any deviation from
  this as a deliberate design change, not an incidental bug fix.
- **Foreground service + MediaSession are required**, not optional, for background audio — Android
  will kill background audio playback without a foreground service, and lockscreen/notification
  transport controls need a `MediaSession` to attach to.
- **Single source of truth for playback state**: keep channel volumes / play-pause / timers etc. in
  the Service, not duplicated into a `ViewModel` or the Activity. Have the Activity mirror service
  state into UI state and re-sync on both `onServiceConnected` *and* `onResume()` — the latter
  matters because the lockscreen/notification transport can change playback while the Activity is
  backgrounded, so an `onServiceConnected`-only sync misses changes that happened while foregrounded
  after a background round-trip.

## Gradle/adb quirks worth knowing

- `gradlew.bat test --tests <Class>` can fail with "Unknown command-line option '--tests'" on some
  project Gradle setups — if so, just run the full `gradlew.bat test` rather than fighting the flag.
- Git Bash mangles absolute Unix-style paths in `adb shell` commands (e.g. `/sdcard/foo` gets
  rewritten to a Windows path). Prefix with `MSYS_NO_PATHCONV=1` when passing device-side paths to
  `adb shell`.
- A double hyphen (`--`) is illegal *inside* an XML comment — an `AndroidManifest.xml` comment
  written with a prose "em-dash" (`foo -- bar`) fails the manifest merger with an opaque
  `ManifestMerger2$MergeFailureException: Error parsing AndroidManifest.xml`, not a message naming
  the `--`. Use a single hyphen, "to", or reword. (Kotlin/C++/Markdown `--` is fine; this is XML-only.)
- Instrumented tests need runtime-permission grants set up in the test, not just declared in the
  manifest: `@get:Rule val p = GrantPermissionRule.grant(Manifest.permission.RECORD_AUDIO)` (from
  `androidx.test:rules`) — a `<uses-permission>` for a dangerous permission (RECORD_AUDIO) is not
  auto-granted to a headless instrumented run, and the capture silently returns silence/fails without it.
- LF→CRLF warnings on `git add`/`git commit` on Windows are harmless noise from line-ending
  normalization, not an error.
- Newer Android versions can break older Espresso versions: Android 16 (API 36) blocks the
  hidden-API reflection `InputManagerEventInjectionStrategy` relies on, so
  `espresso-core` below ~3.7.0 fails Compose-UI-driving instrumented tests (anything using
  `createComposeRule`/`createAndroidComposeRule` and `Espresso.onIdle`) with
  `NoSuchMethodException: android.hardware.input.InputManager.getInstance []`. If this resurfaces
  after an OS bump, bump `espresso-core` before assuming new tests themselves are broken.

## Repo hygiene

- **Never commit audio files** (`.wav`, `.flac`, `.mp3`, `.aac`, `.ogg`, `.m4a`) to Git, including
  test/placeholder assets — they're gitignored. If a component needs a bundled audio asset (e.g.
  the Test 2 harness's reference track), check in a script that generates it locally instead of the
  binary itself, with a README noting it must be (re)generated after a fresh checkout.

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
  `git add` warnings noted above.
- **Write reusable scripts, not one-off `python -c` snippets.** Anything worth computing once (an
  SNR sweep, a metric over a capture set) belongs in `analysis/scripts/` as a real file with
  argparse and a docstring, so it's re-runnable as the code or data changes and can be checked in.
  A `python -c "..."` that prints a finding evaporates with the shell session and has to be
  rewritten from scratch next time. The `sweep_snr_floor.py` script is the template. This applies
  even to a quick ad-hoc edge-case check mid-task (e.g. spot-checking a function's behavior while
  reviewing code) — the impulse to verify a hunch inline is exactly the case this rule targets, not
  just deliberate analysis work.
- **Validate a DSP-parameter concern empirically before changing it, not by guessing.** When a
  default (e.g. a PSR exclusion window, a filter cutoff) is suspected to be miscalibrated against
  the actual signal shape, write a small diagnostic script that measures the real quantity (e.g.
  `measure_main_lobe_width.py` printing correlation magnitude around the peak) rather than
  reasoning about it in the abstract or "fixing" it speculatively — the measurement can just as
  easily show the original default was fine. Same spirit as "Diagnose before re-implementing" above,
  applied to offline DSP analysis instead of on-device audio behavior.
- **Python negative-slice gotcha:** a slice bound computed as `len - k` silently changes meaning if
  it goes negative — `out[: n - k]` is `out[:5]` when `n - k == 5`, but becomes `out[:-3]` (a large
  *positive*-length slice from the start, not an empty one) when `n - k == -3`. This bit
  `synth.py`'s `delay()`: for `abs(d) >= len(signal)` the computed bound went negative and the slice
  silently selected the wrong range instead of being empty, surfacing as a confusing
  `numpy` broadcast-shape `ValueError` rather than a clear error or correct result. When a slice
  bound is arithmetic (not a literal), explicitly guard the case where it could go negative rather
  than trusting Python's negative-index reinterpretation to do the right thing.

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
