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

## Test 1 — Latency harness (continuous-buffer stability)

**Question:** Does a single continuous audio buffer (lead-in + overdub target) preserve a stable, correctly-measured round-trip offset, or does a scheduling seam introduce silent error?

**Setup:** One Android device (any available — the goal is validating your implementation's behavior, not benchmarking a specific device against a published spec number, since no authoritative Pixel 10 latency figure exists anyway). Build the continuous-buffer capture/playback path using Oboe with `PerformanceMode::LowLatency` and `SharingMode::Exclusive` (per `developer.android.com/games/sdk/oboe/low-latency-audio`).

**Method:** Loopback test — physical clap or a known click track through a loopback cable — repeated ~20 times. Check `AAudioStream_getXRunCount()` for buffer underruns on each run. Confirm the measured offset is stable across repetitions and doesn't drift when the lead-in and target recording are scheduled as one continuous stream vs. (as a negative control) two sequentially-scheduled players.

**What this answers:** Direct yes/no on whether the "no scheduling seam" assumption holds. Doesn't require musical content or a second device.

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

**Confidence:** Low confidence either way — the design doc's rejection of this approach rested on a
single anecdotal report, not a systematic test, so this is a genuinely open question rather than one
with a directional prior.

## Test 2 — Single-device bleed + offline alignment

**Question:** Does GCC-PHAT recover a clean, usable alignment peak from real phone-speaker-to-phone-mic bleed, or does real-world SNR fall below what the algorithm needs?

**Setup correction (single device, not two):** The actual bleed mechanism in the design is one phone playing back the beatbox track through its own speaker while simultaneously recording the overdub through its own mic — playback and capture on the *same* device. One phone is sufficient and correctly reproduces the mechanism being tested. A second phone would only be useful later, for checking cross-device variance in speaker/mic hardware and AGC behavior — a real but lower-priority question, not what this test is scoped to answer.

**Recommended sequencing** (given Windows 11 is available for the analysis half):

1. **Synthetic validation first, on Windows.** Inject known delays and controlled noise levels into a clean signal using Python (`scipy.signal.correlate` plus an FFT-based phase transform for the GCC-PHAT weighting). Confirm the implementation recovers the correct offset and map out the theoretical SNR floor where it starts to fail. This is pure software — no phone needed — and isolates "is the code correct" from "does the physical setup work."
2. **Real-bleed recording, one phone.** Record the clean beatbox track, then have the same phone play it back through its speaker while recording the overdub through its mic. Vary playback volume and phone orientation/distance from any obstruction to map where the correlation peak degrades. Run the validated GCC-PHAT implementation from step 1 against this real data.

**What this answers:** Whether the "no calibration step needed" claim in the design doc — which currently rests on GCC-PHAT being appropriate in principle — holds up against actual phone-mic-quality bleed. A failure at step 2 (after step 1 passes) tells you the acoustic environment doesn't have enough SNR, not that the algorithm is wrong.

**Confidence:** GCC-PHAT as a time-delay estimation method is well-supported by peer-reviewed literature (Knapp & Carter 1976). What's untested is device-specific applicability — I have no evidence either way on whether typical phone speaker/mic bleed clears the SNR floor this method needs, and the design doc itself flags this as an open empirical question.

**Second phone:** optional, lower priority. Only add it if step 2 passes and you want an early read on cross-device portability before further investment.

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
