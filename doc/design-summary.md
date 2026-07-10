# Collaborative Overdub App — Design Discussion Summary

## Core concept
An Android app for musical collaboration: one person records audio (e.g., beatboxing, singing), sends it by uploading to shared cloud storage and sharing the resulting link via the native OS share sheet (see "Sharing mechanism and file format" below), a second person overdubs on top (e.g., rapping, harmonized/counterpoint singing), and can forward the result further

## Prior art check
No existing app matches this exact model — record locally, share via native OS share sheet, recipient overdubs and re-shares the same way, no central server/social feed required.

- **Centralized layering apps exist** (SoundStorming, Trackd, BandLab, Soundtrap) but collaboration happens through the app's own network/cloud, not the phone's native share sheet.
- **iOS Voice Memos** added on-device layered recording (iPhone 16 Pro+, 2025) but it's local-only, no send/forward loop.
- Weak supporting evidence: a Loopy Pro forum thread shows someone explicitly wanting this exact workflow ("record my track, send to group member, they record, and so on") and being pointed to full DAW tools or manual file-passing instead.
- **Confidence: moderate that nothing like this exists** — search was not exhaustive (no full Play Store audit).

## Sharing mechanism and file format (added 2026-07-05)

**Problem:** raised in documentation review (`review-20260705-093038.md`) — messaging apps commonly
re-encode audio attachments to a lossy codec, sometimes at a reduced sample rate, which would degrade
the correlation reference GCC-PHAT alignment depends on at every hop.

**Decision: lossless format by default, distributed via a link to shared cloud storage rather than a
direct message attachment.**
- **Format:** default to an uncompressed lossless container (WAV/PCM), retaining all raw data
  bit-for-bit. This removes the lossy-transcoding risk entirely rather than just mitigating it, and
  storage cost is a non-issue given modern phone/cloud storage capacity. FLAC remains an option later
  if upload bandwidth becomes a real constraint — still lossless, smaller, but adds an encode/decode
  step — not adopted now since there's no evidence it's needed.
- **Distribution:** the app uploads the recording — per the raw-stem-forwarding decision above, all
  accumulated stems, not just the newest one — to shared cloud storage (e.g. Google Drive) and shares
  the resulting link via the native OS share sheet. The link (plain text/URL) is what passes through
  the messaging app, never the audio bytes themselves, so this sidesteps messaging apps' lossy
  audio-attachment pipelines entirely rather than hoping a chosen share target happens to preserve
  bytes.
- **Relationship to "no central server" (Prior art check, above):** this uses general-purpose cloud
  storage the user already has (their own Google Drive, etc.), not an app-specific backend or social
  feed — the differentiation from centralized layering apps (SoundStorming, Trackd, BandLab,
  Soundtrap) was about not building a proprietary collaboration network, which still holds. It does
  mean the app is no longer purely local-with-share-sheet — it now depends on the user having (and
  being signed into) a cloud storage account, and on that provider's availability.

**Open items this raises (not yet resolved):**
- Auth/integration: does the app integrate directly with a specific provider's API (e.g. Google
  Drive API, requiring sign-in) to automate upload + link creation, or rely on the OS's generic
  Storage Access Framework / share sheet and let the user manually pick a destination? The former
  guarantees losslessness but adds a real dependency and onboarding step; the latter is simpler to
  build but a user could still pick a messaging app as the destination and reintroduce transcoding
  risk. (Deferral reaffirmed 2026-07-09 — not test-gated; the SAF path's transcoding risk is the
  deciding factor to weigh at product-build time.)
