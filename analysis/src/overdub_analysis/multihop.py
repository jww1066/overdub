"""Test 3 multi-hop alignment-error Monte Carlo (doc/prototype-plan.md Test 3, revised).

Under the raw-stem decision every hop aligns against the *original* reference,
so per-hop noise does not chain: track k's timing error vs the shared
reference is an independent draw e_k, and the misalignment between any two
tracks i and j is |e_i - e_j|. What genuinely worsens with chain length is
(a) per-device systematic bias differences (the moto g(20) timestamp class),
and (b) interference growth with hop position — hop k correlates through the
bleed of k-1 other stems. This module draws per-track errors under that model
and reports the max pairwise offset per trial; the gate is the 95th
percentile at N=4 staying <= 15 ms.

Error model per overdub track k (k = 0..N-1, hop position in the chain):

    e_k = b_k + n_k + median(m timestamp-read errors)

  * ``b_k`` — per-device systematic bias, uniform in
    [-bias_half_range_ms, +bias_half_range_ms]. A *placeholder distribution*
    until a second device's data exists (prototype-plan.md); the useful output
    is therefore the *critical* half-range at which the gate fails, i.e. a
    requirement on the unknown, not a verdict about it.
  * ``n_k`` — per-hop alignment noise, N(0, noise_std_ms * growth^k). Session A
    measured std 0.31 ms for the click-anchored correlator; the vocal study
    (uncorrelated in-band interference does not move the offset) supports a
    flat schedule (growth = 1.0), but the growth knob exists for when
    correlated multi-stem bleed data says otherwise.
  * the read-median term — only for the timestamp mechanism (headphone path):
    each of ``reads_per_track`` reads is N(0, read_noise_std_ms) plus, with
    ``outlier_prob``, a displacement of ``outlier_ms`` (random sign when
    ``outlier_signed``); the track uses the median of its reads. Session A
    observed 1 outlier of ~+40 ms in 9 sessions (read noise ~0.25 ms), so the
    defaults mirror that single observation — a rate with huge uncertainty,
    which is why the driver sweeps it.

The original/reference track is itself part of the mix with zero error by
construction; ``include_reference_track=True`` (default) appends that zero
column before taking the pairwise range, so "max pairwise" includes pairs
with the original.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["HopModel", "simulate_track_errors", "max_pairwise_offset"]


@dataclass(frozen=True)
class HopModel:
    """Per-hop error-model parameters (all times in milliseconds)."""

    bias_half_range_ms: float = 0.0
    noise_std_ms: float = 0.31
    noise_growth_per_hop: float = 1.0
    outlier_prob: float = 0.0
    outlier_ms: float = 39.6
    outlier_signed: bool = True
    reads_per_track: int = 1
    read_noise_std_ms: float = 0.0

    def __post_init__(self) -> None:
        if self.bias_half_range_ms < 0:
            raise ValueError("bias_half_range_ms must be >= 0")
        if self.noise_std_ms < 0 or self.read_noise_std_ms < 0:
            raise ValueError("noise stds must be >= 0")
        if not 0.0 <= self.outlier_prob <= 1.0:
            raise ValueError("outlier_prob must be in [0, 1]")
        if self.reads_per_track < 1:
            raise ValueError("reads_per_track must be >= 1")
        if self.noise_growth_per_hop <= 0:
            raise ValueError("noise_growth_per_hop must be > 0")


def simulate_track_errors(
    model: HopModel, n_tracks: int, trials: int, rng: np.random.Generator
) -> np.ndarray:
    """Draw per-track alignment errors vs the shared reference.

    Returns a ``(trials, n_tracks)`` array in ms. Track index is hop position
    (0 = first overdub), which the noise-growth schedule keys on.
    """
    if n_tracks < 1:
        raise ValueError("n_tracks must be >= 1")
    if trials < 1:
        raise ValueError("trials must be >= 1")

    shape = (trials, n_tracks)
    b = model.bias_half_range_ms
    bias = rng.uniform(-b, b, shape) if b > 0 else np.zeros(shape)

    stds = model.noise_std_ms * model.noise_growth_per_hop ** np.arange(n_tracks)
    noise = rng.standard_normal(shape) * stds[np.newaxis, :]

    m = model.reads_per_track
    reads = rng.standard_normal((trials, n_tracks, m)) * model.read_noise_std_ms
    if model.outlier_prob > 0.0:
        hit = rng.random((trials, n_tracks, m)) < model.outlier_prob
        if model.outlier_signed:
            signs = rng.choice([-1.0, 1.0], size=(trials, n_tracks, m))
        else:
            signs = np.ones((trials, n_tracks, m))
        reads = reads + hit * signs * model.outlier_ms
    read_term = np.median(reads, axis=2)

    return bias + noise + read_term


def max_pairwise_offset(
    errors: np.ndarray, *, include_reference_track: bool = True
) -> np.ndarray:
    """Per-trial max pairwise misalignment (ms) — the range of the track errors.

    ``max_{i,j} |e_i - e_j| = max(e) - min(e)``. With
    ``include_reference_track`` the original track participates with error 0,
    so the range is taken over the track errors plus a zero.
    """
    e = np.asarray(errors, dtype=np.float64)
    if e.ndim != 2:
        raise ValueError("errors must be a (trials, n_tracks) array")
    hi = e.max(axis=1)
    lo = e.min(axis=1)
    if include_reference_track:
        hi = np.maximum(hi, 0.0)
        lo = np.minimum(lo, 0.0)
    return hi - lo
