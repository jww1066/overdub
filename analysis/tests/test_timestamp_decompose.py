"""Tests for overdub_analysis.timestamp_decompose (test2-step2-plan.md item 13 (a)).

The synthetic fixtures build a healthy 8-run cluster with realistic per-session start jitter and
inject a known ~40 ms glitch into exactly one raw value of a ninth run; the attribution must name
that value's characteristic component subset and nothing else. The regression fixture pins the
recomposition arithmetic to a real Session A sidecar (StreamOffset.kt's convention).
"""

from __future__ import annotations

import pytest

from overdub_analysis.timestamp_decompose import (
    TimestampRun,
    attribute_outliers,
    interpret,
)

FS = 48000
#: Per-session start-jitter (ms), deterministic stand-in for the real harness jitter.
JITTER_MS = [0.0, 3.0, -2.0, 5.0, 1.0, -4.0, 2.0, 6.0]
#: Fixed monotonic-minus-wall clock offset (ns) -- constant within a boot.
MONO_WALL_OFFSET_NS = 7_000_000_000_000
#: Fixed basis constant: stream_offset - click_offset for a healthy run (Pixel 10 measures ~-15).
BASIS_MS = -15.0


def _healthy_run(i: int, jitter_ms: float) -> TimestampRun:
    """One synthetic session with true stream offset (-80 + jitter) ms and consistent raw values."""
    true_offset_ms = -80.0 + jitter_ms
    wall_ms = 1_000_000.0 + i * 20_000.0
    read_nanos = (wall_ms + 16_400.0) * 1e6 + MONO_WALL_OFFSET_NS  # read ~16.4 s after the stamp
    t_out = read_nanos
    t_in = read_nanos + 500_000.0  # input read 0.5 ms after output
    clock_delta_ms = (t_out - t_in) / 1e6  # -0.5
    p_out = 786_000.0 + i * 10.0
    p_in = p_out + FS * (true_offset_ms - clock_delta_ms) / 1000.0
    wav_frames = int(p_in) - 4_800  # ~100 ms ring occupancy at the read point
    return TimestampRun(
        label=f"run{i}",
        sample_rate=FS,
        output_frames=p_out,
        output_nanos=t_out,
        input_frames=p_in,
        input_nanos=t_in,
        wall_ms=wall_ms,
        wav_frames=wav_frames,
        click_offset_ms=true_offset_ms - BASIS_MS,
    )


def _cluster() -> list[TimestampRun]:
    return [_healthy_run(i, j) for i, j in enumerate(JITTER_MS)]


def test_recomposition_matches_real_sidecar():
    """Regression: the recomputed offset must equal the sidecar value byte-for-byte in spirit.

    Raw values from recapture_session_a/conversational_armslength_faceup_none_1783541243390.json,
    whose harness-computed stream_offset_ms is -78.445729.
    """
    run = TimestampRun(
        label="regression",
        sample_rate=48000,
        output_frames=786960,
        output_nanos=293380154221695,
        input_frames=784944,
        input_nanos=293380190667424,
    )
    assert run.frame_delta_ms == pytest.approx(-42.0)
    assert run.clock_delta_ms == pytest.approx(-36.445729)
    assert run.stream_offset_ms == pytest.approx(-78.445729, abs=1e-6)


def test_healthy_cluster_yields_no_outliers():
    result = attribute_outliers(_cluster())
    assert result.discriminant == "stream_minus_click_ms"
    assert result.attributions == ()
    assert len(result.cluster_labels) == len(JITTER_MS)


def test_input_frame_position_glitch_is_attributed():
    runs = _cluster()
    base = _healthy_run(8, 1.0)
    glitched = TimestampRun(
        label="glitched",
        sample_rate=FS,
        output_frames=base.output_frames,
        output_nanos=base.output_nanos,
        input_frames=base.input_frames + FS * 40 / 1000.0,  # +40 ms of phantom input frames
        input_nanos=base.input_nanos,
        wall_ms=base.wall_ms,
        wav_frames=base.wav_frames,  # the WAV reflects reality, not the glitched report
        click_offset_ms=base.click_offset_ms,
    )
    runs.append(glitched)

    result = attribute_outliers(runs)
    assert [a.label for a in result.attributions] == ["glitched"]
    attribution = result.attributions[0]
    assert attribution.discriminant_deviation_ms == pytest.approx(40.0, abs=1.0)
    assert set(attribution.flagged_components) == {"frame_delta_ms", "input_minus_wav_ms"}
    assert "input framePosition glitch" in interpret(attribution)


