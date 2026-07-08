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
   must be re-measured against the click before this budget is trusted.

## Test 1 — Latency harness (continuous-buffer stability)

**Question:** Does a single continuous audio buffer (lead-in + overdub target) preserve a stable, correctly-measured round-trip offset, or does a scheduling seam introduce silent error?

**Setup:** One Android device (any available — the goal is validating your implementation's behavior, not benchmarking a specific device against a published spec number, since no authoritative Pixel 10 latency figure exists anyway). Build the continuous-buffer capture/playback path using Oboe with `PerformanceMode::LowLatency` and `SharingMode::Exclusive` (per `developer.android.com/games/sdk/oboe/low-latency-audio`).

**Hardware status (2026-07-05):** loopback rig ordered — a PassMark Audio Loopback Plug (TRRS)
plus a Movo UCMA-2 USB-C-to-TRRS adapter, needed since the target device (Pixel 10) has no 3.5mm
jack. This is a fully electrical loopback path (phone USB-C → UCMA-2 → PassMark plug), so no
physical clap/acoustic signal is needed for this test — the test signal is generated and read back
over the wired connection, primarily by the harness's own capture path with OboeTester as a
cross-check (see Method below). Test 2's acoustic bleed test is unaffected by this and still
uses the phone's built-in speaker/mic directly.

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

**Status update (2026-07-08):** partially de-risked ahead of the rig. The Pixel 10 timestamp study
(`test2-sweep-results.md`, "Stream-timestamp decomposition confirmed") already shows `getTimestamp`
succeeding on both streams and tracking per-session start jitter (subtracting it collapses the
run-to-run offset std 13.4→5.5ms) — the mechanism is *available and self-consistent* on this
device. What the rig still owes this test is the *honesty* check: that the reported values match
physical truth (the moto g(20) failure class) on the route the rig measures. Note the 5.5ms
residual std brushes this test's ≤5ms allowance as a raw number; how much of it is quantization
vs. real error is decomposed by the in-basis calibration click (Test 2's ground-truth correction).

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

**Implementation status (2026-07-05):** step 1's Python GCC-PHAT is implemented and its
synthetic-validation gate passes (`analysis/src/overdub_analysis/gcc_phat.py` +
`synth.py`, 14 pytest cases green). At high/clean SNR (30 dB ≥ the 20 dB bar) the recovered
offset is within ±1 sample of the injected delay and PSR ≥10 dB; the 6 dB PSR floor for a
broadband periodic click train sits at ≈ −30 dB SNR (run
`analysis/scripts/sweep_snr_floor.py` to reproduce) — far below any realistic phone-bleed SNR
for that signal class. (Caveat, added 2026-07-08: that floor did *not* transfer to the real
signal — the real sweep failed 0/36 full-band — and it has not been re-measured with the
band-limited pipeline, the real beatbox reference, or vocal interference present; re-measuring it
is folded into step 3 below.) The synthetic fixtures double as the
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
independent of the correlator) measured the true baseline offset at -80.98 ms; GCC-PHAT reported
+107.12 ms, ~188 ms off — essentially one reference beat period. So PSR ≥ 6 dB + a (0, 300 ms)
positivity lag window is *not* a sufficient alignment gate: both bless the alias (the true offset
is negative in the harness basis, so the "plausible positive" window pointed the wrong way, and
the beat-period peak is a real sharp feature of the reference's autocorrelation). The honest gate
is `|gcc_phat_offset - click_offset| ≤ 2 ms` per capture, with the lag window admitting negative
offsets (or re-basis by trimming to beatbox-only content so the positivity prior holds). Test 2
step 2 is **not passed**; the 36-cell sweep must be re-run against the click-bearing reference and
re-gated. See `test2-sweep-results.md` "Calibration click cross-check."**

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
Remaining: re-run the full 36-cell sweep against the click-bearing reference and re-gate on
`|gcc_phat_offset - click_offset| ≤ 2ms` (admitting negative offsets), not PSR + a positivity
window.

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
the Pixel has not passed — the calibration-click cross-check showed the prior "35/36 clear 6 dB"
was 35/36 locking onto a beat-period alias, not the true alignment (`test2-sweep-results.md`). So
the favorable-case existence proof is not yet established; the re-gated sweep (admitting negative
offsets, judged against the click) is what would establish it.**

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

## Test 3 (proposed; revised 2026-07-08) — Multi-hop alignment error simulation

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
