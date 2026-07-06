# Overdub App — Prototype Validation Plan

## Purpose

Not a product prototype. Two narrow tests targeting the two assumptions the entire architecture depends on. If either fails, the "accept mic bleed, no calibration, no USB-C requirement" design direction needs to be reconsidered before any further engineering — UI, sharing flow, echo cancellation, lead-in UX are all downstream of these two questions and out of scope here.

## Why these two, and not the others

The design doc lists several open items: pre-roll buffer sizing, `AcousticEchoCanceler` quality, onset detection reliability, USB Audio Class consistency. All of these are either explicitly deferred already or are optimizations layered on top of alignment working at all. Two items are load-bearing:

1. **Continuous-buffer latency stability** — the doc flags that lead-in and overdub target must be one continuous audio stream, not two sequentially-scheduled players, or "a scheduling seam would silently invalidate the measured offset." Unverified on real devices.
2. **Cross-correlation alignment under real bleed conditions** — GCC-PHAT (Knapp & Carter, *IEEE Trans. Acoustics, Speech, and Signal Processing*, 1976) is peer-reviewed and well-established as a time-delay-estimation method in principle. What's unverified is whether it locks onto a clean peak given actual phone-speaker-to-phone-mic bleed SNR, not whether the math is sound.

If (1) fails, your measured latency offset is meaningless regardless of alignment method. If (2) fails, the no-calibration bleed-based approach doesn't hold and you're back to reconsidering USB-C or an explicit calibration step. Everything else in the design doc is contingent on these two holding up.