def test_input_nanotime_glitch_is_attributed():
    runs = _cluster()
    base = _healthy_run(8, 1.0)
    glitched = TimestampRun(
        label="glitched",
        sample_rate=FS,
        output_frames=base.output_frames,
        output_nanos=base.output_nanos,
        input_frames=base.input_frames,
        input_nanos=base.input_nanos - 40e6,  # input clock reads 40 ms early
        wall_ms=base.wall_ms,
        wav_frames=base.wav_frames,
        click_offset_ms=base.click_offset_ms,
    )
    runs.append(glitched)

    result = attribute_outliers(runs)
    assert [a.label for a in result.attributions] == ["glitched"]
    attribution = result.attributions[0]
    assert attribution.discriminant_deviation_ms == pytest.approx(40.0, abs=1.0)
    assert set(attribution.flagged_components) == {"clock_delta_ms", "input_anchor_ms"}
    assert "input nanoTime glitch" in interpret(attribution)


def test_falls_back_to_raw_offset_without_click():
    runs = [
        TimestampRun(
            label=r.label,
            sample_rate=r.sample_rate,
            output_frames=r.output_frames,
            output_nanos=r.output_nanos,
            input_frames=r.input_frames,
            input_nanos=r.input_nanos,
            wall_ms=r.wall_ms,
            wav_frames=r.wav_frames,
            click_offset_ms=None,
        )
        for r in _cluster()
    ]
    base = _healthy_run(8, 1.0)
    runs.append(
        TimestampRun(
            label="glitched",
            sample_rate=FS,
            output_frames=base.output_frames,
            output_nanos=base.output_nanos,
            input_frames=base.input_frames + FS * 40 / 1000.0,
            input_nanos=base.input_nanos,
            wall_ms=base.wall_ms,
            wav_frames=base.wav_frames,
            click_offset_ms=None,
        )
    )

    # Without the click, the discriminant is the raw offset, which carries the +/-6 ms
    # start jitter -- so the outlier threshold must sit above the jitter, unlike the
    # click-anchored default. (This is why the click discriminant is preferred.)
    result = attribute_outliers(runs, outlier_threshold_ms=10.0)
    assert result.discriminant == "stream_offset_ms"
    assert [a.label for a in result.attributions] == ["glitched"]
    assert set(result.attributions[0].flagged_components) == {
        "frame_delta_ms",
        "input_minus_wav_ms",
    }


def test_too_few_runs_raises():
    with pytest.raises(ValueError):
        attribute_outliers(_cluster()[:3])


def test_no_flag_interpretation_falls_back():
    runs = _cluster()
    # An outlier whose error is split across frame and clock in sub-threshold pieces would
    # flag nothing; simulate by demanding a huge flag threshold on a real glitch.
    base = _healthy_run(8, 1.0)
    runs.append(
        TimestampRun(
            label="glitched",
            sample_rate=FS,
            output_frames=base.output_frames,
            output_nanos=base.output_nanos,
            input_frames=base.input_frames + FS * 40 / 1000.0,
            input_nanos=base.input_nanos,
            wall_ms=base.wall_ms,
            wav_frames=base.wav_frames,
            click_offset_ms=base.click_offset_ms,
        )
    )
    result = attribute_outliers(runs, flag_threshold_ms=100.0)
    assert result.attributions[0].flagged_components == ()
    assert "no reliable single-component attribution" in interpret(result.attributions[0])


def test_noisy_referent_cannot_flag():
    """A component whose own cluster spread rivals the anomaly must not attribute it.

    This is the Session A reality: WAV length / wall anchors jitter by tens of ms benignly,
    so a 40 ms glitch deviation on them is noise, not a culprit.
    """
    runs = _cluster()
    base = _healthy_run(8, 1.0)
    runs.append(
        TimestampRun(
            label="glitched",
            sample_rate=FS,
            output_frames=base.output_frames,
            output_nanos=base.output_nanos,
            input_frames=base.input_frames + FS * 40 / 1000.0,
            input_nanos=base.input_nanos,
            wall_ms=base.wall_ms,
            wav_frames=base.wav_frames,
            click_offset_ms=base.click_offset_ms,
        )
    )
    # With a flag threshold below the frame_delta cluster spread (~3.7 ms scaled MAD from the
    # +/-6 ms jitter), frame_delta becomes an unreliable referent and must drop out, leaving
    # only the zero-spread input_minus_wav check.
    result = attribute_outliers(runs, flag_threshold_ms=2.0)
    assert set(result.attributions[0].flagged_components) == {"input_minus_wav_ms"}
