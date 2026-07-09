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
harness to check this, once real per-hop error data exists to drive it. (Revised 2026-07-08: the
"compounding" framing was corrected — under align-to-original, per-hop noise doesn't chain; see
Test 3's model correction.)

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
   | Test 2 — recovered-offset accuracy | within ±2ms of in-basis ground truth | Was stated only in Test 2's pass bar and omitted from this table (fixed 2026-07-08); it is the per-hop alignment-accuracy allowance the multi-hop model consumes. |
   | Test 3 — multi-hop misalignment | 95th-percentile max pairwise offset ≤15ms at N=4 hops | The same top-level ceiling applied end-to-end, not an independent allowance (see point 4). Reworded 2026-07-08 from "cumulative drift": per-hop errors don't sum under align-to-original — see the revised Test 3. |

3. **Caveat:** these numbers are literature-grounded and defensible as genuinely decided in
   advance, but they weren't validated against phone-speaker-to-phone-mic bleed specifically. If
   Test 2 step 1 (synthetic, no device involved) shows the algorithm structurally cannot reach the
   PSR floor even at high SNR, that's an *achievability* finding, not grounds to quietly lower the
   *acceptability* bar — it would mean reconsidering the design direction, per this doc's stated
   purpose, not relaxing the threshold post-hoc.

4. **Budget reconciliation against first measured data (added 2026-07-08).** These rows are not
   independent allowances that sum to 15ms — Test 3's 15ms is the same top-level ceiling applied
   end-to-end, consuming the per-hop errors Tests 1/1a/2 bound. And the first measured numbers
   already crowd it: the Pixel 10 timestamp study (`test2-sweep-results.md`) leaves a **5.5ms
   per-measurement residual std** after timestamp correction. If that were all real alignment
   error, a *single* overdub pair (two tracks, each with an independent ~5.5ms-std error vs. the
   shared reference) has a pairwise-difference std of ~7.8ms — 95th percentile ≈15ms, the entire
   ceiling consumed at one hop, before any chain. It also exceeds Test 1a's ≤5ms allowance as a
   raw number. Part of the 5.5ms is plausibly measurement quantization (band-limited-correlation
   resolution + `getTimestamp` granularity) rather than product-path error, but decomposing that
   split is now load-bearing, not a footnote — the in-basis calibration click (Test 2's
   ground-truth correction below) is the instrument that decomposes it. **Update 2026-07-08:** the
   click now exists and its first cross-check reframes this number — the timestamp study's offsets
   were *alias* offsets (+187ms beat-period aliases), so the 5.5ms is jitter in the
   alias-vs-true-peak relationship, not yet directly the product's per-hop error. Because the
   alias sits at a near-fixed offset from the truth, the *std* (variance) carries over to the
   true peak, so the budget arithmetic is not invalidated — but the real correlator-error number
   must be re-measured against the click before this budget is trusted. **First such measurement
   (2026-07-08, click-anchored gate on the baseline capture): correlator-vs-click error
   -0.54 ms** — well inside ±2 ms, an encouraging sign that most of the 5.5 ms residual std is
   harness/quantization rather than correlator error; the 36-cell click-gated re-run provides
   the population number. **Session A measurement (2026-07-08, baseline × 9 repeats,
   `test2-sweep-results.md` "Session A re-capture"): correlator-vs-click error mean −1.18 ms,
   std 0.25 ms, max 1.35 ms — 9/9 inside ±2 ms.** The 5.5 ms scare is resolved: it was harness
   start-jitter + quantization, and the correlator's own per-session std (0.25 ms) consumes
   almost none of the ±2 ms per-hop allowance (the stable ~−1.2 ms bias is calibratable, not
   noise). One new budget input cuts the other way: **1 of 9 runs showed a ~40 ms `getTimestamp`
   outlier** (stream−click residual +24.5 ms vs. the −15.1 ± 0.25 ms cluster of the other
   eight) — on the best-case device, so Test 1a's ≤5 ms trust bar cannot be met by a single
   timestamp read; any product mechanism using `getTimestamp` needs repeated reads/median and
   the loopback-rig honesty check remains load-bearing.

## Test 1 — Latency harness (continuous-buffer stability)

**Question:** Does a single continuous audio buffer (lead-in + overdub target) preserve a stable, correctly-measured round-trip offset, or does a scheduling seam introduce silent error?

**Setup:** One Android device (any available — the goal is validating your implementation's behavior, not benchmarking a specific device against a published spec number, since no authoritative Pixel 10 latency figure exists anyway). Build the continuous-buffer capture/playback path using Oboe with `PerformanceMode::LowLatency` and `SharingMode::Exclusive` (per `developer.android.com/games/sdk/oboe/low-latency-audio`).

**Hardware status (2026-07-05):** loopback rig ordered — a PassMark Audio Loopback Plug (TRRS)
plus a Movo UCMA-2 USB-C-to-TRRS adapter, needed since the target device (Pixel 10) has no 3.5mm
jack. This is a fully electrical loopback path (phone USB-C → UCMA-2 → PassMark plug), so no
physical clap/acoustic signal is needed for this test — the test signal is generated and read back
over the wired connection, primarily by the harness's own capture path with OboeTester as a
cross-check (see Method below). Test 2's acoustic bleed test is unaffected by this and still
uses the phone's built-in speaker/mic directly. **Update (2026-07-08): rig delivery is
delayed.** Interim de-risking that needs no rig — most of the timestamp-variance question —
is scheduled under Test 1a's "Interim timestamp-variance plan" below.

**Method (revised 2026-07-08 — stale "physical clap" wording removed; the rig is fully electrical,
per the hardware-status note above):** drive a known click/test signal through the electrical
loopback, **through the harness's own continuous-buffer capture path — not OboeTester alone.**
OboeTester measures the *device's* round-trip latency, but it cannot test this implementation's
scheduling-seam hypothesis, and its number lives in a different measurement basis than the
harness's captures (see Test 2's ground-truth correction), so it serves as a sanity cross-check,
not the primary instrument. Repeat ~20 times. Check `AAudioStream_getXRunCount()` for buffer
underruns on each run. Confirm the measured offset is stable across repetitions and doesn't drift
when the lead-in and target recording are scheduled as one continuous stream vs. (as a negative
control) two sequentially-scheduled players. The electrical path is also deliberately the
instrument here rather than an acoustic click: no room noise or reverb, so rep-to-rep variance
reflects scheduling behavior rather than acoustics — which matters for a test whose negative
control must *detectably* fail.

**What this answers:** Direct yes/no on whether the "no scheduling seam" assumption holds. Doesn't require musical content or a second device.

**Pass/fail threshold:** Measured offset variance across the 20 reps must stay within **±3ms**
(e.g. ~144 samples at 48kHz — actual sample count depends on the device's native rate) for the
continuous-stream condition. **Any buffer underrun (`AAudioStream_getXRunCount()` > 0) is a hard
fail** regardless of measured variance, since an underrun invalidates the continuous-stream
assumption outright. The negative-control (two sequentially-scheduled players) is expected to fail
this bar — if it doesn't, that's a signal the test rig isn't sensitive enough to detect a scheduling
seam, not that seams are harmless.

**Threshold clarification (2026-07-08):** the ±3ms bar applies to the offset *within a session* —
equivalently, to per-rep offsets after subtracting each rep's own `getTimestamp`-derived stream
offset. It does **not** apply to raw offsets compared across ~20 independently-started sessions:
the Pixel 10 timestamp study (`test2-sweep-results.md`) measured ~13.4ms std of benign per-session
start jitter across independently-started stream pairs, which would blow ±3ms for reasons already
understood and unrelated to the continuous-stream hypothesis this test exists to check. (The
product self-measures within one continuous session, so within-session is also the
product-relevant quantity.)

**Confidence:** High confidence this test design is correct — it mirrors Google's own recommended latency-measurement approach (OboeTester, per AOSP's audio latency documentation). Low confidence in what the result will be — the design doc already flags real A/V sync bugs (200–700ms) reported by Pixel 8/9 users as a different-but-adjacent failure mode, which is a signal, not a prediction.

## Test 1a — AAudio self-reported latency accuracy (headphone-safe alignment path)

**Priority: run this first.** Cheapest of the three to validate, and if it passes it removes the
entire bleed-dependency question for headphone-wearing users rather than requiring a workaround.

**Question:** Does AAudio/Oboe's own reported stream latency (timestamps against the shared audio
clock) match the ground-truth round-trip latency measured by the physical loopback, closely enough
to use directly as the alignment offset — with no dependence on any acoustic bleed signal?

