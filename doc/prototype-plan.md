# Overdub App — Prototype Validation Plan

## Purpose

Not a product prototype. Narrow tests targeting the assumptions the entire architecture depends
on. If one fails, the "accept mic bleed, no calibration, no USB-C requirement" design direction
needs to be reconsidered before any further engineering — UI, sharing flow, echo cancellation,
lead-in UX are all downstream of these questions and out of scope here.

Two tests were load-bearing at the start (Tests 1 and 2 below). The 2026-07-05 documentation
review added two more: **Test 1a** (headphone monitoring removes the acoustic path Test 2 depends
on, so the most promising fix — trusting AAudio/Oboe's own reported latency — needs its own
validation; see design-summary.md "Headphone monitoring gap and alignment alternatives") and
**Test 3** (whether per-hop alignment error grows across a multi-hop forwarding chain; see
design-summary.md "Chain-of-forwarding alignment error").

## Status at a glance (2026-07-08)

| Test | Verdict | What remains |
|---|---|---|
| 1 — continuous-buffer stability | **Blocked on the loopback rig** (delivery delayed) | Run when the rig arrives |
| 1a — timestamp honesty/accuracy | **Partially de-risked** (variance + outlier classes measured on both routes; interim plan complete 2026-07-09) | Honesty check — most critically on the headphone route — needs the rig |
| 2 — bleed alignment | **Pass bar met** — Session A 11/11 under the click-anchored gate | Session B (full 36-cell map) is confirmatory-only |
| 3 — multi-hop error | **Conditional PASS** (closed-form arithmetic) | Conditions: cross-device bias ≤ ~±8 ms (needs device #2); median-of-5 reads + a per-capture rejection gate |

Remaining work in priority order (updated 2026-07-09 — the bleed-mix listening test is **done**:
echo cancellation is v1 work, suppression target ~12 dB, and the **NLMS feasibility prototype now
clears that target on real captures** (bleed-only 18.4/18.3 dB, vocal-present 14.1 dB in-band;
see design-summary.md "Echo cancellation for v1"). The headset-gated items are also **done**: the
Tier-2 override test **passed**, so `setDeviceId()` can demote an active USB headset and the
forced-speaker-chirp direction is viable on this device, and the 13(c) headset-route batch is
measured — see `test2-sweep-results.md` "Headset-route session". **The calibration-signal
bake-off is fully closed (2026-07-09): the riser on-device capture PASSES** — quality 17.8 dB
(bar ≥ 10), onset recovery 0.00 ms vs the click (bar ≤ 2 ms), sample-exact agreement between the
two independent instruments; see `test2-sweep-results.md` "Riser on-device capture". The asset
chain and pass-bar judge are `mix_calibration_signal.py` / `detect_calibration_signal.py` +
`verify_apk_asset.py`, with the riser mixed at `SELECTED_MIX_ONSET_S` (0.550 s) inside the click
lead-in — see `reference_track_README.md` for the 3-step generation chain and pairing rule. The
port implements the riser waveform + the anchored ±90 ms window + the |gcc − signal| ≤ 2 ms
re-take gate):

1. **Test 2 Session B** confirmatory re-capture (device time, no code work — the riser-bearing
   asset is already installed, and Session B captures made with it carry both instruments).
2. **Tests 1 + 1a when the rig arrives** — the headphone-route honesty check is the most
   consequential remaining measurement (see Test 1a).
3. **Cross-device work** when a second device exists: bias subtraction (Test 3's ±8 ms gate) + the
   on-device two-gain AGC tone probe.

Parallel (unblocked, no device needed): the remaining echo-cancellation work — audition the real
NLMS residuals against the listening test's simulated ec12 rung (renders in
`analysis/echo_cancel_eval/`, gitignored; regenerate with
`analysis/scripts/run_echo_cancel_eval.py`).

## Why these two, and not the others

The design doc lists several open items: pre-roll buffer sizing, `AcousticEchoCanceler` quality, onset detection reliability, USB Audio Class consistency. All of these are either explicitly deferred already or are optimizations layered on top of alignment working at all. Two items are load-bearing:

1. **Continuous-buffer latency stability** — the doc flags that lead-in and overdub target must be one continuous audio stream, not two sequentially-scheduled players, or "a scheduling seam would silently invalidate the measured offset." Unverified on real devices.
2. **Cross-correlation alignment under real bleed conditions** — GCC-PHAT (Knapp & Carter, *IEEE Trans. Acoustics, Speech, and Signal Processing*, 1976) is peer-reviewed and well-established as a time-delay-estimation method in principle. What's unverified is whether it locks onto a clean peak given actual phone-speaker-to-phone-mic bleed SNR, not whether the math is sound.

If (1) fails, your measured latency offset is meaningless regardless of alignment method. If (2) fails, the no-calibration bleed-based approach doesn't hold and you're back to reconsidering USB-C or an explicit calibration step. Everything else in the design doc is contingent on these two holding up.

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
   | Test 2 — recovered-offset accuracy | within ±2ms of in-basis ground truth | The per-hop alignment-accuracy allowance the multi-hop model consumes. |
   | Test 3 — multi-hop misalignment | 95th-percentile max pairwise offset ≤15ms at N=4 hops | The same top-level ceiling applied end-to-end, not an independent allowance (see point 4). Per-hop errors don't sum under align-to-original — see Test 3's model. |

3. **Caveat:** these numbers are literature-grounded and defensible as genuinely decided in
   advance, but they weren't validated against phone-speaker-to-phone-mic bleed specifically. If
   Test 2 step 1 (synthetic, no device involved) shows the algorithm structurally cannot reach the
   PSR floor even at high SNR, that's an *achievability* finding, not grounds to quietly lower the
   *acceptability* bar — it would mean reconsidering the design direction, per this doc's stated
   purpose, not relaxing the threshold post-hoc.

4. **Budget reconciliation against measured data (2026-07-08, resolved).** These rows are not
   independent allowances that sum to 15ms — Test 3's 15ms is the same top-level ceiling applied
   end-to-end, consuming the per-hop errors Tests 1/1a/2 bound. An early scare — a 5.5ms
   per-measurement residual std in the Pixel 10 timestamp study, which (if real alignment error)
   would have consumed the entire ceiling at a single hop — resolved benign: it was harness
   start-jitter plus quantization around a correlator *alias* peak, not product-path error. The
   click-anchored Session A measurement (`test2-sweep-results.md` "Session A re-capture") puts the
   real per-session correlator error at **mean −1.18 ms, std 0.25 ms, max 1.35 ms — 9/9 inside
   ±2 ms**; the stable ~−1.2 ms bias is calibratable, and the noise consumes almost none of the
   ±2 ms per-hop allowance. One budget input cut the other way: **1 of 9 sessions showed a ~40 ms
   `getTimestamp` outlier** on the best-case device, so Test 1a's ≤5 ms trust bar cannot be met by
   a single timestamp read. Any product mechanism using `getTimestamp` needs repeated reads *plus*
   a per-capture rejection gate — the follow-up multi-read batch found a session-level desync
   class a median cannot fix (see Test 1a's interim plan, step 2) — and the loopback-rig honesty
   check remains load-bearing.

## Test 1 — Latency harness (continuous-buffer stability)

**Question:** Does a single continuous audio buffer (lead-in + overdub target) preserve a stable, correctly-measured round-trip offset, or does a scheduling seam introduce silent error?

**Setup:** One Android device (any available — the goal is validating your implementation's behavior, not benchmarking a specific device against a published spec number, since no authoritative Pixel 10 latency figure exists anyway). Build the continuous-buffer capture/playback path using Oboe with `PerformanceMode::LowLatency` and `SharingMode::Exclusive` (per `developer.android.com/games/sdk/oboe/low-latency-audio`).

**Hardware status:** loopback rig ordered 2026-07-05 — a PassMark Audio Loopback Plug (TRRS) plus
a Movo UCMA-2 USB-C-to-TRRS adapter (the Pixel 10 has no 3.5mm jack). This is a fully electrical
loopback path (phone USB-C → UCMA-2 → PassMark plug): the test signal is generated and read back
over the wired connection, no acoustic signal involved. Test 2's acoustic bleed test is unaffected
and uses the phone's built-in speaker/mic directly. **Delivery is delayed (as of 2026-07-08);**
the rig-independent parts of the timestamp question were pulled forward into Test 1a's "Interim
timestamp-variance plan" below.

**Method:** drive a known click/test signal through the electrical loopback, **through the
harness's own continuous-buffer capture path — not OboeTester alone.** OboeTester measures the
*device's* round-trip latency, but it cannot test this implementation's scheduling-seam
hypothesis, and its number lives in a different measurement basis than the harness's captures (see
Test 2's ground-truth correction), so it serves as a sanity cross-check, not the primary
instrument. Repeat ~20 times. Check `AAudioStream_getXRunCount()` for buffer underruns on each
run. Confirm the measured offset is stable across repetitions and doesn't drift when the lead-in
and target recording are scheduled as one continuous stream vs. (as a negative control) two
sequentially-scheduled players. The electrical path is deliberately the instrument here rather
than an acoustic click: no room noise or reverb, so rep-to-rep variance reflects scheduling
behavior rather than acoustics — which matters for a test whose negative control must *detectably*
fail.

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

**Question:** Does AAudio/Oboe's own reported stream latency (timestamps against the shared audio
clock) match the ground-truth round-trip latency measured by the physical loopback, closely enough
to use directly as the alignment offset — with no dependence on any acoustic bleed signal?

**Setup:** The same fully electrical loopback rig as Test 1 — no new hardware. Log
`AAudioStream_getTimestamp()` (or Oboe's equivalent) alongside the ground-truth offset already
being measured for Test 1, across whatever output routes are available (built-in speaker, wired
headset, Bluetooth if on hand).

**Method:** For each of the ~20 repetitions Test 1 already runs, record both numbers side by side —
the loopback-measured ground truth and AAudio's self-reported latency. Compare across routes: does
the discrepancy (if any) stay consistent, or does it change meaningfully between speaker and
headphone output? Repeat on a second device if available, since the design doc's one documented
counter-example (moto g(20)) was device-specific, not universal. **Take ~10 timestamp reads per
repetition, not one** — Session A observed a 1-in-9 single-read ~40 ms outlier, so single reads
are untrustworthy, and the rep batch doubles as an outlier-rate measurement.

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

**Status (2026-07-08) — partially de-risked ahead of the rig.** What is established, all on the
Pixel 10 (full write-ups in `test2-sweep-results.md`):

- **The mechanism is available and self-consistent.** `getTimestamp` succeeds on both streams and
  tracks per-session start jitter — subtracting it collapses the run-to-run offset std
  13.4 → 5.5 ms ("Stream-timestamp decomposition confirmed").
- **Timestamp anomalies come in two classes, and a median only fixes one** ("Multi-read timestamp
  batch," 43 captures × 11 reads): an *isolated-glitch* class (median-of-k recovers the true
  offset) and a *session-level desync* class — the input clock ~+35 ms off for the whole session,
  the audio itself misaligned 78.67 ms, the median wrong too, silent to XRun/dropped/route gates,
  caught only by the independent calibration click. Observed rates: 2/43 anomalies, 1/43
  session-level (thin estimates). Read-noise std over clean runs ~0.4 ms; the stream−click basis
  residual is a stable ~−15.1 ms on clean runs.
- **What the rig still owes this test is honesty on the headphone route:** the click is a rig-free
  honesty check on the speaker route only. A headphone session (no bleed, no click) would leave
  the session-level desync class *silent* — that concrete failure is what the rig's honesty
  validation must de-risk before the product trusts `getTimestamp` blind on that route (the
  moto g(20) failure class).

**Confidence:** genuinely open. The original rejection of this approach rested on a single
anecdotal moto g(20) report; the Pixel data since shows the mechanism working but with a measured
fat tail that mandates repeated reads plus a rejection gate.

**Interim timestamp-variance plan (2026-07-08, rig delayed).** The rig is irreplaceable only for
headphone-route *honesty* and Test 1's seam check; the timestamp *variance* questions were
testable without it. Three steps:

1. **Decompose the existing Session A outlier from its sidecars (zero device time)** — **done;
   inconclusive by under-determination.** No single-read referent discriminates a 40 ms anomaly:
   `frame_delta`'s +40 ms deviation matches the offset error but its own benign cluster spreads
   ±24 ms (start jitter), and the wall anchors spread ±40 ms. Single-read sidecars under-determine
   the culprit, so no cheap single-read sanity check (e.g. framePosition-vs-length) is validated.
   Write-up: `test2-sweep-results.md` "Session A timestamp-outlier decomposition."
2. **Multi-read logging + unattended batch (device, no rig)** — **done.** ~11 `getTimestamp`
   reads spread across each session, logged in the sidecar; 43 baseline captures. Results are the
   two-class finding summarized in the Status above: median-of-k validated for isolated glitches,
   *not* a blanket remedy; the session-level class needs an independent per-capture anchor (a
   uniform whole-session shift is invisible even to a line-fit consistency check on the reads).
   Write-up: `test2-sweep-results.md` "Multi-read timestamp batch."
3. **Headset-route variance batch — done (2026-07-09).** 41 captures through a USB-C headset
   (output) + built-in mic (input), the product headphone-session stream shape, over wireless
   ADB: **41/41 clean, 0/447 off-line reads** — no isolated-glitch anomaly on this route at this
   sample size; start-jitter std 22.9 ms (~1.7× the speaker route's 13.4 ms). By construction
   this route has no acoustic anchor, so the session-level desync class and honesty remain the
   rig's job — unchanged. The same session also passed the Tier-2 headset-override test, so the
   forced-speaker-chirp fallback is actually buildable on this device if honesty fails here.
   Write-up: `test2-sweep-results.md` "Headset-route session."

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

**Setup (single device):** The actual bleed mechanism in the design is one phone playing back the beatbox track through its own speaker while simultaneously recording the overdub through its own mic — playback and capture on the *same* device. One phone is sufficient and correctly reproduces the mechanism being tested. A second phone would only be useful later, for checking cross-device variance in speaker/mic hardware and AGC behavior — a real but lower-priority question, not what this test is scoped to answer.

**Three steps, all now run** (implementation detail and work log: `test2-step2-plan.md`; full
measurements: `test2-sweep-results.md`):

1. **Synthetic validation (Python, no device) — done.** `analysis/src/overdub_analysis/gcc_phat.py`
   + `synth.py` pass the implementation-correctness gate: at clean SNR the recovered offset is
   within ±1 sample of the injected delay with PSR ≥ 10 dB. The synthetic fixtures double as
   port-correctness regression tests for the eventual Kotlin/C++ port. An early click-train SNR
   floor (≈ −30 dB) did *not* transfer to the real signal; the floor was re-measured with the
   production pipeline (real click-bearing reference, band-limited 500–4000 Hz, click-anchored
   window, ±2 ms gate — `analysis/scripts/sweep_snr_floor_real_reference.py`): **−27..−30 dB
   in-band SNR, set entirely by calibration-click burial** — the anchored correlator posts 0.00 ms
   error at every SNR where the click anchors.
2. **Real-bleed sweep on the Pixel 10 — done; pass bar met after a major correction.** The 36-cell
   sweep (volume × distance × orientation × obstruction) captured clean, but the road to a
   trustworthy alignment had two failures that reshaped the method:
   - *Full-band GCC-PHAT failed outright* (0/36 ≥ 6 dB PSR): PHAT over-weights noise-dominated HF
     and bass-rolled-off LF. Band-limiting to 500–4000 Hz recovered the peak broadly (35/36).
   - *The band-limited offsets were aliases.* The in-basis calibration click (an independent
     matched-filter instrument — see "Ground-truth correction" below) showed the whole
     +61..+151 ms offset family, "confident" PSR included, was a **~+187 ms beat-period alias** of
     negative true offsets (true baseline −79.62 ms vs. GCC-PHAT +107.12 ms). PSR ≥ 6 dB plus a
     positive-offset lag window both blessed the alias; the alias peak is genuinely ~12 dB larger
     than the true peak, so no wide lag window can reject it. The honest gate is a
     **click-anchored ±90 ms window (narrower than half the beat period, so a one-beat alias is
     excluded by construction) plus `|gcc_phat_offset − click_offset| ≤ 2 ms` per capture**, with
     PSR demoted to a diagnostic. A stream-timestamp-anchored window recovered the same true
     offset, validating the product-shaped variant (the product has no click, but has
     `getTimestamp`). This episode is CLAUDE.md trap (d): an estimator's own quality metric cannot
     catch failures the estimator's assumptions cause.
   - *Re-captured and re-gated (Session A): 11/11 PASS* — the baseline gate cell × 9 repeats
     (correlator error mean −1.18 ms, std 0.25 ms, max 1.35 ms) plus the min-bleed and HF-rattle
     extreme cells (−1.21 / −0.46 ms). **The step-2 pass bar — the baseline realistic condition
     within ±2 ms of in-basis ground truth — is met.** Session B (the remaining arrangements → the
     full 36-cell alignment/UX-constraint map) is confirmatory-only, run when convenient.
3. **Vocal-interference injection (pure Python) — done.** Production must find the bleed
   underneath a close-mic vocal sitting exactly in the 500–4000 Hz analysis band. The realistic
   vocal-to-bleed ratio was pinned *in advance* at **−12.2 dB** (two in-basis close-mic takes agree
   exactly — the vocal lands *below* the bleed, the opposite of the "loud vocal" assumption).
   Result: the alignment is essentially **immune** — the click-anchored offset is unchanged by
   even 1 sample from +0 to +24 dB in-band ratio; the failure mode at +24–30 dB is the vocal
   burying the *calibration click* (anchor lost), not pulling the alignment — ~36 dB of margin
   above the realistic ratio. Cross-take robust.

**What this answers:** Whether the design's bleed-based alignment holds up against actual
phone-mic-quality bleed. It does on this device — but the alias finding weakened the design doc's
"no calibration step needed" claim: an independent anchor (calibration click, or per-capture
timestamp anchor plus a rejection gate) is required to *validate* the correlation, not just
compute it. See design-summary.md "Timing correction strategy" point 5 and the open
beat-period-aliasing product question there.

**Pass/fail threshold:**
- **Step 1 (synthetic, implementation-correctness gate):** at high/clean SNR (e.g. ≥20dB), recovered
  offset must match the injected delay within **±1 sample** and peak-to-sidelobe ratio (PSR) must be
  **≥10dB** — this confirms the code is correct before using it to map anything. Sweep noise level
  downward and record the SNR at which PSR crosses below **6dB** (the minimum-acceptable floor,
  borrowed from standard TDOA/GCC-PHAT practice, not invented from this dataset) — that crossing
  point is "the SNR floor," an output of this test, not a threshold to hit.
- **Step 2 (real bleed):** counts as a usable lock in a given condition (volume/orientation/distance)
  if **PSR ≥ 6dB and recovered offset is within ±2ms** of the in-basis calibration-click ground
  truth (see the ground-truth correction below). **Overall Test 2 pass bar:** the baseline
  realistic condition (comfortable conversational playback volume, phone within arm's reach, no
  obstruction) must clear this bar. Edge conditions (quiet volume, phone in a pocket) failing is
  acceptable and becomes a documented UX constraint (e.g., app enforces a minimum playback volume)
  rather than a test failure. (Post-alias amendment: PSR is diagnostic-only in the final gate —
  the true acoustic peak is a multipath cluster that can read ~0 dB PSR even when correct; the
  binding criterion is the click-anchored ±2 ms.)

**Ground-truth correction (2026-07-08).** This bar originally read "within ±2ms of the ground truth
already established by Test 1's loopback measurement." That comparison is invalid, for two
independent reasons:

- **Route mismatch:** the loopback rig is electrical via the USB-C adapter, so it measures the
  wired route's round trip — not the builtin-speaker→builtin-mic path Test 2's bleed uses.
  Per-route latencies differ; that is Test 1a's own premise.
- **Measurement-basis mismatch:** the harness's GCC-PHAT offset carries a large fixed
  harness-specific constant (the captured WAV's sample 0 is not input-stream frame 0 once the
  input-buffer sizing and startup drain gap fold in). A latency measured by another tool
  (OboeTester) in its own basis cannot be compared at ±2ms against an offset measured in the
  harness's basis. (The once-mysterious "~201 ms constant" decomposed as ~14–15 ms of genuine
  basis residual plus the ~187 ms correlator alias.)

The ground truth must be **in-basis and on-route**: a short high-SNR calibration click embedded at
a known sample position in the bundled reference track, detected in the captured WAV by a matched
filter (independent of the correlator being judged), judged against the GCC-PHAT offset *in the
same file*. This is built and validated (`test2-step2-plan.md` item 11): the click survived the
real speaker→mic path, exposed the alias family, and anchored the Session A pass. Test 1's
loopback rig keeps a narrower, still-necessary role: independently verifying that `getTimestamp`
values are honest (the moto g(20) failure class) on the route it actually measures.

**Confidence:** GCC-PHAT as a time-delay estimation method is well-supported by peer-reviewed
literature (Knapp & Carter 1976). Its device-specific applicability on the Pixel 10 is now
measured (pass, with the anchor requirement above); other devices are the open question — see
below.

**Cross-device generalization.** Test 2's on-device numbers are gathered on a single Pixel 10.
Two halves generalize differently:

- **The algorithm and the pass/fail *criteria* generalize** (device-independent). GCC-PHAT's
  correctness, the ±1-sample synthetic accuracy, and the PSR floor come from the synthetic step 1
  with no device in the loop. The PSR ≥ 6dB / offset-within-±2ms bars are borrowed from TDOA
  practice, not fit to Pixel data, and the ±2ms bar is measured against *that device's own*
  in-basis ground truth (the calibration click), so the criterion is self-relative and transfers
  even though the absolute latency does not.
- **Whether real bleed clears that floor does *not* generalize** — an empirical per-device question
  dominated by (a) speaker/mic hardware SNR (loudness, sensitivity, chassis geometry — the Pixel 10's
  baseline capture RMS is a Pixel-10 number) and, the bigger wildcard, (b) OEM mic DSP. The harness
  forces `InputPreset::VoiceRecognition` to suppress AGC/NS, but that's a *request* OEMs honor
  inconsistently; residual AGC in particular auto-compensates a quiet bleed and flattens exactly the
  volume/distance SNR gradient this sweep exists to map. Preset honesty is **not established even
  on the Pixel**: sweep finding 2 in `test2-sweep-results.md` shows gain-ratio compression despite
  `VoiceRecognition` (device-level exponent 0.85; the input-AGC vs output-amp split needs the
  on-device two-gain tone probe below). Secondary per-device unknowns: whether LowLatency/Exclusive
  is granted at all, the native sample rate, and route-forcing quirks.

**Direction of the bias:** the Pixel 10 is close to a *best case* for this approach (clean
near-AOSP audio stack, well-behaved AAudio, good transducers). The Session A pass is a
favorable-case existence proof — "the approach and the code are sound, and it clears the bar on a
good device" — and generalizing downward to budget or heavy-OEM-skin hardware should be expected
to get *worse*, not better. (Had it *failed* on Pixel, that would have been near-fatal for the
bleed approach outright.) Adjacent evidence of device variance: the moto g(20) platform-latency
counter-example (Test 1a) and the Pixel 8/9 200–700ms A/V-sync reports.

**What establishing generalization would take:** re-run the same harness on a deliberate spread (a
budget device, a heavy-skin device such as Samsung, a mid-tier), logging per device whether
LowLatency/Exclusive is granted and at what rate/burst, the resulting bleed SNR vs. the Pixel
baseline, and — most sharply — whether forcing VoiceRecognition actually disabled AGC (directly
testable: play a fixed tone at two known gains and check whether captured RMS preserves the gain
ratio or compresses it; compression = AGC still active = SNR-mapping compromised on that device).
The harness's metadata already logs `device_model`, `sample_rate`, `input_preset`, `xrun_count`,
and `stream_volume_index`, so it can be pointed at a second device with no code change.

**Design consequence:** because generalization is gated on OEM behavior the app doesn't control, the
product likely can't assume bleed-based alignment works on every device — it may need a device
allowlist or a runtime bleed-SNR self-check. This is a large part of why Test 1a (trusting AAudio's
self-reported latency, a more nearly device-agnostic mechanism) exists, and why the design contemplates
per-route/per-device mechanism selection rather than one path for all hardware.

## Test 3 — Multi-hop alignment error (conditional PASS, 2026-07-08)

**Model correction (2026-07-08):** as originally framed ("do independent per-hop errors compound
into cumulative drift"), this test modeled a mechanism the design has already eliminated. Under
the raw-stem decision, every hop aligns against the *original* reference, so per-hop errors do not
chain: track k's timing error vs. the shared reference is an independent draw e_k, and the
misalignment between any two tracks i and j is |e_i − e_j| — the difference of two independent
draws, essentially flat in chain length (a random walk arises only if each hop aligns to the
*previous* track, which the raw-stem decision forbids). What genuinely can worsen with chain
length, and what the revised test models instead:

1. **Per-device systematic bias.** Each device's alignment mechanism can carry a fixed bias b_k
   (the moto g(20) ~100ms timestamp discrepancy is this class). Pairwise misalignment is
   (b_i − b_j) + (e_i − e_j), and between heterogeneous devices the bias *differences* — which no
   chain-length statistics average away — are the realistic dominant term.
2. **Interference growth.** Hop k correlates against the original stem through the bleed of the
   k−1 *other* stems plus the performer's own vocal — per-hop error variance could grow with
   position in the chain. Magnitude comes from Test 2 step 3, not an assumed constant.

**Question:** With per-device biases and position-dependent interference modeled, does the
95th-percentile **max pairwise** offset between any two tracks stay ≤15ms at N=4?

**Results (2026-07-08; `analysis/scripts/run_multihop_simulation.py` +
`overdub_analysis/multihop.py`, with the cross-device bias distribution — the one unmeasured
input — swept as a requirement rather than assumed):**

1. **Noise is a non-issue.** With the measured per-hop error std (0.31 ms, Session A) and a flat
   interference schedule (the vocal study: uncorrelated in-band interference does not move the
   anchored offset), the 95th-percentile max pairwise offset at N=4 is **1.13 ms** with zero
   cross-device bias — 7% of the ceiling — and nearly flat in chain length (1.26 ms at N=6).
2. **The ceiling is consumed almost entirely by cross-device bias.** The N=4 gate holds through a
   uniform bias half-range of ±8.25 ms and fails at ±8.5 ms. This converts the unmeasured
   distribution into a requirement: **per-device systematic biases must agree within ~±8 ms** for
   no-calibration multi-hop to hold; a moto-g(20)-class ~100 ms bias fails outright, so
   heterogeneous chains need the per-device calibration/self-check the design already
   contemplates. Once a second device's bias is measured, this gate is a **subtraction**
   (|b_i − b_j| against the budget), not a re-simulation.
3. **The headphone/timestamp mechanism needs median-of-5 reads at minimum — a knife-edge pass.**
   Binomials, not simulation: at the Session-A-observed 1-in-9 outlier rate (~40 ms displacement),
   a single read fails the gate (P(≥1 bad track of 4) ≈ 38%), median-of-3 fails (~13% of chains),
   median-of-5 clears at ~4.5% vs. the gate's 5% — by half a percentage point, on a rate estimated
   from one observation. The subsequent multi-read batch (Test 1a interim step 2) sharpened this:
   median-of-k is validated for the *isolated-glitch* class only; a **session-level desync** class
   exists that the median cannot fix, so median-of-5 **must be paired with a per-capture
   rejection/consistency gate** (the click gate on the speaker route; whatever the rig validates
   on the headphone route) or the binomial chain-failure rate is an underestimate.

**Verdict: conditional PASS.** The 15 ms gate holds at N=4 under the measured noise for either
mechanism, *conditional on* (a) cross-device bias differences staying within ~±8 ms — a stated
requirement on unmeasured hardware — and (b) the timestamp mechanism taking ≥5 reads per session
with a median *plus* a per-capture rejection gate.

**Assessment reconciliation (`test3-monte-carlo-assessment.md`, 2026-07-08).** All three headline
numbers are closed-form (range order statistics, an inverted uniform-range statistic, binomials),
and the simulation reproduces them exactly — `tests/test_multihop.py` asserts the simulation
against the same closed forms, so the two agree by construction. **The verdict rests on the
arithmetic; the Monte Carlo is a cross-check, held in reserve for the one case that would turn
genuinely non-analytic** (mixed mechanisms per hop — bleed on some devices, timestamps on others —
with correlated failure modes). One modeling caveat: the flat interference schedule extrapolates
the single-vocal injection result to the k−1 *stacked* stems hop k would actually hear — same
interference class, but an inference, not a measurement; if it ever needs closing, a stacked-stem
variant of `run_vocal_injection.py` measures the actual quantity cheaply.

## Explicitly out of scope for this prototype

- Lead-in / count-in UX
- Echo cancellation *on-device* (the Kotlin/C++ NLMS port, or `AcousticEchoCanceler` evaluation) —
  EC itself is decided v1 work (bleed-mix listening test, 2026-07-09) and the offline NLMS
  feasibility prototype clears the ~12 dB target (design-summary.md "Echo cancellation for v1");
  the on-device port stays out of prototype scope
- Sharing/forwarding flow
- Pre-roll buffer sizing
- Onset detection
- Forced-speaker calibration chirp / adaptive hybrid routing (headphone fallback) — deferred pending Test 1a's result
- Explicit re-alignment/correction against the original reference mid-chain (multi-hop drift fallback) — needed only if cross-device biases exceed ~±8 ms, per Test 3's verdict

None of these matter if Test 1, Test 1a, Test 2, or Test 3 fails, and building them now would be scope creep against the design doc's own stated priorities.
