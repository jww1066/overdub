"""Tests gating the musical calibration-signal candidates on the hard requirements.

doc/design-summary.md "Beat-period aliasing" (decided 2026-07-09) + doc/prototype-plan.md
"calibration-signal bake-off": the per-take calibration signal must meet
  - energy concentrated in 500-4000 Hz;
  - >= 2 kHz of bandwidth within it;
  - an aperiodic single-peak autocorrelation (sidelobes ~10+ dB down in +/-90 ms);
  - a deterministic waveform at a known position;
  - ~10 dB detection quality under the realistic capture path.
The accented-downbeat candidate additionally must be timbrally unique vs the
other count-in clicks (dominance >= 10 dB), or the beat-period alias returns
through the back door. These tests are the synthetic gate the design doc
sequences *before* the one-on-device-capture-each step.
"""

from __future__ import annotations

import numpy as np
import pytest

from overdub_analysis.calibration_candidates import (
    BAND_HI_HZ,
    BAND_LO_HZ,
    accented_downbeat,
    count_in_scenario,
    detect_template,
    evaluate_candidate,
    log_sweep_riser,
    shaker_burst,
)

RATE = 48000

CANDIDATES = [accented_downbeat, log_sweep_riser, shaker_burst]


def _metrics(factory, **kw):
    return evaluate_candidate(factory(rate=RATE), snrs_db=(0.0,), **kw)


# --- determinism + known position -------------------------------------------


@pytest.mark.parametrize("factory", CANDIDATES, ids=lambda f: f().name)
def test_generation_is_deterministic(factory):
    """Regeneration is bit-identical (the emitted signal and the matched-filter
    template must be the same waveform)."""
    a = factory(rate=RATE)
    b = factory(rate=RATE)
    assert a.seed == b.seed
    np.testing.assert_array_equal(a.template, b.template)
    # Different seeds (where the seed is actually used, e.g. the shaker's
    # noise) change the waveform; the chirp candidates are seed-independent.
    c = factory(rate=RATE, seed=a.seed + 1)
    if a.name == "shaker-burst":
        assert not np.array_equal(a.template, c.template)
    else:
        np.testing.assert_array_equal(a.template, c.template)


@pytest.mark.parametrize("factory", CANDIDATES, ids=lambda f: f().name)
def test_template_onset_is_zero_and_band_confined(factory):
    spec = factory(rate=RATE)
    assert spec.onset_sample == 0
    assert spec.template.size == round(RATE * spec.duration_s)
    # All energy is generated inside the band, so out-of-band content is only
    # the bandpass filter's transition leakage -- well under 10% of total.
    spec_fft = np.fft.rfft(spec.template)
    freqs = np.fft.rfftfreq(spec.template.size, d=1.0 / RATE)
    power = np.abs(spec_fft) ** 2
    inband = (freqs >= BAND_LO_HZ) & (freqs <= BAND_HI_HZ)
    assert power[inband].sum() / power.sum() >= 0.9


# --- the hard requirements --------------------------------------------------


@pytest.mark.parametrize("factory", CANDIDATES, ids=lambda f: f().name)
def test_in_band_bandwidth_at_least_2khz(factory):
    """The >=2 kHz in-band bandwidth requirement (sub-ms, cycle-unambiguous peak)."""
    m = _metrics(factory)
    assert m.bw_90pct_hz >= 2000.0, f"{factory().name}: 90pct bw {m.bw_90pct_hz:.0f} Hz < 2000"
    assert m.bw_10db_hz >= 2000.0, f"{factory().name}: -10dB bw {m.bw_10db_hz:.0f} Hz < 2000"


@pytest.mark.parametrize("factory", CANDIDATES, ids=lambda f: f().name)
def test_aperiodic_single_peak_autocorrelation(factory):
    """Worst autocorrelation sidelobe within +/-90 ms must be >=10 dB down."""
    m = _metrics(factory)
    assert m.worst_sidelobe_db <= -10.0, (
        f"{factory().name}: worst sidelobe {m.worst_sidelobe_db:.1f} dB > -10"
    )