- Link permissions: must ensure the uploaded file is accessible to the recipient (e.g. "anyone with
  the link can view") without exposing it to a wider unintended audience — needs a concrete
  sharing-permission default.
- Per-hop re-upload: consistent with "always forward raw stems," each hop's link should point to
  that hop's own upload of the full accumulated stem set, not the original uploader's file — so the
  chain doesn't depend on any one person's storage/link staying alive indefinitely. This costs
  bandwidth proportional to chain length — likely fine given "modern phones have a lot of storage,"
  but not yet validated against real mobile-data constraints for long chains.
- Upload latency: the sender must wait for the upload to finish before the share sheet can hand off
  a working link, unlike an instant local-file share — a real, if probably minor, UX cost compared to
  the original all-local design, not yet measured.

## Deep linking and app handoff (added 2026-07-05)

**Problem:** flagged by an external design critique (`glm-critique.txt`, since deleted after
triage) — none of the decisions above say what actually happens when a recipient taps the shared
cloud-storage link. A raw `drive.google.com/...` link isn't a URL this app can register as an App
Link handler for (Android App Links require verified ownership of the link's domain via
`assetlinks.json`; this app doesn't own Google Drive's domain), so by default the OS opens it in a
browser or the Drive app, not this app. Every other decision so far assumes the file "arrives" in
the app somehow, without saying how.

**Two distinct cases, likely needing different answers:**
1. **Recipient already has the app installed** — the common case for an established chain past the
   first hop. Doesn't need the cloud link or any deep-linking machinery at all: Android's native
   share sheet already lists any installed app declaring an `ACTION_SEND`/`ACTION_SEND_MULTIPLE`
   intent filter for the relevant MIME type as a direct share target. If User A shares straight to
   the Overdub app (rather than to a messaging app), the raw stem files transfer app-to-app with no
   intermediate cloud upload, no transcoding risk, and no link-tapping ambiguity — simpler than the
   cloud-link path for this case, and worth exposing as the preferred option in the share sheet
   whenever the target device has the app. This doesn't replace the cloud-storage decision above
   (still needed when the destination is a messaging app / unknown recipient), it's a faster path
   layered on top of it.
2. **Recipient doesn't have the app installed yet** — the cloud-link path is necessary here since
   there's no app to receive an app-to-app share into. Two sub-options, neither committed to yet:
   - **Manual friction, no new infrastructure:** the link opens in a browser/Drive app as-is; the
     recipient downloads the file, then manually uses "Open with → Overdub" to import it. Consistent
     with "no central server," but adds real friction right at first-touch, the worst place for it.
   - **Owned-domain App Link + static landing page:** wrap the cloud-storage link behind a domain
     this app controls (e.g. `overdub.app/collab/<id>` redirecting to the actual storage URL), with
     `assetlinks.json` verification so Android opens the app directly if installed, or a static
     (no-backend-compute) landing page with a Play Store button if not. Costs owning a domain and
     hosting a static redirect/landing page — more than "zero infrastructure" but well short of an
     app-specific backend/social feed, so it doesn't reverse the "no central server" differentiation
     from centralized layering apps (SoundStorming, Trackd, BandLab, Soundtrap) established in
     "Prior art check" above.

**Decision (2026-07-09): both cases decided.** Option 1 (app-to-app direct share) is ratified —
build it as the preferred path whenever the recipient has the app. For the no-app-yet case, take
the owned-domain App Link + static landing page route: first-touch is the worst possible place
for friction in a product whose growth mechanism *is* the forwarding chain, and the cost (a
domain plus static hosting, no backend compute) does not reverse the no-central-server
positioning.

## Latency
No authoritative published round-trip latency number exists for the Pixel 10 specifically — Google's official AOSP latency table stops at 2016-2017 Pixel/Pixel XL devices (18ms under ideal conditions). Best available reference points:
- Google reported ~39ms average round-trip latency across popular Android phones in 2021; 20ms is the CDD "Pro Audio" requirement; 10ms is the long-term target.
- Real-world A/V sync bugs (200-700ms) have been reported by Pixel 8/9 users — a different bug class from raw stream latency, but a real risk signal for anything relying on assumed latency figures.
- **Recommendation:** measure on-device with OboeTester rather than assume a number.

## Timing correction strategy (evolved over the conversation)
1. **Rejected:** "snapping"/time-stretching audio to auto-correct rhythm — technically viable (WSOLA/phase vocoder) but risks vocal artifacts and fights intentional expressive timing in rap (syncopation, rushing/dragging). Not pursued.
2. **Latency is a fixed offset, not a drift problem** — must be corrected by shifting the whole second track by measured round-trip latency, not by adjusting when recording starts.
3. **Bluetooth ruled unpredictable** by design constraint (codec/device variability, mid-session drift).
4. **Speaker+mic vs. USB-C wired audio compared:** USB-C is the only path that avoids mic bleed without Bluetooth, and is one of three officially CTS-tested latency routes in the CDD — but requires hardware most users don't have and has unverified cross-device USB Audio Class support.
5. **Final direction: accept mic bleed for accessibility.** This unexpectedly *helps* rather than only hurts:
   - Bleed enables **cross-correlation-based timing alignment** (GCC-PHAT, Knapp & Carter 1976) using the beatbox bleed as a natural reference signal — ~~no calibration step needed, more reliable than trusting AAudio's self-reported latency~~ **(claim weakened 2026-07-08).** The Test 2 sweep showed GCC-PHAT against a rhythmic beatbox reference locks onto **beat-period self-similarity aliases** — a +187 ms alias won the argmax with a "confident" PSR over the true ~-80 ms offset, and neither the PSR gate nor a positivity lag window rejected it (`test2-sweep-results.md` "Calibration click cross-check"). An *independent* calibration signal (a prepended aperiodic chirp, detected by matched filter) was required to even *judge* the alignment, and is likely needed in the product to gate it per-capture. So "no calibration step" no longer holds as stated; the honest position is "calibration is needed to *validate/gate* the bleed correlation, and whether the product must *emit* a calibration chirp per take or can rely on a runtime self-check is an open question." This also rehabits trusting AAudio's self-reported latency (Test 1a): on the Pixel 10 `getTimestamp` succeeded on both streams and tracked the start-jitter, so it may be the more robust mechanism — the original rejection rested on a single moto g(20) anecdote.
   - Bleed can be reduced (not eliminated) via **acoustic echo cancellation with a known reference** (NLMS adaptive filtering, per Sondhi & Berkley 1980) — best done **offline, on-device** (processing-locus decision 2026-07-09) using the exact clean beatbox stem, since there's no real-time deadline and the known delay constrains the search. Android's built-in `AcousticEchoCanceler` is a real-time alternative but of unverified quality for music content specifically. Whether EC is needed at all for v1 is gated on the bleed-mix listening test (see "Open items").
6. **Revisited 2026-07-05, after documentation review:** point 5's bleed mechanism assumes the reference track exits the phone's own loudspeaker and re-enters its own mic. Headphone monitoring removes that acoustic path almost entirely, silently breaking alignment for a large, predictable share of real users — not addressed in the original design. See "Headphone monitoring gap and alignment alternatives" below for the options considered and the direction chosen.

## Headphone monitoring gap and alignment alternatives

**Problem:** bleed-based alignment above only works when the reference track is actually audible to
the recording device's own microphone. Headphone monitoring (closed-back, in-ear, most Bluetooth
earbuds) — the natural choice for anyone trying to hear a clean reference while performing, and the
route Android switches to automatically once a headset is connected — removes that acoustic path
almost entirely. This wasn't addressed in the original design; it surfaced via a documentation
review (`review-20260705-093038.md`).

