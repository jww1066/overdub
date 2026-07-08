"""Tests for the calibration click (doc/test2-step2-plan.md item 11).

The round-trip cases mirror how the click is used for real: prepend to a
reference-like signal, simulate the capture path (delay + band-limiting +
polarity + noise), then require the matched-filter detector to recover the
onset to within a sample or two -- the accuracy class the +/-2 ms bar needs.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import butter, sosfiltfilt

from overdub_analysis.calibration_click import (
    CLICK_AMPLITUDE,
    CLICK_DURATION_S,
    LEAD_IN_S,
    PRE_SILENCE_S,
    ClickDetection,
    click_template,
    detect_click,
    prepend_click,
)
from overdub_analysis.synth import add_noise_at_snr, broadband_click_train, delay

RATE = 48000


def _reference_with_click(rng: np.random.Generator) -> tuple[np.ndarray, int]:
    """A beatbox-ish signal with the calibration lead-in; returns (ref, click_onset)."""
    content = broadband_click_train(3 * RATE, rng=rng)
    result = prepend_click(content, RATE)
    return result.samples, result.click_onset_sample


def _speaker_band(signal: np.ndarray) -> np.ndarray:
    """Zero-phase 500-4000 Hz bandpass, simulating the usable speaker->mic band."""
    sos = butter(4, [500.0, 4000.0], btype="bandpass", fs=RATE, output="sos")
    return sosfiltfilt(sos, signal)


def test_template_shape_and_bounds() -> None:
    tmpl = click_template(RATE)
    assert tmpl.size == round(RATE * CLICK_DURATION_S)
    assert np.max(np.abs(tmpl)) <= CLICK_AMPLITUDE + 1e-12
    # Hann-windowed: starts and ends at (near) zero, peaks in the middle.
    assert abs(tmpl[0]) < 1e-6 and abs(tmpl[-1]) < 1e-6
    assert np.max(np.abs(tmpl)) > 0.5


def test_prepend_positions_and_preserves_signal() -> None:
    content = np.linspace(-0.5, 0.5, RATE)
    result = prepend_click(content, RATE)
    assert result.click_onset_sample == round(RATE * PRE_SILENCE_S)
    assert result.lead_in_samples == round(RATE * LEAD_IN_S)
    assert result.samples.size == result.lead_in_samples + content.size
    # Pre-click region is silent; original signal is bit-identical after the lead-in.
    assert np.all(result.samples[: result.click_onset_sample] == 0.0)
    np.testing.assert_array_equal(result.samples[result.lead_in_samples :], content)


def test_prepend_rejects_empty_signal() -> None:
    with pytest.raises(ValueError):
        prepend_click(np.array([]), RATE)


def test_detect_recovers_onset_clean() -> None:
    rng = np.random.default_rng(11)
    ref, click_onset = _reference_with_click(rng)
    d = 4700  # ~98 ms, the measured population-mean neighborhood
    capture = add_noise_at_snr(delay(ref, d), 20.0, rng)
    det = detect_click(capture, RATE)
    assert isinstance(det, ClickDetection)
    assert abs(det.onset_sample - (click_onset + d)) <= 1
    assert det.quality_db > 10.0


def test_detect_survives_bandlimited_inverted_noisy_path() -> None:
    """The realistic case: speaker band-limiting + polarity inversion + noise."""
    rng = np.random.default_rng(12)
    ref, click_onset = _reference_with_click(rng)
    d = 3000
    capture = add_noise_at_snr(-_speaker_band(delay(ref, d)), 10.0, rng)
    det = detect_click(capture, RATE)
    assert abs(det.onset_sample - (click_onset + d)) <= 2
    assert det.quality_db > 6.0


def test_detect_quality_low_without_click() -> None:
    """A capture with no click must be flaggable via quality, not silently wrong."""
    rng = np.random.default_rng(13)
    with_ref, click_onset = _reference_with_click(rng)
    with_click = detect_click(add_noise_at_snr(delay(with_ref, 1000), 20.0, rng), RATE)
    clickless = broadband_click_train(3 * RATE, rng=rng)
    without = detect_click(add_noise_at_snr(delay(clickless, 1000), 20.0, rng), RATE)
    assert with_click.quality_db - without.quality_db > 6.0


def test_detect_search_window_bounds_the_search() -> None:
    rng = np.random.default_rng(14)
    ref, click_onset = _reference_with_click(rng)
    d = 2400  # 50 ms
    capture = add_noise_at_snr(delay(ref, d), 20.0, rng)
    true_onset = click_onset + d
    # A window around the true onset finds it.
    windowed = detect_click(
        capture, RATE, search_window=(click_onset, click_onset + round(0.3 * RATE))
    )
    assert abs(windowed.onset_sample - true_onset) <= 1
    # A window that excludes it is forced elsewhere.
    forced = detect_click(capture, RATE, search_window=(true_onset + RATE, None))
    assert forced.onset_sample >= true_onset + RATE
    # An empty window raises.
    with pytest.raises(ValueError):
        detect_click(capture, RATE, search_window=(10**9, None))


def test_detect_rejects_capture_shorter_than_template() -> None:
    with pytest.raises(ValueError):
        detect_click(np.zeros(10), RATE)