@pytest.mark.parametrize("factory", CANDIDATES, ids=lambda f: f().name)
def test_beat_period_lobe_is_low(factory):
    """No strong self-similarity lobe at the inter-onset period (187 ms) -- the
    specific alias risk the calibration signal exists to avoid."""
    m = _metrics(factory)
    assert m.beat_sidelobe_db <= -10.0


@pytest.mark.parametrize("factory", CANDIDATES, ids=lambda f: f().name)
def test_detection_quality_and_onset_accuracy(factory):
    """Under the simulated realistic path (band-limited + inverted + in-band
    noise at 0 dB SNR) the matched filter recovers the onset to within a couple
    of samples with >=10 dB detection quality."""
    m = _metrics(factory)
    quality, onset_err = m.detection[0.0]
    assert onset_err <= 2, f"{factory().name}: onset err {onset_err} samples"
    assert quality >= 10.0, f"{factory().name}: quality {quality:.1f} dB < 10"


@pytest.mark.parametrize("factory", CANDIDATES, ids=lambda f: f().name)
def test_detection_at_negative_snr(factory):
    """Stretch: still detectable (>=10 dB) at -6 dB in-band SNR -- margin below
    any realistic phone-bleed SNR, where the real captures measured the click
    surviving at ~34 dB quality."""
    m = evaluate_candidate(factory(rate=RATE), snrs_db=(-6.0,))
    quality, onset_err = m.detection[-6.0]
    assert onset_err <= 2
    assert quality >= 10.0


# --- the downbeat-specific timbral-uniqueness requirement --------------------


def test_accented_downbeat_dominates_count_in_ticks():
    """The accented downbeat must be timbrally distinct from the other count-in
    metronome clicks: its matched-filter peak dominates neighboring ticks by
    >=10 dB, or the beat-period alias returns via the neighboring clicks
    (design-summary.md)."""
    spec = accented_downbeat(rate=RATE)
    ci = count_in_scenario(spec, bpm=120.0)
    assert ci.detected_onset_sample == 0, "downbeat must be the matched-filter argmax"
    assert ci.dominance_db >= 10.0, f"dominance {ci.dominance_db:.1f} dB < 10"


def test_count_in_scenario_rejects_bad_bpm():
    """Sanity: the scenario places ticks at the beat period and the downbeat at 0."""
    spec = accented_downbeat(rate=RATE)
    ci = count_in_scenario(spec, bpm=100.0, ticks=3)
    assert ci.downbeat_onset_sample == 0
    # The non-accent ticks are all below the downbeat (rel dB < 0).
    assert all(r <= 0.0 for r in ci.tick_rel_db[1:])


# --- detect_template primitives ---------------------------------------------


def test_detect_template_recovers_clean_delayed_onset():
    rng = np.random.default_rng(5)
    spec = log_sweep_riser(rate=RATE)
    tmpl = spec.template
    d = 2000
    cap = np.concatenate([np.zeros(d), tmpl, np.zeros(100)])
    cap = cap + 1e-6 * rng.standard_normal(cap.size)  # break exact ties
    det = detect_template(cap, tmpl, RATE)
    assert abs(det.onset_sample - d) <= 1
    assert det.quality_db > 10.0


def test_detect_template_survives_polarity_inversion():
    spec = shaker_burst(rate=RATE)
    tmpl = spec.template
    d = 1500
    cap = np.concatenate([np.zeros(d), -tmpl, np.zeros(100)])
    det = detect_template(cap, tmpl, RATE)
    assert abs(det.onset_sample - d) <= 1


def test_detect_template_rejects_short_capture():
    spec = accented_downbeat(rate=RATE)
    with pytest.raises(ValueError):
        detect_template(np.zeros(10), spec.template, RATE)