**Addendum (2026-07-05):** a documentation review surfaced a gap neither test above covers —
headphone monitoring breaks the bleed mechanism entirely, since it removes the acoustic path Test 2
depends on (see design-summary.md's "Headphone monitoring gap and alignment alternatives"). Test 1a
below adds a third, cheap validation for the most promising fix: trusting AAudio/Oboe's own reported
latency instead of requiring bleed at all. It's the first of the three to run — it reuses Test 1's
rig rather than needing new device-routing machinery, and if it holds up, it removes the
bleed-dependency question for headphone sessions rather than working around it.

The same review surfaced a second, independent gap: neither test addresses whether per-hop alignment
error compounds across a multi-hop forwarding chain (see design-summary.md's "Chain-of-forwarding
alignment error"). Test 3 (proposed) below is a synthetic Monte Carlo extension of Test 2's Python
harness to check this, once real per-hop error data exists to drive it.

## Skills research (informs scope, not method)

Checked whether any existing Claude Code skill covers this work before planning to hand-roll it. Searched three angles: general Android development skills, Android-specific audio/latency skills, and DSP/signal-processing skills.

- **General Android skills** (`android/skills` — Google's official repo, ~4,500 stars, announced April 2026; `rcosteira79/android-skills`; `chrisbanes/skills`; `dpconde/claude-android-skill`) — cover architecture, Compose, Room, Hilt, testing/debugging. Not audio-specific. Irrelevant to this plan.
- **Audio-specific skills found** — a "sound engineer" skill (spatial audio, HRTF, Wwise/FMOD, game audio middleware) explicitly excludes music production and is scoped to game audio, not relevant. Several "Audio Engineering Patterns" / "Audio Expert" / "Music Analysis" skills cover mixing, mastering, LUFS, EQ, TTS pipelines, tempo/key extraction — none mention cross-correlation, GCC-PHAT, or adaptive filtering.
- **DSP/signal-processing skills** — one closer-in-spirit candidate, a GNU Radio / SDR skill, covers correlation-adjacent signal processing but is scoped to RF hardware (RTL-SDR, HackRF), not audio streams. Low confidence this would transfer usefully — noting as an unverified guess, not a recommendation.
- **Conclusion**: no packaged skill — official or community — covers Android low-latency audio capture tuning combined with acoustic signal alignment. Both tests below are built directly against primary sources (Oboe/AAudio docs, Knapp & Carter 1976) rather than any third-party skill, since none exists that fits.

## Quantitative thresholds — how these were derived (added 2026-07-05)

Documentation review flagged that Test 1 and Test 2 had no numeric pass/fail bar, just qualitative
descriptions ("confirm stable," "map out where it degrades") — which invites judging "pass" after
seeing the data rather than before. Thresholds below are derived, not picked to fit expected
results:

1. **Top-level audible-drift ceiling: 15ms.** Psychoacoustic literature on onset-asynchrony
   perception puts simultaneity judgments for percussive material in the ~10–30ms range; 15ms is a
   conservative pick toward the tight end since this app's material (beatboxing, rap) is
   rhythm-critical, not ambient. This is a generic-perception number, not validated for this app's
   specific bleed/hardware conditions — see caveat at the end of this section.
2. **The ceiling is a budget, split across stages**, so no single error source is allowed to
   consume the whole allowance before other sources even contribute:

   | Stage | Allowance | Rationale |
   |---|---|---|
   | Test 1 — buffer-stability variance | ±3ms | Foundational/systematic error that every downstream stage inherits; kept small since it should be near-zero if the continuous-stream assumption holds. |
   | Test 1a — AAudio self-reported vs. ground-truth latency | ≤5ms discrepancy | Needs enough margin that trusting the platform number alone doesn't already consume a third of the budget. |
   | Test 2 — correlation peak quality | PSR ≥ 6dB (minimum acceptable), ≥10dB (confident) | Borrowed from established TDOA/GCC-PHAT practice for "is this peak trustworthy," not invented from this dataset. |
   | Test 3 — cumulative multi-hop drift | 95th-percentile cumulative offset ≤15ms at N=4 hops | Uses the same top-level ceiling as the final acceptance bar once independent per-hop errors compound. |

3. **Caveat:** these numbers are literature-grounded and defensible as genuinely decided in
   advance, but they weren't validated against phone-speaker-to-phone-mic bleed specifically. If
   Test 2 step 1 (synthetic, no device involved) shows the algorithm structurally cannot reach the
   PSR floor even at high SNR, that's an *achievability* finding, not grounds to quietly lower the
   *acceptability* bar — it would mean reconsidering the design direction, per this doc's stated
   purpose, not relaxing the threshold post-hoc.

## Test 1 — Latency harness (continuous-buffer stability)

**Question:** Does a single continuous audio buffer (lead-in + overdub target) preserve a stable, correctly-measured round-trip offset, or does a scheduling seam introduce silent error?

**Setup:** One Android device (any available — the goal is validating your implementation's behavior, not benchmarking a specific device against a published spec number, since no authoritative Pixel 10 latency figure exists anyway). Build the continuous-buffer capture/playback path using Oboe with `PerformanceMode::LowLatency` and `SharingMode::Exclusive` (per `developer.android.com/games/sdk/oboe/low-latency-audio`).

**Hardware status (2026-07-05):** loopback rig ordered — a PassMark Audio Loopback Plug (TRRS)
plus a Movo UCMA-2 USB-C-to-TRRS adapter, needed since the target device (Pixel 10) has no 3.5mm
jack. This is a fully electrical loopback path (phone USB-C → UCMA-2 → PassMark plug), so no
physical clap/acoustic signal is needed for this test — OboeTester generates and reads back its own
test signal over the wired connection. Test 2's acoustic bleed test is unaffected by this and still
uses the phone's built-in speaker/mic directly.

**Method:** Loopback test — physical clap or a known click track through a loopback cable — repeated ~20 times. Check `AAudioStream_getXRunCount()` for buffer underruns on each run. Confirm the measured offset is stable across repetitions and doesn't drift when the lead-in and target recording are scheduled as one continuous stream vs. (as a negative control) two sequentially-scheduled players.

**What this answers:** Direct yes/no on whether the "no scheduling seam" assumption holds. Doesn't require musical content or a second device.

**Pass/fail threshold:** Measured offset variance across the 20 reps must stay within **±3ms**
(e.g. ~144 samples at 48kHz — actual sample count depends on the device's native rate) for the
continuous-stream condition. **Any buffer underrun (`AAudioStream_getXRunCount()` > 0) is a hard
fail** regardless of measured variance, since an underrun invalidates the continuous-stream
assumption outright. The negative-control (two sequentially-scheduled players) is expected to fail
this bar — if it doesn't, that's a signal the test rig isn't sensitive enough to detect a scheduling
seam, not that seams are harmless.

**Confidence:** High confidence this test design is correct — it mirrors Google's own recommended latency-measurement approach (OboeTester, per AOSP's audio latency documentation). Low confidence in what the result will be — the design doc already flags real A/V sync bugs (200–700ms) reported by Pixel 8/9 users as a different-but-adjacent failure mode, which is a signal, not a prediction.

## Test 1a — AAudio self-reported latency accuracy (headphone-safe alignment path)

**Priority: run this first.** Cheapest of the three to validate, and if it passes it removes the
entire bleed-dependency question for headphone-wearing users rather than requiring a workaround.

**Question:** Does AAudio/Oboe's own reported stream latency (timestamps against the shared audio
clock) match the ground-truth round-trip latency measured by the physical loopback, closely enough
to use directly as the alignment offset — with no dependence on any acoustic bleed signal?

**Setup:** The same loopback rig as Test 1 (physical clap/click track through a loopback cable) — no
new hardware. Log `AAudioStream_getTimestamp()` (or Oboe's equivalent) alongside the
ground-truth offset already being measured for Test 1, across whatever output routes are available
(built-in speaker, wired headset, Bluetooth if on hand).

**Method:** For each of the ~20 repetitions Test 1 already runs, record both numbers side by side —
the loopback-measured ground truth and AAudio's self-reported latency. Compare across routes: does
the discrepancy (if any) stay consistent, or does it change meaningfully between speaker and
headphone output? Repeat on a second device if available, since the design doc's one documented
counter-example (moto g(20)) was device-specific, not universal.

**What this answers:** Whether trusting platform-reported latency is viable as the primary
mechanism (making Test 2's bleed correlation unnecessary for headphone sessions), or only viable as
a rough estimate needing bleed-based correction on top, or not viable at all (falling back to the
forced-speaker calibration chirp or adaptive hybrid from design-summary.md's alternatives list).

**Pass/fail threshold:** Discrepancy between AAudio's self-reported latency and the loopback
ground truth must stay **≤5ms**, consistently across all ~20 reps and across every route tested
(speaker, wired, Bluetooth if available). A route that exceeds 5ms falls back to bleed-correlation
(Test 2) or the forced-chirp alternative for that route specifically — this doesn't need to be an
all-routes-or-nothing decision; e.g. platform timestamps could pass for wired headsets but fail for
Bluetooth, and the app could use different mechanisms per route.

**Confidence:** Low confidence either way — the design doc's rejection of this approach rested on a
single anecdotal report, not a systematic test, so this is a genuinely open question rather than one
with a directional prior.

## Test 2 — Single-device bleed + offline alignment

**Question:** Does GCC-PHAT recover a clean, usable alignment peak from real phone-speaker-to-phone-mic bleed, or does real-world SNR fall below what the algorithm needs?

**Setup correction (single device, not two):** The actual bleed mechanism in the design is one phone playing back the beatbox track through its own speaker while simultaneously recording the overdub through its own mic — playback and capture on the *same* device. One phone is sufficient and correctly reproduces the mechanism being tested. A second phone would only be useful later, for checking cross-device variance in speaker/mic hardware and AGC behavior — a real but lower-priority question, not what this test is scoped to answer.

**Recommended sequencing** (given Windows 11 is available for the analysis half):

1. **Synthetic validation first, on Windows.** Inject known delays and controlled noise levels into a clean signal using Python (`scipy.signal.correlate` plus an FFT-based phase transform for the GCC-PHAT weighting). Confirm the implementation recovers the correct offset and map out the theoretical SNR floor where it starts to fail. This is pure software — no phone needed — and isolates "is the code correct" from "does the physical setup work."
2. **Real-bleed recording, one phone.** Record the clean beatbox track, then have the same phone play it back through its speaker while recording the overdub through its mic. Vary playback volume and phone orientation/distance from any obstruction to map where the correlation peak degrades. Run the validated GCC-PHAT implementation from step 1 against this real data.

**Implementation status (2026-07-05):** step 1's Python GCC-PHAT is implemented and its
synthetic-validation gate passes (`analysis/src/overdub_analysis/gcc_phat.py` +
`synth.py`, 14 pytest cases green). At high/clean SNR (30 dB ≥ the 20 dB bar) the recovered
offset is within ±1 sample of the injected delay and PSR ≥10 dB; the 6 dB PSR floor for a
broadband periodic click train sits at ≈ −30 dB SNR (run
`analysis/scripts/sweep_snr_floor.py` to reproduce) — far below any realistic phone-bleed SNR,
a strong positive finding for this signal class. The synthetic fixtures double as the
port-correctness regression tests the 093038 review asked for when the algorithm is later
ported to Kotlin/C++. Step 2's Android capture harness now has its Gradle scaffold, pure-Kotlin
pieces, the Oboe full-duplex native capture engine (Tier-2 green on a real Pixel 10 as of
2026-07-05 — zero XRuns after an input-warmup fix), and the condition-sweep driver all built
(Stages 1–2 of `test2-step2-plan.md`). **Update — step 2 has now run against real bleed
(2026-07-05):** the manual 36-cell on-device sweep is complete (36/36 clean on the Pixel 10; see
`doc/test2-sweep-results.md` for the full matrix and findings), the real `boots.wav` reference
(48kHz/15.25s) is bundled, and the captures are pulled and fed through the Python GCC-PHAT.
**Full-band GCC-PHAT fails on the real bleed: 0/36 clear the >=6 dB PSR bar** (PSR 0.6-5.8 dB,
unphysical negative offsets). Diagnosed empirically (`analysis/scripts/diagnose_gcc_phat.py`):
the reference is fine (autocorrelation PSR 38-67 dB — cause (a), reference periodicity, ruled
out); the failure is PHAT over-weighting noise-dominated HF and bass-rolled-off LF bands (the
phone speaker rolls off the bass; HF bands are mic-noise, not signal). **A band-limited PHAT
(500-4000 Hz) recovers the correlation peak broadly** — a full-matrix re-run
(`run_bandlimited_gcc_phat_sweep.py`) went from 0/36 to 35/36 clearing the 6 dB bar (29 at
>=10 dB). **But the recovered offset is not yet trustworthy**: offsets span +61 to +151 ms (not
the "consistent +97 ms" the single baseline cell suggested), and one cell scored PSR 11.6 dB
"confident" on a physically impossible -15.25 s wraparound alias — so PSR alone does not validate
alignment. Constraining the lag search to a plausible window and recalibrating the PSR
exclusion-window are the remaining steps before this is a real pass (see `test2-step2-plan.md`
"Next steps" items 7a-7c); the ±2 ms-vs-ground-truth half of the bar also still waits on Test 1's
loopback number. Results remain Pixel-10-specific (see "Cross-device generalization" below).

**What this answers:** Whether the "no calibration step needed" claim in the design doc — which currently rests on GCC-PHAT being appropriate in principle — holds up against actual phone-mic-quality bleed. A failure at step 2 (after step 1 passes) tells you the acoustic environment doesn't have enough SNR, not that the algorithm is wrong.

**Pass/fail threshold:**
- **Step 1 (synthetic, implementation-correctness gate):** at high/clean SNR (e.g. ≥20dB), recovered
  offset must match the injected delay within **±1 sample** and peak-to-sidelobe ratio (PSR) must be
  **≥10dB** — this confirms the code is correct before using it to map anything. Sweep noise level
  downward and record the SNR at which PSR crosses below **6dB** (the minimum-acceptable floor,
  borrowed from standard TDOA/GCC-PHAT practice, not invented from this dataset) — that crossing
  point is "the SNR floor," an output of this test, not a threshold to hit.
- **Step 2 (real bleed):** counts as a usable lock in a given condition (volume/orientation/distance)
  if **PSR ≥ 6dB and recovered offset is within ±2ms** of the ground truth already established by
  Test 1's loopback measurement. **Overall Test 2 pass bar:** the baseline realistic condition
  (comfortable conversational playback volume, phone within arm's reach, no obstruction) must clear
  this bar. Edge conditions (quiet volume, phone in a pocket) failing is acceptable and becomes a
  documented UX constraint (e.g., app enforces a minimum playback volume) rather than a test failure.

**Confidence:** GCC-PHAT as a time-delay estimation method is well-supported by peer-reviewed literature (Knapp & Carter 1976). What's untested is device-specific applicability — I have no evidence either way on whether typical phone speaker/mic bleed clears the SNR floor this method needs, and the design doc itself flags this as an open empirical question.

**Second phone:** optional, lower priority. Only add it if step 2 passes and you want an early read on cross-device portability before further investment.

**Cross-device generalization (added 2026-07-05).** Test 2's on-device numbers are gathered on a
single Pixel 10 (Tier-2 green as of 2026-07-05: zero XRuns, baseline capture RMS ~320-340,
48kHz/96-frame bursts, `LowLatency`/`Exclusive` granted). It matters to be precise about what that does
and doesn't establish for other Android hardware — two halves generalize differently:

- **The algorithm and the pass/fail *criteria* generalize** (device-independent). GCC-PHAT's
  correctness, the ±1-sample synthetic accuracy, and the 6dB PSR floor (≈−30dB SNR for a broadband
  click train) come from the synthetic step 1 with no device in the loop, so the SNR→PSR mapping is a
  property of the algorithm and signal class, not the phone. The PSR ≥ 6dB / offset-within-±2ms bars
  are borrowed from TDOA practice, not fit to Pixel data, and the ±2ms bar is measured against *that
  device's own* loopback ground truth, so the criterion is self-relative and transfers even though the
  absolute latency does not.
- **Whether real bleed clears that floor does *not* generalize** — an empirical per-device question
  dominated by (a) speaker/mic hardware SNR (loudness, sensitivity, chassis geometry — the Pixel 10's
  baseline capture RMS is a Pixel-10 number) and, the bigger wildcard, (b) OEM mic DSP. The harness
  forces `InputPreset::VoiceRecognition` to suppress AGC/NS, but that's a *request* OEMs honor
  inconsistently; residual AGC in particular auto-compensates a quiet bleed and flattens exactly the
  volume/distance SNR gradient this sweep exists to map. Secondary per-device unknowns: whether
  LowLatency/Exclusive is granted at all, the native sample rate (48kHz on Pixel — affects sample-count
  arithmetic, not physics), and route-forcing quirks.

**Direction of the bias:** the Pixel 10 is close to a *best case* for this approach (clean near-AOSP
audio stack, well-behaved AAudio, good transducers, honest preset handling). A Pixel pass is therefore
a favorable-case existence proof — "the approach and the code are sound, and it clears the bar on a
good device" — and generalizing it downward to budget or heavy-OEM-skin hardware should be expected to
get *worse*, not better. (Had it *failed* on Pixel, that would have been near-fatal for the bleed
approach outright.) There's already adjacent evidence of device variance: the moto g(20) platform-
latency counter-example (Test 1a) and the Pixel 8/9 200–700ms A/V-sync reports.

**What establishing generalization would take:** re-run the same harness on a deliberate spread (a
budget device, a heavy-skin device such as Samsung, a mid-tier), logging per device whether
LowLatency/Exclusive is granted and at what rate/burst, the resulting bleed SNR/PSR vs. the Pixel
baseline, and — most sharply — whether forcing VoiceRecognition actually disabled AGC (directly
testable: play a fixed tone at two known gains and check whether captured RMS preserves the gain ratio
or compresses it; compression = AGC still active = SNR-mapping compromised on that device). The
harness's metadata already logs `device_model`, `sample_rate`, `input_preset`, `xrun_count`, and
`stream_volume_index`, so it can be pointed at a second device with no code change.

**Design consequence:** because generalization is gated on OEM behavior the app doesn't control, the
product likely can't assume bleed-based alignment works on every device — it may need a device
allowlist or a runtime bleed-SNR self-check. This is a large part of why Test 1a (trusting AAudio's
self-reported latency, a more nearly device-agnostic mechanism) exists, and why the design contemplates
per-route/per-device mechanism selection rather than one path for all hardware.

## Test 3 (proposed) — Multi-hop alignment drift simulation

**Question:** Do independent per-hop alignment errors compound across a chain of overdubs
(A→B→C→D...) into audible drift by the last track, even if raw stems (not a flattened mix) are
forwarded at every hop?

**Setup:** Pure synthetic, extends Test 2 step 1's Python harness — no phone needed. Model each hop's
alignment error as an independent random draw from the error distribution characterized empirically
by Test 1a/Test 2 (once that data exists), or from a range of plausible values as a placeholder if
not. Simulate chains of N hops (e.g. N = 2 through 6) and track the cumulative worst-case offset
between the earliest and latest track across many simulated chains (Monte Carlo, 1000+ trials per
chain length).

**What this answers:** Whether the "always forward raw stems" mitigation
(design-summary.md's "Chain-of-forwarding alignment error") is sufficient on its own, or whether a
chain of even small per-hop errors accumulates past an audible threshold (e.g. ±10–20ms) at
realistic chain lengths — which would mean either a stricter per-hop accuracy requirement, or an
explicit re-alignment step against the *original* reference at some point in the chain (rather than
only against the immediately-prior track).

**Pass/fail threshold:** Using the same 15ms top-level ceiling, the 95th-percentile cumulative
worst-case offset across simulated chains must stay **≤15ms at N=4 hops** (treated as the realistic
typical chain length) for the "always forward raw stems" mitigation to be declared sufficient on its
own. N=6 is tracked as a stress case, not a hard gate. Exceeding 15ms at N=4 fails this test and
means either a stricter per-hop accuracy requirement or an explicit mid-chain re-alignment step
against the original reference is needed.

**Confidence:** High confidence the simulation approach itself is sound — standard
error-propagation/Monte Carlo exercise. Low confidence in the outcome — no data yet on the actual
per-hop error distribution, so this test's realistic inputs aren't known until Test 1a/Test 2 run
first. **Sequencing: run last of the four**, since it consumes their output.

## Explicitly out of scope for this prototype

- Lead-in / count-in UX
- Echo cancellation (NLMS or `AcousticEchoCanceler`) — deferred pending Test 2 results
- Sharing/forwarding flow
- Pre-roll buffer sizing
- Onset detection
- Forced-speaker calibration chirp / adaptive hybrid routing (headphone fallback) — deferred pending Test 1a's result
- Explicit re-alignment/correction against the original reference mid-chain (multi-hop drift fallback) — deferred pending Test 3's result

None of these matter if Test 1, Test 1a, Test 2, or Test 3 fails, and building them now would be scope creep against the design doc's own stated priorities.

## Realistic timeline

A few days each for Test 1 and Test 2, for someone comfortable with Kotlin/NDK and basic Python signal processing. Test 1a adds relatively little on top of Test 1 since it reuses the same rig — mostly just logging and comparing an extra number per run. Test 3 is a half-day to a day once Test 1a/Test 2 produce real error data to drive it (it's pure Python, no device time needed). Not a confident estimate — I don't know your familiarity with Oboe specifically or whether device access is immediately available, and haven't seen any of these tests run to calibrate against.
