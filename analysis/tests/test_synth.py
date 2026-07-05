"""Unit tests for the `synth` helpers, focused on `delay`'s edge cases.

`gcc_phat`'s own correctness is exercised end-to-end in `test_gcc_phat.py`;
these tests target `delay` in isolation since it has boundary behavior
(`abs(d) >= len(signal)`) that a delay-then-correlate test would never
exercise on its own.
"""

from __future__ import annotations

import numpy as np

from overdub_analysis import delay


def test_delay_positive_shifts_right_and_pads_front() -> None:
    s = np.arange(1.0, 6.0)  # [1, 2, 3, 4, 5]
    out = delay(s, 3)
    assert out.size == s.size + 3
    np.testing.assert_array_equal(out, [0, 0, 0, 1, 2, 3, 4, 5])


def test_delay_negative_shifts_left_and_pads_tail() -> None:
    s = np.arange(1.0, 6.0)  # [1, 2, 3, 4, 5]
    out = delay(s, -2)
    assert out.size == s.size + 2
    np.testing.assert_array_equal(out, [3, 4, 5, 0, 0, 0, 0])


def test_delay_negative_at_signal_length_is_all_zero() -> None:
    """|d| == len(signal): the shifted signal has just fully left the window."""
    s = np.arange(1.0, 6.0)
    out = delay(s, -5)
    assert out.size == s.size + 5
    assert np.all(out == 0.0)


def test_delay_negative_beyond_signal_length_is_all_zero() -> None:
    """|d| > len(signal): previously raised a numpy broadcast ValueError."""
    s = np.arange(1.0, 6.0)
    out = delay(s, -11)
    assert out.size == s.size + 11
    assert np.all(out == 0.0)