**Alternatives considered:**
1. **Forced-speaker calibration chirp.** `AudioTrack.setPreferredDevice()` / `AudioRecord.setPreferredDevice()`
   (public API, 23+/28+) can route one stream to the built-in speaker/mic even while a headset is
   connected. A short automatic chirp at the start of the lead-in, forced to the speaker/mic
   regardless of the active route, would let the existing bleed-correlation approach run as an
   invisible calibration step before handing off to headphones for the actual take. Uncertain
   whether OEMs/the Bluetooth stack actually let an app demote an active headset route for one
   stream — unverified, would need its own device test.
2. **Trust platform-reported latency instead of measuring it acoustically.** AAudio/Oboe expose
   stream timestamps against a shared clock; if accurate, this gives the round-trip offset directly,
   with no dependence on any acoustic signal at all — works identically on speaker or headphones.
   Point 5 above rejected this based on a single anecdotal ~100ms discrepancy reported on one
   mid-range device (moto g(20)) — thin evidence to discard the simplest option outright.
3. **Adaptive hybrid.** Detect the active output route and switch mechanism: bleed-correlation on
   speaker, option 1's forced chirp on headphones, platform timestamps as a last resort. More moving
   parts than a single mechanism, and only worth building if option 2 alone doesn't hold up across
   devices.

