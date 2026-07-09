"""Attribute a per-session ``getTimestamp`` stream-offset outlier to a specific raw component.

test2-step2-plan.md item 13 (a) / prototype-plan.md Test 1a "Interim timestamp-variance plan"
step 1. Session A (`test2-sweep-results.md` "Session A re-capture") observed 1 run in 9 whose
timestamp-derived stream offset disagreed with the calibration click by ~+40 ms (stream - click
residual +24.5 ms vs the -15.1 +/- 0.25 ms cluster of the other eight). Test 3's median-of-5
remedy rests on that outlier being a single-read glitch; *which* raw value glitched decides
whether a cheaper, stronger remedy exists (e.g. sanity-checking ``framePosition`` against the
elapsed capture length instead of taking k reads).

The sidecars carry the four raw values behind each derived offset:

    stream_offset = frame_delta + clock_delta
    frame_delta   = (input_frames - output_frames) / fs          (both ``framePosition``)
    clock_delta   = output_nanos - input_nanos                    (both ``nanoTime``, CLOCK_MONOTONIC)

plus two per-stream consistency checks that do not depend on the other stream:

    input_minus_wav  = input_frames - wav_frames    (input framePosition vs frames actually captured)
    output_minus_wav = output_frames - wav_frames   (output framePosition vs the same referent)
    *_anchor         = nanos vs the sidecar wall-clock stamp (monotonic-to-wall is constant within
                       a boot, so cross-run deviations expose a lying ``nanoTime``)

A glitch in one raw value flags a characteristic component subset (e.g. input ``framePosition``
flags ``frame_delta`` + ``input_minus_wav`` but leaves the clock components alone), which
:func:`interpret` maps to a named culprit. All arithmetic is pure so it is unit-testable; the CLI
that reads sidecars/WAVs/the click CSV is ``scripts/decompose_timestamp_outlier.py``.

Component values are reported in milliseconds throughout. Flagging requires the component to be
a *reliable discriminator*, not just deviant: it must deviate from the cluster median by more
than the absolute threshold AND by more than 3x the cluster's scaled MAD, AND the cluster spread
itself must sit below the threshold -- a referent whose benign run-to-run jitter is comparable to
the anomaly (e.g. the wall anchors at ~+/-40 ms, or the WAV length at ~15 ms) cannot attribute a
glitch of that size, and letting it flag would manufacture a false culprit. When *no* component
survives that rule, the honest verdict is that single-read sidecars under-determine the
attribution (the Session A outcome) -- the discriminating instrument is multi-read logging
(item 13 (b)): consecutive reads of one stream lie on a frame-vs-time line, so a single-read
glitch is directly visible as an off-line point with no cross-run referent needed.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

#: Components examined per run, in report order. Values in ms; see :class:`TimestampRun`.
COMPONENTS: tuple[str, ...] = (
    "frame_delta_ms",
    "clock_delta_ms",
    "input_minus_wav_ms",
    "output_minus_wav_ms",
    "wav_ms",
    "output_anchor_ms",
    "input_anchor_ms",
)

#: Robust-spread scale factor: median absolute deviation -> std-equivalent for a normal cluster.
_MAD_SCALE = 1.4826


@dataclass(frozen=True)
class TimestampRun:
    """One capture session's raw timestamp readings (from its JSON sidecar) plus referents.

    ``wall_ms`` is the sidecar's ``timestamp`` field (epoch ms; the harness stamps it once per
    capture, so monotonic-minus-wall anchors are comparable *across* runs, meaningless absolutely).
    ``wav_frames`` is the captured WAV's frame count. ``click_offset_ms`` is the calibration-click
    ground truth from ``run_click_gated_sweep.py``. All three are optional -- a run missing one
    simply skips the components that need it.
    """

    label: str
    sample_rate: int
    output_frames: float
    output_nanos: float
    input_frames: float
    input_nanos: float
    wall_ms: float | None = None
    wav_frames: int | None = None
    click_offset_ms: float | None = None

    @property
    def frame_delta_ms(self) -> float:
        """(input framePosition - output framePosition), as ms of audio."""
        return (self.input_frames - self.output_frames) / self.sample_rate * 1000.0

    @property
    def clock_delta_ms(self) -> float:
        """(output nanoTime - input nanoTime), ms."""
        return (self.output_nanos - self.input_nanos) / 1e6

    @property
    def stream_offset_ms(self) -> float:
        """Recomputed stream offset -- must match the sidecar's ``stream_offset_ms``.

        Same convention as the harness's ``computeStreamOffset`` (StreamOffset.kt):
        ``(p_in - p_out) + (t_out - t_in) * fs / 1e9``, expressed in ms (mic-lags-positive).
        """
        return self.frame_delta_ms + self.clock_delta_ms

    @property
    def stream_minus_click_ms(self) -> float | None:
        """Timestamp-derived offset minus click ground truth -- the basis residual.

        Stable across healthy runs (a fixed measurement-basis constant, ~-15.1 ms on the
        Pixel 10); a deviation here is a timestamp error, since the click is independent.
        """
        if self.click_offset_ms is None:
            return None
        return self.stream_offset_ms - self.click_offset_ms

    @property
    def wav_ms(self) -> float | None:
        """Captured WAV length, ms."""
        if self.wav_frames is None:
            return None
        return self.wav_frames / self.sample_rate * 1000.0

    @property
    def input_minus_wav_ms(self) -> float | None:
        """Input framePosition vs frames actually written to the WAV, ms.

        Ring occupancy at the read point makes this nonzero but roughly constant across runs;
        a large deviation means the input framePosition disagrees with the captured data itself.
        """
        if self.wav_frames is None:
            return None
        return (self.input_frames - self.wav_frames) / self.sample_rate * 1000.0

    @property
    def output_minus_wav_ms(self) -> float | None:
        """Output framePosition vs the captured WAV length, ms (same referent as the input check)."""
        if self.wav_frames is None:
            return None
        return (self.output_frames - self.wav_frames) / self.sample_rate * 1000.0

    @property
    def output_anchor_ms(self) -> float | None:
        """Output nanoTime minus the wall stamp, ms (cross-run comparable within one boot)."""
        if self.wall_ms is None:
            return None
        return self.output_nanos / 1e6 - self.wall_ms

    @property
    def input_anchor_ms(self) -> float | None:
        """Input nanoTime minus the wall stamp, ms (cross-run comparable within one boot)."""
        if self.wall_ms is None:
            return None
        return self.input_nanos / 1e6 - self.wall_ms

    def component(self, name: str) -> float | None:
        if name not in COMPONENTS:
            raise ValueError(f"unknown component: {name}")
        return getattr(self, name)


@dataclass(frozen=True)
class ComponentDeviation:
    """One component's value in an outlier run vs the healthy cluster."""

    component: str
    value_ms: float
    cluster_median_ms: float
    cluster_spread_ms: float  # scaled MAD of the cluster (std-equivalent)
    deviation_ms: float
    flagged: bool


