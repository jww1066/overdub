# Collaborative Overdub App — Design Discussion Summary

## Core concept
An Android app for musical collaboration: one person records audio (e.g., beatboxing), sends it via standard sharing (messaging apps), a second person overdubs on top (e.g., rapping), and can forward the result further. Use case is hip-hop specifically (rap + sung hooks), with other musical applications possible.

## Prior art check
No existing app matches this exact model — record locally, share via native OS share sheet, recipient overdubs and re-shares the same way, no central server/social feed required.

- **Centralized layering apps exist** (SoundStorming, Trackd, BandLab, Soundtrap) but collaboration happens through the app's own network/cloud, not the phone's native share sheet.
- **iOS Voice Memos** added on-device layered recording (iPhone 16 Pro+, 2025) but it's local-only, no send/forward loop.
- Weak supporting evidence: a Loopy Pro forum thread shows someone explicitly wanting this exact workflow ("record my track, send to group member, they record, and so on") and being pointed to full DAW tools or manual file-passing instead.
- **Confidence: moderate that nothing like this exists** — search was not exhaustive (no full Play Store audit).

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