**Decision: validate option 2 first.** It's the cheapest to test — it extends the loopback rig
`prototype-plan.md`'s Test 1 already builds, rather than requiring new device-routing machinery —
and if it holds up, it eliminates the entire bleed-dependency question for headphone sessions rather
than working around it. Options 1 and 3 stay as fallback candidates if option 2's accuracy proves
unreliable across devices. See `prototype-plan.md`'s Test 1a. **Caveat (2026-07-08, Session A
re-capture):** even on the Pixel 10, 1 of 9 sessions returned a ~40 ms `getTimestamp` outlier
(the other 8 clustered within ±0.25 ms) — so option 2, if adopted, must read the timestamps
repeatedly and take a median rather than trusting a single read, and the loopback honesty check
(Test 1a) remains load-bearing regardless. Test 3's arithmetic sharpened this (2026-07-08):
median-of-5 is the minimum that clears the multi-hop gate at the observed rate, and only by half
a percentage point — and whether medians help at all depends on the outlier being a single-read
glitch rather than a session-level state, which is untested. Both questions are scheduled in the
interim timestamp-variance plan (`prototype-plan.md` Test 1a) while the rig is delayed.
**Decomposition update (2026-07-08, `test2-sweep-results.md` "Session A timestamp-outlier
decomposition"):** the offline outlier decomposition (plan step 1) did *not* confirm a
single-read glitch — but it found no evidence of a session-level state either (the wall anchors
and capture length are clean-ish), and it showed single-read sidecars *under-determine* the
attribution because the only cross-run referents available jitter by as much as the anomaly.
That makes plan step 2's multi-read logging load-bearing for the glitch-vs-session-state
question (its frame-vs-time-line discriminator needs no cross-run referent); median-of-5 stays
the leading candidate on "no evidence the glitch persists" + step 2's upcoming measurement,
not on a proven single-read glitch. **Multi-read batch update (2026-07-08,
`test2-sweep-results.md` "Multi-read timestamp batch"):** step 2 ran — 43 baseline captures on
the Pixel 10, ~11 `getTimestamp` reads each. The glitch-vs-session-state question is now settled
by measurement, and the answer is **median-of-5 is not a blanket fix.** Of 2 anomalous runs, one
was an isolated timestamp glitch the median recovered (the click-anchored alignment still
PASSED) — median-of-k validated for that class. The other was a **session-level desync**: the
input clock read ~+35 ms off for the whole session, the audio itself misaligned 78.67 ms (click
FAIL), the median wrong too, and it was silent to every XRun/dropped/route gate — only the
independent click anchor caught it. A uniform whole-session offset shift is invisible to a
line-fit consistency check as well (no off-line points, just a shifted intercept), so the only
detector for the session-level class is an independent anchor: the click on the speaker route,
the loopback rig on the headphone route. So the product's timestamp mechanism needs
median-of-k **plus** a per-capture rejection gate; on the headphone route (no click, no runtime
rig) the session-level class would be silent, which is the concrete failure Test 1a's rig
honesty validation must de-risk before the product trusts `getTimestamp` blind.

**Decision revised (2026-07-09): pursue option 1 (forced-speaker chirp) first for the product.**
The multi-read batch changed the calculus: option 2's session-level desync class is undetectable
on the headphone route without an acoustic anchor, while option 1 — if the route override works —
gives headphone sessions the same calibration-signal anchor + per-capture gate as the speaker
route (one mechanism everywhere, timestamps demoted to diagnostics). **Gating fact established
(2026-07-09): the Tier-2 headset-override test PASSED on the Pixel 10** — `setDeviceId()` demoted
an active USB headset (route stayed `builtin_speaker`, acoustically corroborated), so the
forced-speaker chirp is buildable on this device (`test2-sweep-results.md` "Headset-route
session"). Caveats: wired USB only — Bluetooth untested, and route demotion is per-device OEM
behavior, so it joins the cross-device list. Option 2 remains the fallback if other OEMs refuse
the override, and then requires
median-of-5 reads plus a per-capture rejection gate, rig-validated honesty, and a UX answer for
the undetectable session-level class. Backstop UX (either route, decided 2026-07-09): a
**re-take prompt on gate failure** — when the per-take gate fails, tell the performer
immediately and offer a re-record.

## Chain-of-forwarding alignment error

**Problem:** raised in documentation review (`review-20260705-093038.md`) — the product is
explicitly multi-hop ("record, share, overdub, forward further"), but every design decision above
analyzes alignment for a single overdub relationship. If each hop's alignment measurement has some
residual error, does it compound across a chain (A→B→C→D...) into audible drift by the last track?

**Partial fix: always forward raw stems, never a flattened mix.** If every hop re-sends all prior
individual stems rather than a progressively-flattened mix, each new overdubber's alignment is
always computed against the original clean beatbox reference, not against a chain of
previously-aligned/re-mixed copies. This closes one real compounding path — error introduced by
repeatedly re-encoding/re-flattening/transcoding audio through successive hops — since the reference
signal used for correlation stays pristine at every hop instead of degrading hop over hop. This is
effectively free given the "never trim/flatten at the source" principle already established below.

**What raw-stem forwarding does NOT fix:** each hop still performs its own independent
latency/alignment measurement on that device (bleed correlation, or AAudio timestamps per the option
above), and each measurement has its own error distribution — a few milliseconds of misalignment is
possible even against a perfectly clean reference. Forwarding raw stems doesn't reduce this per-hop
*measurement* error, only the *reference-degradation* error. Whether independent per-hop measurement
errors compound audibly across a chain (track 4 ends up meaningfully off from track 1 even though
each hop was individually "aligned") is a genuinely open, untested question — a
statistics-of-independent-errors question, not a data-format question.

**Decision:** always forward raw/lossless per-track stems downstream (never a flattened mix) as a
low-cost mitigation.

**Update (2026-07-08) — the open question is narrower than the paragraph above states.** Because
every hop aligns against the *original* reference (a direct consequence of raw-stem forwarding),
independent per-hop *noise* does not compound at all: each track's error vs. the shared reference
is an independent draw, so the misalignment between any two tracks is the difference of two draws
— essentially flat in chain length, not a random walk (a random walk would require each hop
aligning to the *previous* track, which this design forbids). The genuinely open multi-hop risks
are instead: (a) **per-device systematic bias** — each device's alignment mechanism can carry a
fixed bias (the moto g(20) timestamp discrepancy is this class), and misalignment between
heterogeneous devices is dominated by bias *differences* that no chain statistics average away;
and (b) **interference growth** — hop k correlates against the original stem through the bleed of
k−1 other stems plus the performer's own vocal, so per-hop error worsens with position in the
chain. `prototype-plan.md`'s Test 3 was revised accordingly (2026-07-08) to model bias +
position-dependent interference and to gate on the max *pairwise* offset, not a summed
"cumulative" drift. **First run (2026-07-08, conditional PASS):** with the measured per-hop noise
(0.31 ms std) the N=4 gate sits at 1.13 ms — 7% of the 15 ms ceiling — so the whole budget is
cross-device bias: the gate holds iff per-device biases agree within **~±8 ms** (a requirement on
unmeasured hardware, judged when a second device is tested), and the headphone/timestamp
mechanism needs **median-of-5** timestamp reads to survive the observed 1-in-9 ~40 ms outlier
rate. See `prototype-plan.md` Test 3 for the full results.

## Concurrency and threading model (added 2026-07-05)

**Problem:** raised in documentation review (`review-20260705-093038.md`) — neither doc said where
GCC-PHAT alignment, echo cancellation, or file I/O for the shared recording would run, despite
`CLAUDE.md`'s own main-thread-discipline rule (CPU-bound work off the main thread, I/O off the main
thread).

**Decision:**
- GCC-PHAT alignment runs on `Dispatchers.Default` (CPU-bound, not trivially fast) — never inline
  with the Oboe audio callback or the UI thread.
- File I/O for the shared recording (write to disk, upload to cloud storage, read a downloaded
  stem) runs on `Dispatchers.IO`.
- Echo cancellation, if adopted after the bleed-mix listening test (see "Open items"), runs
  **offline on-device** like alignment — a post-take NLMS pass on `Dispatchers.Default`, not
  real-time audio-callback work. (Processing-locus decision 2026-07-09: there is **no processing
  backend** — earlier "server-side" phrasing for EC and the playback-start offset meant
  *offline*, and all post-alignment processing runs on the phone, preserving the
  no-central-server positioning. The `AcousticEchoCanceler` real-time fallback, if ever adopted,
  is platform `AudioEffect` work, not app-owned coroutine work.)
- Alignment is exposed as a single `suspend fun align(...)` on a repository-shaped class (e.g.
  `OverdubRepository`, consistent with the android-data-layer skill's repository-as-error-boundary
  pattern), not a fire-and-forget callback. The caller (ViewModel) owns the scope
  (`viewModelScope`), so backing out of the alignment screen cancels the parent job and
  cancellation propagates automatically — no separate cancel-token plumbing. The correlation loop
  should check for cancellation periodically (e.g. `ensureActive()` inside the FFT/correlation
  loop) so a cancelled job actually stops promptly rather than running to completion silently.

This matches the CPU-bound/I-O-bound split `CLAUDE.md` already establishes for the sibling audio
app, and follows the coroutines skill's "suspend fun, caller owns the scope" guidance directly, so
it doesn't need to be reverse-engineered later the way the noisedroid FFT-synthesis threading fix
was.

## Session state persistence (added 2026-07-05)

**Problem:** raised in documentation review — the lead-in design has session state (key, meter,
tempo, whether the reference chord is enabled) that should survive at least a configuration change,
and arguably prefill on the next app launch, but neither doc named a persistence mechanism.

**Decision:** Jetpack **Preferences DataStore**, not Room or Typed/Proto DataStore — the state is
four scalar values with no relational structure, too small to justify a schema/serializer. Two
distinct lifetimes:
- **Active session state** (state of an in-progress recording) lives in memory in the recording
  Service/ViewModel only, per `CLAUDE.md`'s existing "single source of truth" rule for playback
  state — never read from or written to DataStore mid-session.
- **Last-used defaults** (key/meter/tempo/chord-enabled) are written to Preferences DataStore only
  when the user changes them on the setup screen, and read once to prefill that screen on next
  launch — DataStore is a durable-defaults cache, not the source of truth for a running session.

Per the datastore skill's two known traps: any `catch` around DataStore reads/writes must not
swallow `CancellationException`, and a `corruptionHandler` should be installed (fall back to the
default session config, not a crash) since Preferences DataStore can throw `CorruptionException` on
a damaged file just as the typed variant can.

## Lead-in / count-in design (final proposal)
1. First user sets key, meter, tempo.
2. A lead-in plays: metronome count-in + optional reference chord (user-requested only — skippable for pure percussion tracks).
3. Recording starts immediately at lead-in; performer waits until measure 2 to begin the real performance.
4. Full recording (including lead-in) is sent downstream — **never trimmed at the source**, because the lead-in is the reference material needed for alignment, and the correct cut point isn't known until after alignment is computed.
5. Non-destructive **playback-start offset** (computed once, on-device after alignment — processing-locus decision 2026-07-09, see "Concurrency and threading model") lets downstream users skip the lead-in on playback without deleting it from the file.
6. **Critical implementation risk flagged:** the lead-in and the overdub target track must be one continuous audio buffer/stream, not two sequentially-scheduled players — a scheduling seam between them would silently invalidate the measured offset. Needs explicit verification on real devices.

## Early-start / pickup-note handling
- Problem: a hard boundary at the downbeat either clips early/accidental starts or clips intentional pickup notes — can't distinguish the two after the fact.
- **Resolved via UX, not detection:** explicit visual/audio cue — metronome goes silent after the count-in ("get ready"), then indicates "recording" on beat 1. Users wanting pickup notes deliberately insert their own lead time by waiting an extra measure.
- Onset-detection-based auto-recovery of early content was considered and explicitly **not** pursued for v1 — unverified on noisy phone recordings, adds engineering, redundant with the simpler UX fix.
- **Pre-roll buffer question (should slightly-early starts be captured rather than dropped) was explicitly deferred**, pending real usage data (proxy metric suggested: rate of immediate re-recording after a take, as a signal of boundary-related frustration).
- **Fade-in at the playback-start offset:** approved as a cheap, unconditional fix for click/pop artifacts at any hard cut point — orthogonal to the pre-roll question, doesn't resolve or require resolving it.

## Open items / explicitly deferred
- Pre-roll buffer size and whether it's needed at all — deferred pending real-world data.
- ~~Reliability of cross-correlation alignment under low bleed SNR (loud/close-mic vocal vs. quiet
  bleed) — unverified by the 2026-07-05 sweep, which measured bleed against a quiet room only,
  with no vocal present, in exactly the 500–4000 Hz speech band the correlator now uses.~~
  **Resolved (2026-07-08)** by Test 2 step 3 (vocal-interference injection,
  `test2-sweep-results.md`): the alignment is essentially immune to the vocal — the click-anchored
  GCC-PHAT offset is unchanged from +0 to +24 dB in-band vocal-to-bleed ratio, and the realistic
  ratio measured in-basis is **−12.2 dB** (a real close-mic take lands *below* the bleed, the
  opposite of the "loud vocal" assumption). The failure mode at +24–30 dB is burial of the
  *calibration click* (the anchor), not alignment pulling — ~36 dB of margin. The vocal is
  tempo-correlated but not waveform-correlated with the reference, so PHAT sees it as in-band
  noise, not a competing peak.
- **Beat-period aliasing of GCC-PHAT against a rhythmic reference (added 2026-07-08).** A
  beatbox-style reference has strong self-similarity at its inter-onset interval (~187 ms for
  `boots.wav`); under real-bleed SNR the PHAT argmax locks onto that alias one beat displaced from
  the true alignment, with a high PSR, and a positivity lag window blesses it. Neither PSR nor a
  plausible-offset window rejects it — only an independent aperiodic reference (the calibration
  chirp) does. Open product questions: must every take emit a calibration chirp to gate the
  correlation, can a runtime self-check (e.g. consistency of GCC-PHAT across two analysis bands, or
  vs. `getTimestamp`) detect the alias without an emitted chirp, or should the reference be chosen
  to be less rhythmically periodic? See `test2-sweep-results.md` "Calibration click cross-check."
  **Decided (2026-07-09): every take emits a calibration signal**, mixed into the playback stream
  at a known sample position during the lead-in (generated at playback time — never embedded in
  the shared files), providing both the anchored search window and the per-take rejection gate
  (`|gcc − signal| ≤ 2 ms`; gate failure → re-take prompt). No vocal is present during the
  lead-in, so the burial failure mode can't occur there. The laboratory chirp's *sound* is not
  required — the hard requirements are: energy concentrated in 500–4000 Hz (the measured
  speaker/mic passband), ≥ ~2 kHz of bandwidth within it (sub-ms, cycle-unambiguous matched-filter
  peak), an aperiodic single-peak autocorrelation (sidelobes ~10+ dB down within the ±90 ms
  window), a deterministic waveform at a known position, and enough level × duration for ~10 dB
  detection quality (pulse compression lets a longer signal be proportionally quieter). Duration,
  level, envelope, and timbre are free. **Next: prototype 2–3 musical candidates and A/B them**
  (a designed accented-downbeat count-in transient — must stay timbrally unique vs. the other
  count-in clicks or the beat-period alias returns; a low-level 200–400 ms log-sweep riser; a
  fixed-seed shaker/noise burst), validated synthetically first, then one on-device capture each.
  Rejected: "choose a less periodic reference" (the reference is user content) and a
  timestamp-only runtime self-check as the primary gate (it cannot see the session-level desync
  class).
  **Bake-off synthetic validation — done (2026-07-09).** Three candidates implemented in
  `analysis/src/overdub_analysis/calibration_candidates.py`, gated by
  `analysis/scripts/validate_calibration_candidates.py` + `tests/test_calibration_candidates.py`
  (26 tests, all green). A/B result (the hard requirements, all measured in the 500–4000 Hz band;
  dominance is gated only for the downbeat, the one that lives among count-in clicks):

  | candidate | in-band % | bw (90pct) | worst sidelobe ±90 ms | beat lobe 187 ms | dominance vs ticks | detect q @0 dB | proc gain |
  |---|---|---|---|---|---|---|---|
  | accented-downbeat (50 ms linear chirp 3400→500) | 100% | 2240 Hz | −54.6 dB | −inf | **95.6 dB** | 18.5 dB | 21.2 dB |
  | log-sweep-riser (300 ms, 500→4000, peak −18 dBFS) | 99.9% | 2717 Hz | −40.5 dB | −88 dB | 76.1 dB | 24.1 dB | 29.7 dB |
  | shaker-burst (100 ms band-limited noise, fixed seed) | 96.8% | 2950 Hz | −18.5 dB | −314.8 dB | 4.1 dB | 16.5 dB | 25.4 dB |

  **All three meet every hard requirement synthetically** (≥2 kHz in-band bw; sidelobes ≥10 dB down
  in ±90 ms; ≥10 dB detection quality with 0-sample onset error even at −6 dB in-band SNR; deterministic
  at onset 0). The A/B distinctions the table exposes, none of which the lab chirp revealed: (1) the
  **riser** has the most processing gain (29.7 dB — 300 ms × 3120 Hz) and the best in-band aperiodicity
  margin, so it detects at the lowest emitted level, but it is the longest signal; (2) the
  **downbeat** is the only one that *belongs* in a count-in (an accented downbeat) and is maximally
  timbrally distinct from metronome ticks (95.6 dB dominance — the pitch glide vs a static-pitch
  tick), with the best ±90 ms sidelobes, but its short 50 ms gives the least processing gain so it
  needs the highest emitted level; (3) the **shaker** has the widest in-band bandwidth and the deepest
  beat-period lobe (noise is maximally aperiodic) but is the most confusable with *tonal* count-in
  content (4.1 dB dominance — its flat-in-band spectrum has energy right at a metronome tick's
  frequency), so it is a poor choice *as a count-in accent* though fine as a standalone lead-in burst.
  Two design lessons the prototype paid for, recorded for the port: a log sweep + attack-side decay
  collapses the occupied bandwidth below 2 kHz (energy piles up at the high-f start) — a *linear* sweep
  with a flat envelope is required to spread energy across the band; and a pulse-compressed signal's
  matched-filter quality-exclusion must be the ~ms compressed-pulse width, not the template length
  (excluding the 300 ms template length wiped every competitor and returned quality = inf). **Next: one
  on-device capture each** (manual checkpoint, Pixel 10 + adb — the synthetic path can't exercise the
  real speaker→mic band-limiting/reverb/polarity the lab chirp survived at ~34 dB); each capture must
  confirm ≥10 dB matched-filter detection quality and ≤2 ms onset recovery against the in-basis
  template, and the user auditions the rendered candidates (`analysis/calibration_bakeoff/`,
  gitignored) for musicality — which signal reads as belonging in a count-in is a listening judgment,
  not something the synthetic gate decides.
  **Selection (2026-07-09, post-audition): use the log-sweep-riser as the emitted calibration signal
  for now.** All three auditioned well; the riser is chosen for v1 on its detection margin (most
  processing gain — 29.7 dB — so it detects at the lowest emitted level, ~24 dB quality at 0 dB
  in-band SNR) and its unobtrusive "riser under the count-in" character. The accented-downbeat and
  shaker-burst stay as documented fallbacks for later design (e.g. if the riser's 300 ms length or
  its sustained tone reads as obtrusive on-device, the downbeat is the natural count-in-native
  substitute — it already dominates metronome ticks by 95.6 dB). The selection is encoded as
  `SELECTED_CANDIDATE_FACTORY` in `calibration_candidates.py`. **Remaining step:** one on-device
  capture of the riser through the real speaker→mic path (manual checkpoint, Pixel 10 + adb) to
  confirm ≥10 dB detection quality and ≤2 ms onset recovery on the route that matters; the lab chirp
  in `calibration_click.py` is a separate, already-validated Test 2 ground-truth instrument and is
  not changed by this selection. The no-device prep is done (2026-07-09): the riser is mixed into
  the harness asset at 0.550 s inside the click lead-in (`mix_calibration_signal.py`,
  `SELECTED_MIX_ONSET_S`), and `detect_calibration_signal.py` judges the pass bar per capture with
  the ≤2 ms recovery measured against the click in the same capture (a real capture's true onset
  is unknown, so the click is the in-basis truth).
  **On-device capture — PASS (2026-07-09, bake-off closed).** Baseline cell, canonical wall
  geometry, clean run (xrun=0): riser detection quality **17.8 dB** (bar ≥ 10, compressed-pulse
  exclusion), onset recovery **0.00 ms vs the click** (bar ≤ 2 ms) — both instruments recovered
  the identical −2847-sample offset, and ground truth − `stream_offset_ms` reproduced the known
  ~−15 ms basis constant. The riser is confirmed as the v1 emitted calibration signal on the route
  that matters; the port implements the riser waveform + the anchored ±90 ms window + the
  |gcc − signal| ≤ 2 ms re-take gate. Full record: `test2-sweep-results.md` "Riser on-device
  capture" (including the capture's 2550-sample clip census — the known ADC-rail class again,
  re-confirming capture headroom as the first-order product fix).