@dataclass(frozen=True)
class OutlierAttribution:
    """An outlier run's discriminant deviation and its per-component breakdown."""

    label: str
    discriminant_deviation_ms: float
    deviations: tuple[ComponentDeviation, ...]

    @property
    def flagged_components(self) -> tuple[str, ...]:
        return tuple(d.component for d in self.deviations if d.flagged)


@dataclass(frozen=True)
class DecompositionResult:
    discriminant: str  # "stream_minus_click_ms" or "stream_offset_ms"
    cluster_labels: tuple[str, ...]
    attributions: tuple[OutlierAttribution, ...]


def _scaled_mad(values: list[float]) -> float:
    med = statistics.median(values)
    return _MAD_SCALE * statistics.median([abs(v - med) for v in values])


def attribute_outliers(
    runs: list[TimestampRun],
    outlier_threshold_ms: float = 5.0,
    flag_threshold_ms: float = 5.0,
) -> DecompositionResult:
    """Split runs into a healthy cluster and outliers, and attribute each outlier per component.

    Outliers are runs whose discriminant -- ``stream_minus_click_ms`` when every run carries a
    click offset (the click is independent ground truth), else the raw ``stream_offset_ms`` --
    deviates from the population median by more than ``outlier_threshold_ms``. Each outlier's
    components are then compared against the cluster's medians; a component is flagged when its
    deviation exceeds both ``flag_threshold_ms`` and 3x the cluster's scaled MAD (see module
    docstring for why both).
    """
    if len(runs) < 4:
        raise ValueError("attribute_outliers() needs at least 4 runs (3 cluster + 1 candidate)")

    if all(r.click_offset_ms is not None for r in runs):
        discriminant = "stream_minus_click_ms"
        values = [r.stream_minus_click_ms for r in runs]
    else:
        discriminant = "stream_offset_ms"
        values = [r.stream_offset_ms for r in runs]

    med = statistics.median(values)
    outliers = [r for r, v in zip(runs, values) if abs(v - med) > outlier_threshold_ms]
    cluster = [r for r, v in zip(runs, values) if abs(v - med) <= outlier_threshold_ms]
    if len(cluster) < 3:
        raise ValueError(
            f"only {len(cluster)} runs remain in the healthy cluster at "
            f"outlier_threshold_ms={outlier_threshold_ms} -- too few to form a baseline"
        )

    attributions: list[OutlierAttribution] = []
    for run, value in ((r, v) for r, v in zip(runs, values) if r in outliers):
        deviations: list[ComponentDeviation] = []
        for name in COMPONENTS:
            run_value = run.component(name)
            cluster_values = [c for c in (r.component(name) for r in cluster) if c is not None]
            if run_value is None or len(cluster_values) < 3:
                continue
            cluster_median = statistics.median(cluster_values)
            spread = _scaled_mad(cluster_values)
            deviation = run_value - cluster_median
            deviations.append(
                ComponentDeviation(
                    component=name,
                    value_ms=run_value,
                    cluster_median_ms=cluster_median,
                    cluster_spread_ms=spread,
                    deviation_ms=deviation,
                    flagged=abs(deviation) > flag_threshold_ms
                    and abs(deviation) > 3.0 * spread
                    and spread < flag_threshold_ms,
                )
            )
        attributions.append(
            OutlierAttribution(
                label=run.label,
                discriminant_deviation_ms=value - med,
                deviations=tuple(deviations),
            )
        )

    return DecompositionResult(
        discriminant=discriminant,
        cluster_labels=tuple(r.label for r in cluster),
        attributions=tuple(attributions),
    )


