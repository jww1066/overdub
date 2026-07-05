# Overdub

An Android app for musical collaboration: one person records audio (e.g. beatboxing), shares it
via the phone's native share sheet (messaging apps), a second person overdubs on top (e.g.
rapping), and can forward the result further. No central server, no social feed, no app-specific
network — just local recording plus the OS share sheet, passed along like a chain letter.

Some use cases include hip-hop (rap over a beatboxed or sung hook),
harmonized singing, and many other musical collaboration patterns.

## Status

Pre-implementation. The design direction is set (see below) but its two load-bearing technical
assumptions are unverified on real hardware — see [`doc/prototype-plan.md`](doc/prototype-plan.md)
for the two narrow validation tests that need to pass before any further engineering (UI, sharing
flow, echo cancellation, lead-in UX) is worth building.

## Design highlights

Full detail and rationale in [`doc/design-summary.md`](doc/design-summary.md). Key decisions:

- **Accept mic bleed instead of avoiding it.** Rather than requiring Bluetooth/USB-C or a
  calibration step to prevent the original track from bleeding into the overdub's microphone, the
  design leans into it: the bleed becomes a reference signal for automatic timing alignment via
  cross-correlation (GCC-PHAT), so no explicit calibration step is needed.
- **Latency is a fixed offset, corrected after recording** — by shifting the overdubbed track by
  the measured round-trip latency, not by trying to control when recording starts.
- **Full recordings are always sent, never trimmed at the source** — the lead-in/count-in is kept
  as reference material for alignment; a non-destructive playback-start offset (computed after
  alignment) lets listeners skip it without deleting it from the file.
- **Timing corrections stop at alignment** — no auto time-stretching/snapping of performances, to
  avoid vocal artifacts and preserve intentional expressive timing (rushing, dragging, syncopation).
- **Early/pickup-note handling is UX, not detection** — a silent "get ready" beat after the count-in
  and an explicit "recording" cue at beat 1, rather than trying to algorithmically recover
  early-started audio.

## Validation plan

Two tests gate everything else (see [`doc/prototype-plan.md`](doc/prototype-plan.md) for full
method and rationale):

1. **Continuous-buffer latency stability** — does a single continuous audio stream (lead-in +
   overdub target) preserve a stable, correctly-measured round-trip offset, with no silent error
   from a scheduling seam between separately-scheduled players?
2. **Single-device bleed + offline alignment** — does GCC-PHAT recover a usable alignment peak from
   real phone-speaker-to-phone-mic bleed, or does real-world SNR fall below what the method needs?

If either fails, the "accept bleed, no calibration" design direction needs to be reconsidered before
further work.

## Open questions

Explicitly deferred pending real usage data or further investigation (see
[`doc/design-summary.md`](doc/design-summary.md) for details): pre-roll buffer sizing, echo
cancellation quality on real music content, and USB Audio Class consistency across Android OEMs.

## Development

See [`CLAUDE.md`](CLAUDE.md) for Android audio development and testing conventions used in this
repo.
