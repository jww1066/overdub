#!/usr/bin/env python3
"""Calibration-signal bake-off: A/B the musical candidates on the hard requirements.

What this is (doc/design-summary.md "Beat-period aliasing" item, decided
2026-07-09; doc/prototype-plan.md "calibration-signal bake-off"): the product
emits a per-take calibration signal during the lead-in -- it centers the
GCC-PHAT lag search and provides the |gcc - signal| <= 2 ms rejection gate.
The laboratory chirp (overdub_analysis.calibration_click) proves the
mechanism; its sound is not required. This script prototypes three musical
candidates and ranks them on the hard requirements, synthetically first
(before any on-device capture):

  - in-band energy concentration (500-4000 Hz, the speaker->mic passband);
  - in-band bandwidth >= 2 kHz (sub-ms, cycle-unambiguous matched-filter peak);
  - aperiodicity: worst autocorrelation sidelobe within +/-90 ms <= -10 dB
    (alias resistance), plus a beat-period (187 ms) sidelobe for the record;
  - detection quality ~10 dB under the simulated realistic capture path
    (band-limited + polarity-inverted + in-band noise), with onset recovered
    to within a couple of samples;
  - the accented-downbeat candidate must dominate neighboring count-in ticks
    by >= 10 dB in the count-in scenario (timbral uniqueness -- the
    requirement that keeps the beat-period alias from returning via the
    neighboring count-in clicks).

It also renders each candidate (and the count-in scenario for the downbeat)
to WAV for the manual musicality audition -- the on-device-capture selection
is a listening judgment, not something this script makes. Renders are written
to analysis/calibration_bakeoff/ (gitignored; regenerate this script).

Usage:
    python scripts/validate_calibration_candidates.py
    python scripts/validate_calibration_candidates.py --snrs -6,0,6,10 --bpm 128
"""

from __future__ import annotations

import argparse
import os
import wave

import numpy as np

from overdub_analysis.calibration_candidates import (
    ALL_CANDIDATES,
    BAND_HI_HZ,
    BAND_LO_HZ,
    CandidateSpec,
    count_in_scenario,
    evaluate_candidate,
)


def _db(x: float) -> str:
    if x == float("-inf"):
        return "  -inf"
    if x == float("inf"):
        return "   inf"
    return f"{x:6.1f}"