def interpret(attribution: OutlierAttribution) -> str:
    """Map an outlier's flagged-component subset to a named raw-value culprit (ASCII, one line).

    The mapping follows from the arithmetic: each raw value participates in a characteristic
    subset of components, so the flagged subset identifies it. Falls back to listing the flags
    verbatim when the pattern matches no single raw value.
    """
    flagged = set(attribution.flagged_components)
    if not flagged:
        return (
            "no reliable single-component attribution -- every referent's own cluster spread is "
            "comparable to the anomaly, so single-read sidecars under-determine the culprit. "
            "The discriminating instrument is multi-read logging (item 13 (b)): repeated reads "
            "of one stream lie on a frame-vs-time line, making a single-read glitch visible "
            "as an off-line point without any cross-run referent."
        )

    clock_side = {"clock_delta_ms", "output_anchor_ms", "input_anchor_ms"}
    frame_side = {"frame_delta_ms", "input_minus_wav_ms", "output_minus_wav_ms", "wav_ms"}

    if flagged == {"frame_delta_ms", "input_minus_wav_ms"}:
        return (
            "input framePosition glitch -- the input stream's reported frame count disagrees "
            "with both the output stream and the captured WAV, while every clock component is "
            "clean. Remedy candidate: sanity-check input framePosition against the elapsed "
            "capture length (cheaper and stronger than median-of-k)."
        )
    if flagged == {"frame_delta_ms", "output_minus_wav_ms"}:
        return (
            "output framePosition glitch -- the output stream's reported frame count disagrees "
            "with both the input stream and the captured WAV, while every clock component is "
            "clean. Remedy candidate: sanity-check output framePosition against the elapsed "
            "playback length (cheaper and stronger than median-of-k)."
        )
    if flagged == {"clock_delta_ms", "input_anchor_ms"}:
        return (
            "input nanoTime glitch -- the input stream's clock reading disagrees with the "
            "output stream's and with the wall anchor, while the frame components are clean."
        )
    if flagged == {"clock_delta_ms", "output_anchor_ms"}:
        return (
            "output nanoTime glitch -- the output stream's clock reading disagrees with the "
            "input stream's and with the wall anchor, while the frame components are clean."
        )
    if flagged == {"output_anchor_ms", "input_anchor_ms"}:
        return (
            "wall-clock stamp anomaly -- both anchors moved together while the stream-vs-stream "
            "components are clean; the sidecar 'timestamp' field, not the stream timestamps, "
            "moved (does not explain a stream-offset outlier by itself)."
        )
    if "wav_ms" in flagged and {"input_minus_wav_ms", "output_minus_wav_ms"} <= flagged:
        return (
            "capture-length anomaly -- the WAV itself is short/long, dragging both *_minus_wav "
            "checks; the framePositions agree with each other, so suspect the drain/write path, "
            "not getTimestamp."
        )
    if flagged <= clock_side:
        return f"clock-side anomaly, pattern {sorted(flagged)} -- inspect the deviation table"
    if flagged <= frame_side:
        return f"frame-side anomaly, pattern {sorted(flagged)} -- inspect the deviation table"
    return f"mixed pattern {sorted(flagged)} -- inspect the deviation table"