**Setup:** The same loopback rig as Test 1 (the fully electrical USB-C loopback — no clap/acoustic
signal, per Test 1's hardware-status note) — no new hardware. Log `AAudioStream_getTimestamp()` (or Oboe's equivalent) alongside the
ground-truth offset already being measured for Test 1, across whatever output routes are available
(built-in speaker, wired headset, Bluetooth if on hand).

**Method:** For each of the ~20 repetitions Test 1 already runs, record both numbers side by side —
the loopback-measured ground truth and AAudio's self-reported latency. Compare across routes: does
the discrepancy (if any) stay consistent, or does it change meaningfully between speaker and
headphone output? Repeat on a second device if available, since the design doc's one documented
counter-example (moto g(20)) was device-specific, not universal. (Protocol addition 2026-07-08:
take ~10 timestamp reads per repetition, not one — Session A observed a 1-in-9 single-read
~40 ms outlier, so single reads are untrustworthy and the rep batch doubles as the outlier-rate
measurement Test 3's median-of-k knife-edge needs.)

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

**Status update (2026-07-08):** partially de-risked ahead of the rig. The Pixel 10 timestamp study
(`test2-sweep-results.md`, "Stream-timestamp decomposition confirmed") already shows `getTimestamp`
succeeding on both streams and tracking per-session start jitter (subtracting it collapses the
run-to-run offset std 13.4→5.5ms) — the mechanism is *available and self-consistent* on this
device. What the rig still owes this test is the *honesty* check: that the reported values match
physical truth (the moto g(20) failure class) on the route the rig measures. Note the 5.5ms
residual std brushes this test's ≤5ms allowance as a raw number; how much of it is quantization
vs. real error is decomposed by the in-basis calibration click (Test 2's ground-truth correction).

**Interim timestamp-variance plan (2026-07-08, rig delayed).** The rig is irreplaceable only for
headphone-route *honesty* and Test 1's seam check; the timestamp *variance* questions are
testable now, and the Session A outlier made them urgent — Test 3's median-of-5 remedy rests on
an untested assumption (that an outlier is a single-read glitch, not a session-level state) and
on a one-observation outlier rate. Three steps, none needing the rig:

1. **Decompose the existing outlier — zero device time.** The Session A sidecars carry all four
   raw `(framePosition, nanoTime)` values, so the repeat-7 anomaly can be attributed to a
   specific component (input vs. output frame position vs. clock delta) across the 9 runs. The
   attribution may enable a cheaper, stronger remedy than medians (e.g. sanity-checking
   `framePosition` against elapsed capture length). **Done (2026-07-08,
   `test2-sweep-results.md` "Session A timestamp-outlier decomposition"):
   no reliable single-component attribution.** `frame_delta`'s +40 ms deviation matches the
   offset error exactly (pointing at an input `framePosition` glitch) but its own benign cluster
   spreads ±24 ms — the start-jitter item 10 already measured — and the wall-anchor referents
   spread ±40 ms, so no single-read referent discriminates a 40 ms anomaly. Single-read sidecars
   under-determine the culprit; the framePosition-vs-length sanity check this step hoped to
   validate is *not* free-standing (its `input_minus_wav` cluster spreads 15.6 ms). Consequence:
   step 2's multi-read logging is now load-bearing for *both* the outlier rate and the
   glitch-vs-session-state discrimination (its frame-vs-time-line discriminator needs no
   cross-run referent, sidestepping this under-determination); median-of-5 stays the leading
   remedy candidate on "no evidence the glitch is session-level" + step 2's measurement, not on
   a proven single-read glitch.
2. **Multi-read logging + unattended batch — device, no rig, no repositioning.** Harness change:
   read `getTimestamp` ~10× spread across each session (not once at `stop()`), log all reads in
   the sidecar; then ~30–50 baseline captures via `repeat_sweep_cell.sh`. Yields (i) the outlier
   rate at real sample size (at a true 1/9, ~30 sessions show 3–4 outliers; 0–1 says the rate is
   much lower), (ii) the glitch-vs-session-state discrimination that decides whether median-of-k
   is a valid remedy at all, (iii) a large-N read-noise std replacing the 8-point 0.25 ms
   estimate, and (iv) a bigger stream−click residual population — the click being a rig-free
   honesty check on the speaker route. **Done (2026-07-08, `test2-sweep-results.md` "Multi-read
   timestamp batch"): 43 baseline captures on the Pixel 10 (11 reads/session).** (i) Outlier
   rate: 2/43 runs (4.7%) with a timestamp anomaly — lower than the 1/9 the binomial feared, but
   a thin estimate. (ii) **The discrimination went against the clean single-read-glitch
   hypothesis: the 2 anomalies are two *different* classes.** One was an isolated timestamp
   glitch (click-anchored alignment PASSED; median of 11 reads recovered the true offset despite
   the single read being the +24.89 ms outlier) — median-of-k works for this class. The other was
   a **session-level desync**: the input clock read ~+35 ms off for the whole session, the audio
   itself misaligned 78.67 ms (click FAIL), the median wrong too, and 0 XRuns/0 dropped/correct
   route — silent to every standard gate, caught only by the click. **Median-of-k cannot fix the
   session-level class, so it is not a blanket remedy; it must be paired with a per-capture
   rejection/consistency gate.** A uniform whole-session offset shift (2 clean runs sat 3 ms off
   the basis with zero off-line reads) is invisible to the line-fit flagger, so line-fit
   consistency is not a substitute for the independent anchor either. (iii) Read-noise std over
   the 39 on-basis clean runs ~0.4 ms (the multi-read median collapses the item-10 5.5 ms scare
   to well under 1 ms once anomalous runs are gated out). (iv) The stream−click residual
   population confirms a stable ~−15.1 ms basis on clean runs and is the rig-free speaker-route
   honesty check — but it also shows the headphone route (no click, no runtime rig) would leave
   the session-level class silent, which is the concrete failure the rig's honesty validation
   must de-risk.
3. **Headset-route variance — only if a wired USB-C headset is on hand.** Variance/outlier
   statistics on the exact route this test targets need only the route active; the click won't
   anchor (no bleed), but pure timestamp statistics don't need it. Honesty still waits for the
   rig.

**Rig scoping — why the loopback is still worth running (added 2026-07-08).** After the
ground-truth correction (Test 2), the rig no longer serves as any test's ±2ms referent, which
raises the fair question of what it still establishes. The answer is narrower than the original
scoping, and more decisive:

- **It is the only ground truth for the route where the product trusts timestamps blind.** The
  headphone-monitoring case this test exists for has, by premise, no acoustic path back to the
  mic — so the in-basis calibration click (which validates acoustically, speaker→mic only) cannot
  reach it. An electrical loopback is the only independent measurement of what leaves the jack and
  when — i.e. the only way to catch a moto-g(20)-class lie on exactly the route where the product
  would rely on the reported number with no fallback signal.
- **Rig + click compose per-stream.** Timestamp honesty is a per-stream, per-route property, and a
  realistic headphone session likely runs headset-output + built-in-mic input (inline headset mics
  are poor for vocals). The rig validates the headset-output stream's timestamps; the click
  validates the built-in-speaker output and built-in-mic input. Together the two instruments cover
  every stream/route half the product uses; neither alone does.
- **The result is decisive in both directions.** Within the ≤5ms bar against electrical truth: the
  headphone path is viable as designed and the forced-chirp/adaptive-hybrid fallbacks stay
  shelved. Outside it: a hard trigger for those fallbacks on that route — a design fork, not a
  shrug.
- **What the rig does NOT establish:** anything about the speaker→mic acoustic path or Test 2's
  ±2ms bar (both the calibration click's job now), and anything about Bluetooth — a TRRS plug
  can't reach the BT stack, so if BT monitoring ever stops being "ruled unpredictable"
  (design-summary.md) it needs its own honesty check.
- **Cross-device caveat:** a wired-route honesty pass on the Pixel is a favorable-case existence
  proof, same as the sweep — the moto g(20) anecdote is a *per-device* failure class, so whether
  the product can trust timestamps at runtime or must self-check them per device remains a
  cross-device question regardless of this result.

## Test 2 — Single-device bleed + offline alignment

**Question:** Does GCC-PHAT recover a clean, usable alignment peak from real phone-speaker-to-phone-mic bleed, or does real-world SNR fall below what the algorithm needs?

**Setup correction (single device, not two):** The actual bleed mechanism in the design is one phone playing back the beatbox track through its own speaker while simultaneously recording the overdub through its own mic — playback and capture on the *same* device. One phone is sufficient and correctly reproduces the mechanism being tested. A second phone would only be useful later, for checking cross-device variance in speaker/mic hardware and AGC behavior — a real but lower-priority question, not what this test is scoped to answer.

**Recommended sequencing** (given Windows 11 is available for the analysis half):

1. **Synthetic validation first, on Windows.** Inject known delays and controlled noise levels into a clean signal using Python (`scipy.signal.correlate` plus an FFT-based phase transform for the GCC-PHAT weighting). Confirm the implementation recovers the correct offset and map out the theoretical SNR floor where it starts to fail. This is pure software — no phone needed — and isolates "is the code correct" from "does the physical setup work."
2. **Real-bleed recording, one phone.** Record the clean beatbox track, then have the same phone play it back through its speaker while recording the overdub through its mic. Vary playback volume and phone orientation/distance from any obstruction to map where the correlation peak degrades. Run the validated GCC-PHAT implementation from step 1 against this real data.

3. **Vocal-interference injection (added 2026-07-08; pure Python, no device time).** The 36-cell
   sweep captures bleed against a quiet room floor, but production must find the bleed *underneath
   a loud, close-mic vocal performance* — and the validated 500–4000 Hz analysis band is exactly
   the speech band, so the vocal is maximally in-band interference. This was listed as an open
   item in design-summary.md ("loud/close-mic vocal vs. quiet bleed") but covered by no test.
   Method: record one dry close-mic vocal take (rap/sung), mix it into the existing 36 captures at
   controlled vocal-to-bleed ratios using the step-1 harness's controlled-injection machinery, and
   re-run the band-limited GCC-PHAT. Output: the vocal-to-bleed ratio at which the baseline cell
   stops clearing the bar — the production-relevant analog of step 1's SNR floor. **Pin the
   "realistic ratio" in advance** (measure the RMS of an actual performance take at arm's length
   against the baseline cell's bleed RMS *before* looking at any PSR results) so pass/fail isn't
   judged after seeing the data. The baseline cell at that realistic ratio must clear the same
   PSR ≥ 6dB + ±2ms bar for Test 2's conclusion to extend to production conditions. Fold the
   step-1 SNR-floor re-measurement (band-limited pipeline + real beatbox reference) into this
   step, since the click-train floor did not transfer.
   **Done (2026-07-08, `test2-sweep-results.md` "Vocal-interference injection study"):** the
   realistic ratio was pinned in advance at **−12.2 dB** (in-basis close-mic takes 2 and 3 agree
   exactly — the vocal lands *below* the bleed, the opposite of the "loud vocal" assumption), and
   the baseline cell clears the click gate at that ratio. The alignment is essentially **immune**
   to the vocal: the click-anchored GCC-PHAT offset is unchanged by even 1 sample from +0 to
   +24 dB in-band ratio; the failure mode at +24–30 dB is the vocal burying the *calibration
   click* (anchor lost, `no-click`), not pulling the alignment — ~36 dB of margin above the
   realistic ratio. Cross-take robust. The folded-in SNR-floor re-measurement is also done —
   floor −27..−30 dB in-band, set by click burial, correlator immune (see the step-1 caveat
   above and `test2-sweep-results.md`).

**Implementation status (2026-07-05):** step 1's Python GCC-PHAT is implemented and its
synthetic-validation gate passes (`analysis/src/overdub_analysis/gcc_phat.py` +
`synth.py`, 14 pytest cases green). At high/clean SNR (30 dB ≥ the 20 dB bar) the recovered
offset is within ±1 sample of the injected delay and PSR ≥10 dB; the 6 dB PSR floor for a
broadband periodic click train sits at ≈ −30 dB SNR (run
`analysis/scripts/sweep_snr_floor.py` to reproduce) — far below any realistic phone-bleed SNR
for that signal class. (Caveat, added 2026-07-08: that floor did *not* transfer to the real
signal — the real sweep failed 0/36 full-band. **Re-measured later the same day with the
production pipeline** — real click-bearing reference, band-limited 500–4000 Hz, click-anchored
±90 ms window, ±2 ms gate (`analysis/scripts/sweep_snr_floor_real_reference.py`): the floor is
**−27..−30 dB in-band SNR, set entirely by calibration-click burial** — the anchored correlator
posts 0.00 ms error at every SNR where the click anchors, the same anchor-first failure structure
the vocal study found. See `test2-sweep-results.md` "Synthetic SNR-floor re-measurement.") The synthetic fixtures double as the
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
alignment. The lag-window and PSR-exclusion re-checks are since done (items 7a-7b in
`test2-step2-plan.md`); the ±2 ms-vs-ground-truth half of the bar still lacks its referent — which,
per the ground-truth correction under "Pass/fail threshold" below (2026-07-08), is an in-basis
calibration click embedded in the reference track, *not* Test 1's loopback number as previously
stated here. Results remain Pixel-10-specific (see "Cross-device generalization" below).
**Resolved 2026-07-08 (calibration-click cross-check, `test2-sweep-results.md`): the +61..+151 ms
family — including the +97 ms "population mean" and the edge cell's "band-robust" +87 ms — are
~+187 ms beat-period *aliases* of negative true harness-basis offsets, not correct alignments. The
"confident" PSR verdicts describe sharp alias peaks. The calibration click (matched filter,
independent of the correlator) measured the true baseline offset at -79.62 ms; GCC-PHAT reported
+107.12 ms, ~187 ms off — essentially one reference beat period. So PSR ≥ 6 dB + a (0, 300 ms)
positivity lag window is *not* a sufficient alignment gate: both bless the alias (the true offset
is negative in the harness basis, so the "plausible positive" window pointed the wrong way, and
the beat-period peak is a real sharp feature of the reference's autocorrelation). The honest gate
is `|gcc_phat_offset - click_offset| ≤ 2 ms` per capture, with the lag window admitting negative
offsets (or re-basis by trimming to beatbox-only content so the positivity prior holds). Test 2
step 2 is **not passed**; the 36-cell sweep must be re-run against the click-bearing reference and
re-gated. See `test2-sweep-results.md` "Calibration click cross-check."** **Re-run and re-gated
(2026-07-08, Session A): 11/11 PASS under the click-anchored gate — the baseline gate cell × 9
repeats (correlator error mean −1.18 ms, std 0.25 ms, max 1.35 ms) plus the min-bleed and
HF-rattle extreme cells. The step-2 pass bar — the baseline realistic condition within ±2 ms of
in-basis ground truth — is met; Session B (the remaining arrangements → the full 36-cell map) is
confirmatory-only. See `test2-sweep-results.md` "Session A re-capture."**

**What this answers:** Whether the "no calibration step needed" claim in the design doc — which currently rests on GCC-PHAT being appropriate in principle — holds up against actual phone-mic-quality bleed. A failure at step 2 (after step 1 passes) tells you the acoustic environment doesn't have enough SNR, not that the algorithm is wrong.

**Pass/fail threshold:**
- **Step 1 (synthetic, implementation-correctness gate):** at high/clean SNR (e.g. ≥20dB), recovered
  offset must match the injected delay within **±1 sample** and peak-to-sidelobe ratio (PSR) must be
  **≥10dB** — this confirms the code is correct before using it to map anything. Sweep noise level
  downward and record the SNR at which PSR crosses below **6dB** (the minimum-acceptable floor,
  borrowed from standard TDOA/GCC-PHAT practice, not invented from this dataset) — that crossing
  point is "the SNR floor," an output of this test, not a threshold to hit.
- **Step 2 (real bleed):** counts as a usable lock in a given condition (volume/orientation/distance)
  if **PSR ≥ 6dB and recovered offset is within ±2ms** of the in-basis calibration-click ground
  truth (see the ground-truth correction below — *not* Test 1's loopback number, as this bar
  originally read). **Overall Test 2 pass bar:** the baseline realistic condition
  (comfortable conversational playback volume, phone within arm's reach, no obstruction) must clear
  this bar. Edge conditions (quiet volume, phone in a pocket) failing is acceptable and becomes a
  documented UX constraint (e.g., app enforces a minimum playback volume) rather than a test failure.

**Ground-truth correction (2026-07-08).** This bar originally read "within ±2ms of the ground truth
already established by Test 1's loopback measurement." That comparison is invalid as written, for
two independent reasons:

- **Route mismatch:** the loopback rig is electrical via the USB-C adapter, so it measures the
  wired route's round trip — not the builtin-speaker→builtin-mic path Test 2's bleed uses.
  Per-route latencies differ; that is Test 1a's own premise.
- **Measurement-basis mismatch:** the harness's GCC-PHAT offset carries a large fixed
  harness-specific constant (~201ms on the Pixel 10 — the captured WAV's sample 0 is not
  input-stream frame 0 once the input-buffer sizing and startup drain gap fold in; see
  `test2-sweep-results.md`). A latency measured by another tool (OboeTester) in its own basis
  cannot be compared at ±2ms against an offset measured in the harness's basis. (Resolved
  2026-07-08: the ~201ms is itself ~14-15ms genuine basis residual + ~187ms correlator *alias*,
  not one calibration constant — see the cross-check.)

The ground truth must be **in-basis and on-route**: embed a short high-SNR calibration click at a
known sample position in the bundled reference track, detect its onset in the captured WAV (onset
detection at high SNR is trivially accurate and independent of the correlator being judged), and
judge the GCC-PHAT-recovered offset against that click-derived offset *in the same file*. This
also decomposes the timestamp study's 5.5ms residual std into correlator error vs. measurement
quantization (see "Quantitative thresholds," point 4). Test 1's loopback rig keeps a narrower,
still-necessary role: independently verifying that `getTimestamp` values are honest (the
moto g(20) failure class) on the route it actually measures. ~~Requires regenerating the bundled
reference asset and re-capturing at least the baseline cell — the existing 36 WAVs carry no click.~~
**Done 2026-07-08:** the click library + prepend/detect scripts + 8 unit tests are committed
(`analysis/src/overdub_analysis/calibration_click.py` etc.), the asset is regenerated (16.25s,
chirp at sample 9600), and a baseline cell was re-captured on the Pixel 10. The cross-check
immediately paid off — it exposed that the prior +97ms family are +187ms beat-period aliases, not
alignments (see the implementation-status resolution above and `test2-sweep-results.md`).
The alias-rejection remedy was then decided on that same capture (2026-07-08,
`test2-sweep-results.md` "Alias-gate remedy decision"): the alias peak is genuinely ~12 dB larger
than the true peak in the band-limited correlation, so no wide lag window — signed or not — can
reject it; the gate is a click-anchored ±90 ms window (narrower than half the ~187 ms beat
period, so a one-beat alias is excluded by construction) plus
`|gcc_phat_offset - click_offset| ≤ 2ms`, with PSR demoted to a diagnostic (the true acoustic
peak is a multipath cluster that reads ~0 dB PSR even when correct). A
stream-timestamp-anchored window recovered the same true offset, validating the product-shaped
mechanism (the product has no click, but has `getTimestamp`). Pipeline:
`analysis/scripts/run_click_gated_sweep.py`. Remaining: the staged re-capture (the
`reflector_geometry` field landed 2026-07-08) — Session A: baseline cell × ~9 repeats plus the
min-bleed and HF-rattle extreme cells, which yields the step-2 verdict on the gate cell, the
per-session correlator-error std the budget reconciliation needs, and the stream-vs-click
basis-residual stability that feeds Test 1a; Session B: the remaining arrangements to restore
the full 36-cell alignment/UX-constraint map, run as confirmation if A passes or as
boundary-location if an extreme fails. Protocol detail: `test2-step2-plan.md` item 11 (c).
**Session A completed 2026-07-08: 11/11 PASS (see the implementation-status update above);
Session B is confirmatory-only, run when convenient.**

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
  device's own* in-basis ground truth (the calibration click, per the ground-truth correction above),
  so the criterion is self-relative and transfers even though the absolute latency does not.
- **Whether real bleed clears that floor does *not* generalize** — an empirical per-device question
  dominated by (a) speaker/mic hardware SNR (loudness, sensitivity, chassis geometry — the Pixel 10's
  baseline capture RMS is a Pixel-10 number) and, the bigger wildcard, (b) OEM mic DSP. The harness
  forces `InputPreset::VoiceRecognition` to suppress AGC/NS, but that's a *request* OEMs honor
  inconsistently; residual AGC in particular auto-compensates a quiet bleed and flattens exactly the
  volume/distance SNR gradient this sweep exists to map. Secondary per-device unknowns: whether
  LowLatency/Exclusive is granted at all, the native sample rate (48kHz on Pixel — affects sample-count
  arithmetic, not physics), and route-forcing quirks.

**Direction of the bias:** the Pixel 10 is close to a *best case* for this approach (clean near-AOSP
audio stack, well-behaved AAudio, good transducers — though "honest preset handling," originally
listed here too, is *not* established even on the Pixel: sweep finding 2 in `test2-sweep-results.md`
shows gain-ratio compression despite `VoiceRecognition`, so the AGC-linearity probe below is what
would decide it). A Pixel *pass* would be
a favorable-case existence proof — "the approach and the code are sound, and it clears the bar on a
good device" — and generalizing it downward to budget or heavy-OEM-skin hardware should be expected to
get *worse*, not better. (Had it *failed* on Pixel, that would have been near-fatal for the bleed
approach outright.) There's already adjacent evidence of device variance: the moto g(20) platform-
latency counter-example (Test 1a) and the Pixel 8/9 200–700ms A/V-sync reports. **Status 2026-07-08:
the calibration-click cross-check showed the prior "35/36 clear 6 dB" was 35/36 locking onto a
beat-period alias, not the true alignment (`test2-sweep-results.md`) — but the re-gated Session A
re-capture (click-anchored gate) then passed 11/11: the baseline gate cell × 9 repeats plus both
known-worst extreme cells, correlator error std 0.31 ms. So the favorable-case existence proof now
stands on the gate cell and the two extremes; the full-matrix Session B re-run is confirmatory.**

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

## Test 3 (revised 2026-07-08; first run 2026-07-08 — conditional PASS) — Multi-hop alignment error simulation

**Model correction (2026-07-08):** as originally framed ("do independent per-hop errors compound
into cumulative drift"), this test modeled a mechanism the design has already eliminated. Under
the raw-stem decision, every hop aligns against the *original* reference, so per-hop errors do not
chain: track k's timing error vs. the shared reference is an independent draw e_k, and the
misalignment between any two tracks i and j is |e_i − e_j| — the difference of two independent
draws, essentially flat in chain length (the worst pair among N tracks grows only as the range of
N iid draws, far slower than the random-walk sum "cumulative" implies; a random walk arises only
if each hop aligns to the *previous* track, which the raw-stem decision forbids). A Monte Carlo
that sums per-hop draws would "discover" compounding that cannot occur. What genuinely does worsen
with chain length — and what the simulation must model instead — is:

1. **Per-device systematic bias.** Each device's alignment mechanism can carry a fixed bias b_k
   (the moto g(20) ~100ms timestamp discrepancy is this class; the harness's own ~201ms
   measurement-basis constant is the same species, caught only because it was measured). Pairwise
   misalignment is then (b_i − b_j) + (e_i − e_j), and between heterogeneous devices the bias
   *differences* — which no chain-length statistics average away — are the realistic dominant
   term, not noise accumulation.
2. **Interference growth.** Hop k correlates against the original stem through the bleed of the
   k−1 *other* stems plus the performer's own vocal, all uncorrelated with the reference — so
   per-hop error variance grows with position in the chain rather than being iid. Its magnitude
   comes from Test 2 step 3 (vocal-interference injection), not from an assumed constant.

**Question (revised):** With per-device biases and position-dependent interference modeled, does
the 95th-percentile **max pairwise** offset between any two tracks stay ≤15ms at N=4?

**Setup:** Unchanged in spirit — pure synthetic, extends Test 2 step 1's Python harness, no phone
needed; Monte Carlo, 1000+ trials per chain length (N = 2 through 6). Error model per hop: a
device-bias draw (from a cross-device bias distribution — a placeholder range until at least a
second device's data exists) plus a noise draw whose variance follows the
interference-vs-hop-position schedule from Test 2 step 3.

**What this answers:** Whether raw-stem forwarding plus the measured per-hop accuracy is
sufficient on its own, or whether a per-device bias calibration (e.g. a one-time on-device
self-check) and/or an explicit mid-chain re-alignment against the original reference is needed.

**Pass/fail threshold:** The 95th-percentile max pairwise offset across simulated chains must stay
**≤15ms at N=4 hops** (the same top-level ceiling as the final acceptance bar; N=4 treated as the
realistic typical chain length). N=6 is tracked as a stress case, not a hard gate. Exceeding 15ms
at N=4 fails this test and means a stricter per-hop accuracy requirement, a bias-calibration step,
or a mid-chain re-alignment step is needed.

**Confidence:** High confidence in the no-chaining argument itself — it is arithmetic on the
design's own alignment topology, not simulation. The open empirical inputs are the cross-device
bias distribution and the interference-vs-position variance, so **sequencing is unchanged: run
last of the four** — it consumes Test 1a's, Test 2's, and step 3's outputs.

**First run (2026-07-08, `analysis/scripts/run_multihop_simulation.py` +
`overdub_analysis/multihop.py`, 8 pytest cases; 20 000 trials/point).** Test 2's and step 3's
measured outputs existed, so the simulation ran ahead of Test 1a with the one missing input — the
cross-device bias distribution — swept as a requirement rather than assumed. Three results:

1. **Noise is a non-issue, and the no-chaining arithmetic holds numerically.** With the measured
   per-hop error std (0.31 ms, Session A) and a flat interference schedule (the vocal study:
   uncorrelated in-band interference does not move the anchored offset), the 95th-percentile max
   pairwise offset at N=4 is **1.13 ms** with zero cross-device bias — 7% of the ceiling — and
   nearly flat in chain length (1.26 ms at N=6).
2. **The ceiling is consumed almost entirely by cross-device bias.** Under a uniform placeholder
   distribution the N=4 gate holds through a bias half-range of **±8.25 ms** and fails at
   ±8.5 ms. This converts the unmeasured distribution into a requirement: per-device systematic
   biases must agree within ~±8 ms for no-calibration multi-hop to hold; a moto-g(20)-class
   ~100 ms bias fails outright, so heterogeneous chains need the per-device calibration/self-check
   the design already contemplates. This ±8 ms is the number the cross-device follow-up
   (Test 1a on a second device) gets judged against.
3. **The headphone/timestamp mechanism needs median-of-5 reads at minimum — and that pass is a
   knife-edge, not a comfortable one.** These are binomials, not simulation results: at the
   Session-A-observed 1-in-9 outlier rate (±39.6 ms displacement), a single read fails the gate
   (P(≥1 bad track of 4) = 1−(8/9)⁴ ≈ 38%; p95 ≈ 41 ms) and so does median-of-3 (per-track
   outlier survival 3p²(1−p)+p³ ≈ 3.4% → ~13% of N=4 chains affected); median-of-5 brings the
   chain rate to **~4.5% — under the gate's 5% by half a percentage point**, on a rate estimated
   from ONE observation (the sim's 1.3 ms cell hides this cliff). So the honest product guidance
   is median-of-5 *plus* an actual outlier-rate measurement (folded into the interim
   timestamp-variance plan under Test 1a), or residual-based outlier rejection instead of a
   fixed read count. At a true rate of 1/20, median-of-3 suffices.

**Verdict: conditional PASS.** The 15 ms gate holds at N=4 under the measured noise for either
mechanism, *conditional on* (a) cross-device bias differences staying within ~±8 ms — now a
stated requirement on unmeasured hardware, not an assumption — and (b) the timestamp mechanism
taking ≥5 reads per session with a median (or equivalent outlier rejection). Once a second
device's bias is measured, the bias gate is a **subtraction** (|b_i − b_j| against the budget),
not a re-simulation. **Update (2026-07-08, item 13 (b) batch):** condition (b) is now partly
measured and needs sharpening. A 43-capture multi-read batch (`test2-sweep-results.md`
"Multi-read timestamp batch") confirmed median-of-k recovers the true offset on the *isolated-
glitch* class (1/43 runs: a single/few-read timestamp glitch the median ignored) — so median-of-5
is validated for that class. But the same batch produced 1/43 runs of a **session-level desync**
the median *cannot* fix (the input clock was offset ~+35 ms for the whole session, the audio
itself misaligned 78.67 ms, the median wrong too, and it was silent to XRun/dropped/route gates
— only the click caught it). So median-of-5 is **not a blanket fix**: it must be paired with a
per-capture rejection/consistency gate (the click-anchored alignment gate on the speaker route;
an equivalent the rig validates on the headphone route). The binomial knife-edge in point 3
assumed the outlier was a single-read glitch; 13 (b) measured that ~half (1 of 2) of the
anomalies were a different, median-unfixable class, so the chain-failure rate the binomial
computes is an underestimate unless the per-capture gate removes the session-level class upstream
of the chain — which the click gate does on the speaker route. The headphone route has no click,
so the rig's honesty validation remains the instrument that decides whether the session-level
class occurs there.

**Assessment reconciliation (2026-07-08, `test3-monte-carlo-assessment.md`).** All three headline
numbers are closed-form, and the simulation reproduces them exactly: the noise result is the
range order statistic (95th percentile of the range of 4 iid normals ≈ 3.63σ = 1.13 ms at
σ = 0.31), the critical bias half-range is the uniform-range statistic inverted
(15 ms / 1.80 ≈ 8.3 ms, matching the scan's 8.25–8.50 bracket), and the timestamp results are
the binomials in point 3. `tests/test_multihop.py` asserts the simulation against those same
closed forms, so the two agree by construction. **The Test 3 verdict therefore rests on the
arithmetic; the Monte Carlo is demoted to a cross-check, held in reserve for the one case that
would turn genuinely non-analytic (mixed mechanisms per hop — bleed on some devices, timestamps
on others — with correlated failure modes).** One modeling caveat recorded: the flat interference
schedule extrapolates the single-vocal injection result to the k−1 *stacked* stems hop k would
actually hear — the same interference class (tempo-correlated, waveform-uncorrelated), but an
inference, not a measurement; if it ever needs closing, a stacked-stem variant of
`run_vocal_injection.py` measures the actual quantity for less effort than any modeling.

## Explicitly out of scope for this prototype

- Lead-in / count-in UX
- Echo cancellation (NLMS or `AcousticEchoCanceler`) — deferred pending Test 2 results
- Sharing/forwarding flow
- Pre-roll buffer sizing
- Onset detection
- Forced-speaker calibration chirp / adaptive hybrid routing (headphone fallback) — deferred pending Test 1a's result
- Explicit re-alignment/correction against the original reference mid-chain (multi-hop drift fallback) — deferred pending Test 3's result (first run 2026-07-08: needed only if cross-device biases exceed ~±8 ms — see Test 3's verdict)

None of these matter if Test 1, Test 1a, Test 2, or Test 3 fails, and building them now would be scope creep against the design doc's own stated priorities.

## Realistic timeline

A few days each for Test 1 and Test 2, for someone comfortable with Kotlin/NDK and basic Python signal processing. Test 1a adds relatively little on top of Test 1 since it reuses the same rig — mostly just logging and comparing an extra number per run. Test 3 is a half-day to a day once Test 1a/Test 2 produce real error data to drive it (it's pure Python, no device time needed). Not a confident estimate — I don't know your familiarity with Oboe specifically or whether device access is immediately available, and haven't seen any of these tests run to calibrate against.