def _write_wav(path: str, samples: np.ndarray, rate: int) -> None:
    pcm = np.round(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def _rms_dbfs(samples: np.ndarray) -> float:
    return float(20.0 * np.log10(np.sqrt(np.mean(samples**2)) + 1e-30))


def _to_rms_dbfs(samples: np.ndarray, target_dbfs: float) -> np.ndarray:
    """Scale ``samples`` to a target RMS level in dBFS (for loudness-matched A/B)."""
    cur = _rms_dbfs(samples)
    if cur == float("-inf"):
        return samples
    return samples * (10.0 ** ((target_dbfs - cur) / 20.0))


def _metronome_tick_samples(n: int, freq_hz: float, rate: int, peak_dbfs: float) -> np.ndarray:
    """A short Hann-windowed sine metronome tick at a target peak level."""
    t = np.arange(n) / float(rate)
    tk = np.hanning(n) * np.sin(2.0 * np.pi * freq_hz * t)
    peak = float(np.max(np.abs(tk)))
    if peak > 0:
        tk = tk * (10.0 ** (peak_dbfs / 20.0) / peak)
    return tk


def _render_audition(spec: CandidateSpec, out_dir: str, target_rms_dbfs: float = -20.0) -> None:
    """Write the bare candidate, loudness-matched to a common RMS.

    The candidates are designed at different peaks (downbeat -3, shaker -12,
    riser -18 dBFS) -- a ~15 dB RMS spread -- so a raw back-to-back audition
    would have the ear judge *level*, not *timbre* (the riser would just sound
    quiet). Loudness-matching to a common RMS makes the bare A/B a fair timbre
    comparison, mirroring the bleed-mix listening test's loudness-match note.
    The in-product balance is heard in the context render, not this one.
    """
    rate = spec.rate
    matched = _to_rms_dbfs(spec.template, target_rms_dbfs)
    lead = round(rate * 0.10)
    trail = round(rate * 0.20)
    buf = np.concatenate([np.zeros(lead), matched, np.zeros(trail)])
    path = os.path.join(out_dir, f"candidate_{spec.name}.wav")
    _write_wav(path, buf, rate)
    print(
        f"  rendered audition (loudness-matched to {target_rms_dbfs:.0f} dBFS rms): {path}  "
        f"({spec.duration_s * 1e3:.0f} ms; design peak {spec.params.get('peak_dbfs', float('nan')):.0f} dBFS)"
    )


def _render_in_context(spec: CandidateSpec, bpm: float, out_dir: str) -> None:
    """Render the candidate as it would sit in the product lead-in: mixed with
    a 4-tick metronome count-in. This is the "what the performer hears" render
    -- the candidate is NOT loudness-matched here (its level relative to the
    count-in is the in-product balance, by design), and it is placed in the
    count-in context rather than isolated.

    Placement (illustrative -- the exact lead-in layout is a product decision):
      - accented-downbeat: the candidate IS the accented tick 1 of the count-in
        (ticks 2-4 are plain 1500 Hz metronome ticks).
      - log-sweep-riser / shaker-burst: the candidate plays as a pre-count cue
        in the beat immediately before the count-in begins, then the 4-tick
        count-in follows -- a "cue, then count" lead-in.
    Metronome ticks at -12 dBFS peak (a comfortable count-in level); the
    candidate at its design level.
    """
    rate = spec.rate
    period = round(60.0 / bpm * rate)
    tick_n = round(rate * 0.012)
    tick_peak = -12.0
    tmpl = np.asarray(spec.template, dtype=np.float64).ravel()
    ticks = 4
    pre = round(rate * 0.30)  # lead silence before the cue
    # Layout: [pre silence] [cue slot, 1 beat] [4 count-in ticks, 4 beats] [tail]
    total = pre + period * (ticks + 1) + tmpl.size + round(rate * 0.30)
    buf = np.zeros(total, dtype=np.float64)
    if spec.name == "accented-downbeat":
        # Candidate is tick 1; ticks 2..4 are plain metronome.
        for i in range(ticks):
            onset = pre + i * period
            if i == 0:
                buf[onset : onset + tmpl.size] += tmpl
            else:
                tk = _metronome_tick_samples(tick_n, 1500.0, rate, tick_peak)
                buf[onset : onset + tk.size] += tk
        placement = "candidate = accented tick 1; ticks 2-4 = 1500 Hz metronome"
    else:
        # Candidate as a pre-count cue in the beat before the count-in.
        cue_onset = pre
        buf[cue_onset : cue_onset + tmpl.size] += tmpl
        for i in range(ticks):
            onset = pre + period + i * period
            tk = _metronome_tick_samples(tick_n, 1500.0, rate, tick_peak)
            buf[onset : onset + tk.size] += tk
        placement = "candidate = pre-count cue (beat -1); then 4-tick count-in"
    path = os.path.join(out_dir, f"context_{spec.name}.wav")
    _write_wav(path, buf, rate)
    print(f"  rendered in-context: {path}  ({placement}; metronome ticks {tick_peak:.0f} dBFS peak)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snrs",
        default="-6,0,6,10",
        help="comma list of in-band SNRs (dB) for the detection-quality sweep",
    )
    parser.add_argument("--bpm", type=float, default=120.0, help="count-in tempo for the timbral-uniqueness scenario")
    parser.add_argument(
        "--out-dir",
        default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calibration_bakeoff"),
        help="where to write audition WAVs (gitignored; default analysis/calibration_bakeoff)",
    )
    args = parser.parse_args()
    snrs = tuple(float(s) for s in args.snrs.split(",") if s.strip())
    os.makedirs(args.out_dir, exist_ok=True)

    print("Calibration-signal bake-off -- synthetic validation")
    print(f"band: {BAND_LO_HZ:.0f}-{BAND_HI_HZ:.0f} Hz   count-in: {args.bpm:.0f} BPM")
    print(f"detection SNR sweep (in-band dB): {', '.join(f'{s:g}' for s in snrs)}")
    print()

    rows = []
    for factory in ALL_CANDIDATES:
        spec = factory()
        m = evaluate_candidate(spec, snrs_db=snrs)
        ci = count_in_scenario(spec, bpm=args.bpm)
        rows.append((spec, m, ci))
        _render_audition(spec, args.out_dir)
        _render_in_context(spec, args.bpm, args.out_dir)

    # Per-candidate detail.
    for spec, m, ci in rows:
        print(f"=== {spec.name}  ({spec.description}) ===")
        print(f"  duration:       {spec.duration_s * 1e3:6.1f} ms   peak {_db(m.peak_dbfs)} dBFS   rms {_db(m.rms_dbfs)} dBFS")
        print(f"  in-band energy: {m.in_band_fraction * 100:5.1f}% of total")
        print(f"  in-band bw:     90pct = {m.bw_90pct_hz:6.0f} Hz   -10dB span = {m.bw_10db_hz:6.0f} Hz   (req >= 2000 Hz)")
        print(f"  aperiodicity:   worst sidelobe +/-90ms = {_db(m.worst_sidelobe_db)} dB   (req <= -10 dB)")
        print(f"                  beat-period (187ms) lobe = {_db(m.beat_sidelobe_db)} dB")
        print(f"  processing gain:{m.processing_gain_db:6.1f} dB  (10*log10(T*B); longer/quieter => more gain)")
        print("  detection (snr_db -> quality_db, onset_err_samples):")
        for snr in snrs:
            q, err = m.detection[snr]
            print(f"      {snr:5.1f} dB -> quality {_db(q)} dB, onset err {err} samples")
        print(f"  count-in:       downbeat dominance = {_db(ci.dominance_db)} dB vs neighboring ticks   (req >= 10 dB)")
        print(f"                  detected onset = sample {ci.detected_onset_sample} (true 0); per-tick rel dB: {ci.tick_rel_db}")
        # Verdict flags.
        flags = []
        if m.in_band_fraction < 0.6:
            flags.append(f"LOW in-band energy ({m.in_band_fraction * 100:.0f}%)")
        if m.bw_90pct_hz < 2000 and m.bw_10db_hz < 2000:
            flags.append(f"NARROW bandwidth (90pct {m.bw_90pct_hz:.0f} Hz, -10dB {m.bw_10db_hz:.0f} Hz)")
        if m.worst_sidelobe_db > -10.0:
            flags.append(f"PERIODIC (worst sidelobe {m.worst_sidelobe_db:.1f} dB > -10)")
        if ci.dominance_db < 10.0:
            flags.append(f"NOT timbrally unique (dominance {ci.dominance_db:.1f} dB < 10)")
        best_q = max(m.detection.values(), key=lambda t: t[0])[0]
        worst_q = min(m.detection.values(), key=lambda t: t[0])[0]
        print(f"  -> {'PASS' if not flags else 'FAIL: ' + '; '.join(flags)}")
        print()

    # A/B summary table.
    print("=== A/B summary ===")
    hdr = f"{'candidate':>20} {'inband%':>8} {'bw90Hz':>8} {'bw10Hz':>8} {'sldb90':>8} {'beatdb':>8} {'domdB':>7} {'q@6dB':>7} {'q@0dB':>7} {'pgdB':>7}"
    print(hdr)
    print("-" * len(hdr))
    for spec, m, ci in rows:
        q6 = m.detection.get(6.0, (float("nan"), 0))[0]
        q0 = m.detection.get(0.0, (float("nan"), 0))[0]
        print(
            f"{spec.name:>20} {m.in_band_fraction * 100:>7.1f}% {m.bw_90pct_hz:>8.0f} {m.bw_10db_hz:>8.0f} "
            f"{_db(m.worst_sidelobe_db):>8} {_db(m.beat_sidelobe_db):>8} {_db(ci.dominance_db):>7} "
            f"{_db(q6):>7} {_db(q0):>7} {m.processing_gain_db:>7.1f}"
        )
    print()
    print("Columns: inband% = in-band energy fraction; bw90/bw10 = in-band bandwidth")
    print("(Hz; req >= 2000); sldb90 = worst autocorr sidelobe in +/-90ms (dB vs zero-lag,")
    print("req <= -10); beatdb = sidelobe near 187 ms; domdB = downbeat dominance over")
    print("neighboring count-in ticks (req >= 10); q@6dB/q@0dB = matched-filter detection")
    print("quality at that in-band SNR (>= 10 dB is the detection target); pgdB = processing gain.")
    print()
    print(f"Renders in {args.out_dir} (gitignored):")
    print("  candidate_<name>.wav  -- bare candidate, loudness-matched to -20 dBFS RMS (fair timbre A/B)")
    print("  context_<name>.wav    -- candidate mixed into a 4-tick count-in (the in-product balance;")
    print("                           candidate at its design level, NOT loudness-matched)")
    print("The on-device step -- one capture each through the real speaker->mic path -- is a manual")
    print("checkpoint on the Pixel 10, and the faithful 'what the user hears' (phone speaker, room).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
