# Testing & debugging — detailed guidance

Companion to `CLAUDE.md`'s "Testing methodology — three tiers" and "Diagnose before
re-implementing" sections. Read this when writing/auditing tests, judging whether a green suite
actually proves what it claims, designing a condition sweep, or debugging an on-device symptom.

## When a green suite doesn't prove what it looks like it proves

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

This same "single favorable case over-generalized" trap recurs in offline analysis: a fix that
looked "validated" on one mid-range sweep cell (band-limited GCC-PHAT, "+97 ms") only held up
*directionally* when re-run across the full 36-cell population, which exposed a physically-impossible
outlier the single cell had hidden. Run the population before recording a single-cell result as a
durable "validated" lesson. See `doc/guides/offline-dsp.md`.

## Condition-sweep metadata

**When a sweep axis is defined relative to a physical referent, pin AND record the referent in
metadata — not just the axis values.** A condition matrix varied `distance_cm` (15/50/200 cm)
defined as "distance to the nearest large reflecting surface," but the first six cells were
captured with a desk-below-as-reflector geometry that collapses the distance and orientation
axes (the desk is both the distance referent *and* the face-down resting surface) and can't
extend to `far` (2 m above a desk isn't feasible indoors). The metadata recorded `distance_cm=15`
faithfully but not *which surface* the 15 cm was measured to, so the bad geometry was
indistinguishable from a valid cell and would have silently contaminated the dataset — caught
only because the operator asked a clarifying question, not because the data was self-flagging.
The redo used a wall as the reflector with a separate small pad as the face-down coupler (two
distinct objects, keeping the axes independent). Record the physical-setup referent/geometry
into metadata (a `reflector_geometry`/`setup_notes` field), same rigor as
`device_model`/`input_preset` — the axis values alone are ambiguous without it, and "the
nearest large reflecting surface" is a phrase that needs a name attached before it means
something reproducible.

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
which pointed straight at the input warmup/startup ordering (see `doc/guides/on-device-audio.md`,
"Audio pipeline patterns") instead of at a wrong-but-plausible output-buffer fix. Cheap
instrumentation that disambiguates *which* component failed beats guessing from a single aggregated
number.

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
