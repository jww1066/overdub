# On-device audio — implementation patterns

Companion to `CLAUDE.md`. The *behavioral/product* audio rules (no auto-resume, foreground service
required, single source of truth, focus duck-vs-pause) live in `CLAUDE.md`'s "Core audio behavior
rules". This file holds the *implementation-depth* engine/DSP recipes and the main-thread
scheduling detail. Read it when building or debugging the capture/playback engine.

## Main-thread discipline — contention vs. sequencing

`CLAUDE.md` covers the keep-on-thread / move-off-thread rule of thumb. Two deeper points:

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
- **Measure the true alignment between the two full-duplex streams with `getTimestamp()`, don't infer
  it only from signal correlation.** A full-duplex engine runs *two* hardware streams (output + input)
  that start independently and are not sample-synchronized, so any offset recovered purely by
  correlating the played reference against the captured mic carries a per-session start misalignment
  on top of the real acoustic round-trip. Both streams expose `AAudioStream_getTimestamp()` (Oboe:
  `getTimestamp()`) — a `(framePosition, nanoTime)` pair against a common monotonic clock, with output
  DAC latency and input ADC latency already folded in (it reports when a frame is actually
  *heard* / actually *captured*, not when you enqueued it). Reading both after the streams reach
  RUNNING gives the exact frame relationship between them, so you can subtract the harness's own
  start-offset and recover the pure round-trip — or use the timestamps directly as the alignment,
  independent of any acoustic bleed (this is the "trust the platform latency" path, `Test 1a`). Log
  the pair into capture metadata. Caveat: `getTimestamp()` accuracy is itself device-dependent (the
  moto g(20) reported a wrong number), so a physical loopback stays the independent check that the
  timestamps aren't lying — timestamps remove the *measurement* jitter, the loopback confirms the
  *platform* is honest. Ties to `doc/guides/offline-dsp.md`'s "run-to-run spread can be a measurement
  artifact" lesson.
- **Audio focus (implementation detail; the duck-vs-pause *decision* is in `CLAUDE.md`)**: ducking
  multiple simultaneous tracks via either the framework default or a manual synchronized attenuation
  can produce an audible "swirling"/artifact with several concurrent, decorrelated tracks — if that
  happens, pausing uniformly on any focus loss (same as a manual pause) is simpler and artifact-free,
  at the cost of the whole mix stopping rather than ducking for something brief like a notification
  chime.
