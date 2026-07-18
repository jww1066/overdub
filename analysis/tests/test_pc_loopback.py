"""Tests for the PC audio-loopback-plug stereo diagnostic (prototype-plan.md Test 1 "Hardware
status" -- corroborating/refuting BurnInTest's "corrupt audio input on left channel" verdict).
"""

from __future__ import annotations

import numpy as np
import pytest

from overdub_analysis.pc_loopback import (
    CHIRP_DURATION_S,
    build_test_signal,
    diagnose_stereo_capture,
    left_template,
    right_template,
)
from overdub_analysis.synth import add_noise_at_snr

RATE = 48000


def test_templates_are_distinct_and_bounded() -> None:
    left = left_template(RATE)
    right = right_template(RATE)
    assert left.size == right.size == round(RATE * CHIRP_DURATION_S)
    assert np.max(np.abs(left)) <= 0.9 + 1e-12
    assert np.max(np.abs(right)) <= 0.9 + 1e-12
    # Hann-windowed: near-zero at both ends.
    assert abs(left[0]) < 1e-6 and abs(left[-1]) < 1e-6
    # Genuinely different signals (different bands), not accidentally identical.
    assert not np.allclose(left, right)


def test_build_test_signal_layout() -> None:
    sig = build_test_signal(RATE)
    assert sig.left.shape == sig.right.shape
    assert sig.onset_sample == round(RATE * 0.5)
    # Pre-onset region silent on both channels.
    assert np.all(sig.left[: sig.onset_sample] == 0.0)
    assert np.all(sig.right[: sig.onset_sample] == 0.0)


def _place(template: np.ndarray, total_len: int, onset: int) -> np.ndarray:
    out = np.zeros(total_len)
    out[onset : onset + template.size] = template
    return out


def test_correctly_wired_channels_read_ok() -> None:
    rng = np.random.default_rng(1)
    sig = build_test_signal(RATE)
    total = sig.left.size
    captured_left = add_noise_at_snr(_place(left_template(RATE), total, sig.onset_sample), 20.0, rng)
    captured_right = add_noise_at_snr(_place(right_template(RATE), total, sig.onset_sample), 20.0, rng)

    left_v, right_v = diagnose_stereo_capture(captured_left, captured_right, RATE, sig)
    assert left_v.verdict == "ok"
    assert right_v.verdict == "ok"
    assert abs(left_v.own_offset_ms) < 1.0
    assert abs(right_v.own_offset_ms) < 1.0


def test_swapped_channels_are_detected() -> None:
    """The left recording actually carries the RIGHT channel's chirp, and vice versa --
    exactly the signature a CTIA/OMTP pin-standard mismatch would produce."""
    rng = np.random.default_rng(2)
    sig = build_test_signal(RATE)
    total = sig.left.size
    captured_left = add_noise_at_snr(_place(right_template(RATE), total, sig.onset_sample), 20.0, rng)
    captured_right = add_noise_at_snr(_place(left_template(RATE), total, sig.onset_sample), 20.0, rng)

    left_v, right_v = diagnose_stereo_capture(captured_left, captured_right, RATE, sig)
    assert left_v.verdict == "swapped"
    assert right_v.verdict == "swapped"


def test_silent_channel_reads_no_signal() -> None:
    rng = np.random.default_rng(3)
    sig = build_test_signal(RATE)
    total = sig.left.size
    captured_left = rng.standard_normal(total) * 1e-4  # near-silent noise floor, no chirp at all
    captured_right = add_noise_at_snr(_place(right_template(RATE), total, sig.onset_sample), 20.0, rng)

    left_v, right_v = diagnose_stereo_capture(captured_left, captured_right, RATE, sig)
    assert left_v.verdict == "no-signal"
    assert right_v.verdict == "ok"


def test_crosstalk_without_margin_is_ambiguous_not_ok() -> None:
    """A channel carrying BOTH templates at comparable strength is real crosstalk, not a clean
    swap -- it must not be misreported as "ok" just because its own template is present."""
    rng = np.random.default_rng(4)
    sig = build_test_signal(RATE)
    total = sig.left.size
    both = _place(left_template(RATE), total, sig.onset_sample) + _place(
        right_template(RATE), total, sig.onset_sample
    )
    captured_left = add_noise_at_snr(both, 20.0, rng)
    captured_right = add_noise_at_snr(_place(right_template(RATE), total, sig.onset_sample), 20.0, rng)

    left_v, right_v = diagnose_stereo_capture(captured_left, captured_right, RATE, sig)
    assert left_v.verdict == "ambiguous"
    assert right_v.verdict == "ok"


def test_rejects_rate_too_low_for_chirp() -> None:
    with pytest.raises(ValueError):
        left_template(10)
