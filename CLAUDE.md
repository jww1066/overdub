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

## Diagnose before re-implementing

When an on-device test reports unexpected behavior, don't jump straight to a second implementation
attempt — check whether the *test itself* actually exercised the code path first. In one prior
project, an audio-focus "swirling" artifact survived two different duck implementations (framework
default, then a manual synchronized attenuation) before it turned out the test method — previewing
a ringtone/alarm from Android's Settings — doesn't request audio focus at all in most Android
versions, so neither implementation was ever actually invoked. The real fix was retesting with a
genuine notification/call. Ask what steps were used to reproduce before writing more code.

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
- LF→CRLF warnings on `git add`/`git commit` on Windows are harmless noise from line-ending
  normalization, not an error.
- Newer Android versions can break older Espresso versions: Android 16 (API 36) blocks the
  hidden-API reflection `InputManagerEventInjectionStrategy` relies on, so
  `espresso-core` below ~3.7.0 fails Compose-UI-driving instrumented tests (anything using
  `createComposeRule`/`createAndroidComposeRule` and `Espresso.onIdle`) with
  `NoSuchMethodException: android.hardware.input.InputManager.getInstance []`. If this resurfaces
  after an OS bump, bump `espresso-core` before assuming new tests themselves are broken.

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
