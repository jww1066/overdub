"""Stereo per-channel diagnostic for a physical PC audio-loopback plug.

Why this exists: BurnInTest's Sound Test flagged "corrupt audio input on left channel" when
testing the PassMark TRRS loopback plug directly on a PC (prototype-plan.md Test 1 "Hardware
status" -- the plug/adapter used for the phone's electrical-loopback rig). Rather than trust a
third-party black-box verdict, corroborate it with the same kind of instrument this repo already
validated for Test 2: a matched-filter chirp detector (`overdub_analysis.calibration_click`), not
BurnInTest's own undocumented distortion analysis.

Two DISTINCT, non-overlapping-band chirps -- one nominally routed to the left output channel, one
to the right -- let a single simultaneous stereo play+record distinguish the failure modes that
matter on ONE recording:

    - a channel with no usable signal at all (neither template detects above the quality floor)
    - channels swapped by a wiring-standard mismatch (a channel's recording matches the OTHER
      channel's template, not its own)
    - genuine corruption/high noise (a real but degraded signal: quality above the floor but not
      cleanly separated from the cross-channel score)

This deliberately does not measure round-trip latency/offset -- a same-machine PC loopback has no
meaningful "round trip" to speak of; only per-channel signal identity/integrity matters here.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .calibration_click import detect_click

__all__ = [
    "LEFT_F_LO_HZ",
    "LEFT_F_HI_HZ",
    "RIGHT_F_LO_HZ",
    "RIGHT_F_HI_HZ",
    "CHIRP_DURATION_S",
    "PRE_SILENCE_S",
    "POST_SILENCE_S",
    "QUALITY_FLOOR_DB",
    "CROSSTALK_MARGIN_DB",
    "left_template",
    "right_template",
    "StereoTestSignal",
    "build_test_signal",
    "ChannelVerdict",
    "diagnose_stereo_capture",
]

# Non-overlapping bands so a matched filter for one template gives a low response against the
# other channel's recording UNLESS that channel is actually carrying the wrong signal (a wiring
# swap) -- band separation, not just chirp direction, is what makes that discrimination robust.
LEFT_F_LO_HZ = 500.0
LEFT_F_HI_HZ = 1500.0
RIGHT_F_LO_HZ = 2500.0
RIGHT_F_HI_HZ = 4000.0
CHIRP_DURATION_S = 0.020
CHIRP_AMPLITUDE = 0.9

# Enough silence before the chirp to see a clean noise floor, and after it to rule out any tail/
# ringing artifacts before the recording ends -- this is a single one-shot test, not a sweep.
PRE_SILENCE_S = 0.5
POST_SILENCE_S = 1.0
TOTAL_DURATION_S = PRE_SILENCE_S + CHIRP_DURATION_S + POST_SILENCE_S

# A channel scores "ok" only if its own template beats the floor AND beats the other channel's
# template by this margin -- without the margin, a channel picking up both signals at similar
# strength (real crosstalk, not a clean swap) would misleadingly read as "ok".
QUALITY_FLOOR_DB = 10.0
CROSSTALK_MARGIN_DB = 6.0


def _chirp(f_lo: float, f_hi: float, duration_s: float, rate: int, amplitude: float) -> np.ndarray:
    """Hann-windowed linear chirp -- same construction as `calibration_click.click_template`,
    parameterized so two spectrally-distinct instances can be generated for left/right."""
    n = round(rate * duration_s)
    if n < 2:
        raise ValueError(f"rate {rate} too low for a {duration_s}s chirp")
    t = np.arange(n) / float(rate)
    phase = 2.0 * np.pi * (f_lo * t + (f_hi - f_lo) * t**2 / (2.0 * duration_s))
    return amplitude * np.hanning(n) * np.sin(phase)


def left_template(rate: int) -> np.ndarray:
    return _chirp(LEFT_F_LO_HZ, LEFT_F_HI_HZ, CHIRP_DURATION_S, rate, CHIRP_AMPLITUDE)


def right_template(rate: int) -> np.ndarray:
    return _chirp(RIGHT_F_LO_HZ, RIGHT_F_HI_HZ, CHIRP_DURATION_S, rate, CHIRP_AMPLITUDE)


@dataclass(frozen=True)
class StereoTestSignal:
    """Two mono channels to play simultaneously (e.g. as columns of a play buffer).

    ``left``/``right`` are equal-length; the chirp starts at ``onset_sample`` in both.
    """

    left: np.ndarray
    right: np.ndarray
    onset_sample: int


def build_test_signal(rate: int) -> StereoTestSignal:
    """Build the silence-chirp-silence signal for both channels at ``rate``."""
    pre = round(rate * PRE_SILENCE_S)
    post = round(rate * POST_SILENCE_S)
    left = np.concatenate([np.zeros(pre), left_template(rate), np.zeros(post)])
    right = np.concatenate([np.zeros(pre), right_template(rate), np.zeros(post)])
    return StereoTestSignal(left=left, right=right, onset_sample=pre)


@dataclass(frozen=True)
class ChannelVerdict:
    """Diagnostic outcome for one recorded channel.

    ``own_quality_db``/``cross_quality_db`` are the matched-filter quality (Test 2's PSR-style
    metric) of this channel's recording against its OWN expected template and against the OTHER
    channel's template, respectively. ``verdict`` is one of:

        "ok"            -- own template detected, clearly beating the cross template
        "swapped"       -- the OTHER channel's template is what's actually present here
        "no-signal"     -- neither template detected above the quality floor (silent, or the
                            signal is so degraded/corrupted the matched filter can't recognize it
                            as either known chirp -- this diagnostic can't further distinguish the
                            two; a low-but-present recorded RMS captured separately points to
                            "corrupted" over "silent")
        "ambiguous"     -- something detected, but not cleanly on one side of the margin
    """

    channel: str
    own_quality_db: float
    own_offset_ms: float
    cross_quality_db: float
    verdict: str


def _diagnose_one(
    captured: np.ndarray,
    rate: int,
    own_template: np.ndarray,
    cross_template: np.ndarray,
    expected_onset: int,
    channel: str,
    quality_floor_db: float,
    crosstalk_margin_db: float,
) -> ChannelVerdict:
    own = detect_click(captured, rate, template=own_template)
    cross = detect_click(captured, rate, template=cross_template)
    own_offset_ms = 1000.0 * (own.onset_sample - expected_onset) / rate

    own_ok = own.quality_db >= quality_floor_db
    cross_ok = cross.quality_db >= quality_floor_db
    if own_ok and own.quality_db - cross.quality_db >= crosstalk_margin_db:
        verdict = "ok"
    elif cross_ok and cross.quality_db - own.quality_db >= crosstalk_margin_db:
        verdict = "swapped"
    elif not own_ok and not cross_ok:
        verdict = "no-signal"
    else:
        verdict = "ambiguous"

    return ChannelVerdict(
        channel=channel,
        own_quality_db=own.quality_db,
        own_offset_ms=own_offset_ms,
        cross_quality_db=cross.quality_db,
        verdict=verdict,
    )


def diagnose_stereo_capture(
    captured_left: np.ndarray,
    captured_right: np.ndarray,
    rate: int,
    test_signal: StereoTestSignal,
    *,
    quality_floor_db: float = QUALITY_FLOOR_DB,
    crosstalk_margin_db: float = CROSSTALK_MARGIN_DB,
) -> tuple[ChannelVerdict, ChannelVerdict]:
    """Diagnose both recorded channels against the played `test_signal`.

    Returns ``(left_verdict, right_verdict)``, each judged against BOTH templates so a wiring
    swap (this channel is carrying the other one's signal) is distinguishable from a channel
    that simply has no usable signal.
    """
    l_tmpl = left_template(rate)
    r_tmpl = right_template(rate)
    left_v = _diagnose_one(
        captured_left, rate, l_tmpl, r_tmpl, test_signal.onset_sample, "left",
        quality_floor_db, crosstalk_margin_db,
    )
    right_v = _diagnose_one(
        captured_right, rate, r_tmpl, l_tmpl, test_signal.onset_sample, "right",
        quality_floor_db, crosstalk_margin_db,
    )
    return left_v, right_v
