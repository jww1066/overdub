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
  risk.
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
   - Bleed enables **cross-correlation-based timing alignment** (GCC-PHAT, Knapp & Carter 1976) using the beatbox bleed as a natural reference signal — no calibration step needed, more reliable than trusting AAudio's self-reported latency (which has documented device-specific inaccuracy, e.g. a ~100ms discrepancy reported on a moto g(20)).
   - Bleed can be reduced (not eliminated) via **acoustic echo cancellation with a known reference** (NLMS adaptive filtering, per Sondhi & Berkley 1980) — best done **offline/server-side** using the exact clean beatbox stem, since there's no real-time deadline and the known delay constrains the search. Android's built-in `AcousticEchoCanceler` is a real-time alternative but of unverified quality for music content specifically.
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
unreliable across devices. See `prototype-plan.md`'s Test 1a.

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
low-cost mitigation. The remaining open question — whether independent per-hop alignment noise
compounds across a multi-hop chain — needs its own validation; see `prototype-plan.md`'s Test 3
(proposed).

## Lead-in / count-in design (final proposal)
1. First user sets key, meter, tempo.
2. A lead-in plays: metronome count-in + optional reference chord (user-requested only — skippable for pure percussion tracks).
3. Recording starts immediately at lead-in; performer waits until measure 2 to begin the real performance.
4. Full recording (including lead-in) is sent downstream — **never trimmed at the source**, because the lead-in is the reference material needed for alignment, and the correct cut point isn't known until after alignment is computed.
5. Non-destructive **playback-start offset** (computed once, server-side, after alignment) lets downstream users skip the lead-in on playback without deleting it from the file.
6. **Critical implementation risk flagged:** the lead-in and the overdub target track must be one continuous audio buffer/stream, not two sequentially-scheduled players — a scheduling seam between them would silently invalidate the measured offset. Needs explicit verification on real devices.

## Early-start / pickup-note handling
- Problem: a hard boundary at the downbeat either clips early/accidental starts or clips intentional pickup notes — can't distinguish the two after the fact.
- **Resolved via UX, not detection:** explicit visual/audio cue — metronome goes silent after the count-in ("get ready"), then indicates "recording" on beat 1. Users wanting pickup notes deliberately insert their own lead time by waiting an extra measure.
- Onset-detection-based auto-recovery of early content was considered and explicitly **not** pursued for v1 — unverified on noisy phone recordings, adds engineering, redundant with the simpler UX fix.
- **Pre-roll buffer question (should slightly-early starts be captured rather than dropped) was explicitly deferred**, pending real usage data (proxy metric suggested: rate of immediate re-recording after a take, as a signal of boundary-related frustration).
- **Fade-in at the playback-start offset:** approved as a cheap, unconditional fix for click/pop artifacts at any hard cut point — orthogonal to the pre-roll question, doesn't resolve or require resolving it.

## Open items / explicitly deferred
- Pre-roll buffer size and whether it's needed at all — deferred pending real-world data.
- Reliability of cross-correlation alignment under low bleed SNR (loud/close-mic vocal vs. quiet bleed) — unverified, flagged as an empirical question.
- Reliability of `AcousticEchoCanceler` and onset detection specifically on noisy phone-recorded music content — unverified in both cases.
- USB Audio Class consistency across Android OEMs — not resolved, would need validation against actual target device list (only relevant if accessibility priority is later reversed).