- **Echo cancellation for v1 — YES, v1 work (bleed-mix listening test, 2026-07-09).** The
  vocal-injection study measured the overdub capture carrying reference bleed ~12 dB *above* the
  vocal (ratio −12.2 dB), so a speaker-route stem is bleed-dominated. The listening test
  (`analysis/scripts/render_bleed_mix.py`; renders + manifest in
  `analysis/listening_test/`, gitignored) aligned a Session A capture to the clean reference and
  auditioned the product-shaped mix against a simulated-echo-cancellation ladder (bleed attenuated
  6/12/18 dB) and a perfect-EC reference (vocal only). Verdict: the unsuppressed product mix is
  **not** acceptable — the bleed reads as objectionable HF hiss/coloration, not benign on-beat
  "room"; the first acceptable rung is **~12 dB suppression** (vocal brought from −12.4 dB under its
  backing to ~−1.5 dB), 18 dB cleaner, perfect-EC best with the least hiss. So offline on-device
  NLMS (or `AcousticEchoCanceler`) is v1 work, with a rough **suppression target ~12 dB**; the
  residual hiss above 12 dB is the remaining quality cost (the bleed path degrades HF the clean
  reference doesn't carry — confirmed by its absence in the no-bleed renders). Two method notes
  the test established: (1) the vocal must be placed on the reference grid via its take's
  `getTimestamp` stream offset, NOT a whole-take vocal-vs-reference GCC-PHAT (the latter
  correlates two different waveforms and is tempo-correlated but segment-unstable, which put the
  vocal off-rhythm until corrected); (2) the A/B must be loudness-matched (common RMS) so the ear
  judges coloration, not the bleed's ~16 dB level dominance. `AcousticEchoCanceler` quality on
  music content remains unverified — the ~12 dB target is what an EC mechanism would have to meet.
  **NLMS feasibility measured (2026-07-09): offline NLMS clears the target on the real path.**
  The prototype (`analysis/src/overdub_analysis/echo_cancel.py`; driver
  `analysis/scripts/run_echo_cancel_eval.py`; synthetic gate `tests/test_echo_cancel.py`) runs
  NLMS with the exact clean reference as the far-end signal on a click-gated, aligned Session A
  capture (a causality guard absorbs the ±2 ms alignment residual). On two baseline captures:
  **bleed-only 18.4 / 18.3 dB** in-band suppression (500–4000 Hz; room-noise ceiling ~59 dB, so
  the result is mechanism-limited, not noise-limited), and **14.1 dB with the vocal present**
  (the product's adaptation condition — the vocal mixed in at the measured −12.2 dB in-band
  ratio), both clearing the ~12 dB target. The step size is the lever that got the vocal-present
  case over the bar: near-end signal costs adaptation misadjustment proportional to mu
  (10.6 dB at mu 0.5, 11.8 at 0.15, 14.1 at 0.05 with extra passes buying back convergence) —
  precisely the trade *offline* EC gets for free, since there is no convergence deadline; this is
  the concrete advantage over the real-time `AcousticEchoCanceler` path. Per-second suppression
  varies with content (7.5–24.9 dB; quiet passages suppress less) — the take-total in-band number
  is the target-comparable quantity. Caveats, all inherited favorable-case: one device (Pixel 10),
  two captures of one cell, one vocal take, and the vocal-present run is a *constructed* stem
  (a real simultaneous vocal+bleed capture could interact with mic DSP in ways a mix cannot show).
  Remaining EC work: audition `residual_bleed_only.wav` / `residual_with_vocal.wav`
  (`analysis/echo_cancel_eval/`, gitignored) against the listening test's simulated ec12 rung to
  confirm 14–18 dB of *real* NLMS reads as clean as 12 dB of arithmetic attenuation did, and the
  eventual on-device (Kotlin/C++) port with the synthetic tests as port-correctness fixtures.
  **First audition + artifact diagnosis (2026-07-09): "a lot of clicks and hiss" — measured, three
  causes, two of them real findings** (`analysis/scripts/diagnose_ec_residual.py` separates the
  classes): (1) **The clicks are beat-aligned capture-saturation residuals.** The Session A
  baseline capture itself is clipped — 1,247 full-scale samples in the raw device WAV, and every
  broadband click event in it sits on a reference beat onset (255/255) — the input chain rails on
  beatbox kick transients at conversational volume. Clipping is a nonlinearity a linear FIR cannot
  model, so each clipped kick leaves a near-full-scale click in the residual (109/109 residual
  clicks beat-aligned). This is capture saturation, not filter failure; the RMS suppression
  numbers stand (the clicks are too short to move RMS) but perceptual acceptability of real EC is
  still open. Product options it raises: capture headroom (lower input gain, or a float/24-bit
  capture path), clip-aware EC (freeze adaptation and interpolate the residual across railed
  samples), or accepting per-beat residuals. GCC-PHAT alignment, notably, passed *through* this
  clipping all along — the correlator is robust to it; EC is not. (2) **The hiss is the known
  uncorrelated-HF bleed coloration, solo-exposed.** The capture's 8–16 kHz RMS (~3,680) dwarfs its
  500–4,000 Hz in-band RMS (~616); NLMS removes the *correlated* 16–20 dB of that HF, and what
  remains (bleed-path HF distortion + room noise) is unremovable by any reference-driven EC — the
  listening test's "bleed degrades HF" finding heard without the mix masking it. (3) **Two
  rendering bugs in the eval script compounded the audition, now fixed:** residual WAVs were
  written unscaled and hard-clipped at int16 (now one shared attenuate-only gain across the render
  set), and renders kept the lead-in, where the calibration chirp survives EC nearly uncancelled —
  the filter *over*-predicts it by ~4 dB because the ~0.9 FS chirp drives the speaker/input chain
  into a different gain regime than the music the filter converged on (level dependence; its own
  small finding: don't assume EC cleans the emitted-calibration-signal region). Renders are now
  trimmed to the content body by default; re-audition after regenerating.
  **Clip-aware EC built and measured (2026-07-09, second audition still heard the clicks —
  expected, since down-scaling can't un-clip a railed waveform).** A railed sample is missing
  data, so the treatment is: freeze adaptation across railed spans (adapting on the rail injects
  the clipping error into the weights) and mute the residual across them with 2 ms fades
  (`clip_mask` / `mute_spans` in `echo_cancel.py`, `adapt_mask` on `nlms`; on by default in the
  eval whenever the capture rails). On the baseline capture: 55 spans, 626 ms total muted (~4% of
  the take, 3 ms pad per side); the residual's peak dropped from −4.5 to **−26.5 dBFS** (the
  residual's peaks were entirely saturation clicks — now ~16 dB *below* the capture's peaks
  instead of 6 dB above), and in-band suppression improved to **20.4 dB bleed-only / 14.0 dB
  vocal-present** (from 18.2 with the raw residual). Beat-aligned residue outside the railed spans
  survives at the ~22 dB-quieter level — the un-railed portion of each loud transient, the same
  level-dependence class as the chirp finding; whether it still reads as clicks is a listening
  judgment, and `--clip-pad-ms` widens the muting if so (`*_unrepaired.wav` renders keep the raw
  residual for A/B). Product corollary: clip-aware EC needs the raw capture's railed-sample
  positions, which the app has at capture time — but capture headroom (lower input gain / float
  path) remains the better first-order fix, since muting discards the performer's vocal across
  those spans too (~tens of ms per take at this rate — small, but nonzero).
- Onset detection reliability on noisy phone-recorded music content — unverified.
- USB Audio Class consistency across Android OEMs — not resolved, would need validation against actual target device list (only relevant if accessibility priority is later reversed).
- **Non-visual (haptic) cue for the "recording" signal** — documentation review flagged that a
  performer watching their instrument/hands can't see a visual-only cue at the critical instant.
  **Explicitly deferred to later in the prototyping phase**, not decided now — it's a UX-layer
  decision independent of the load-bearing timing assumptions Test 1/1a/Test 2/Test 3 are gating,
  so it doesn't block prototype validation. Revisit once those tests conclude.
