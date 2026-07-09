"""Offline NLMS echo cancellation (design-summary.md "Echo cancellation for v1").

The bleed-mix listening test (2026-07-09) decided echo cancellation is v1
work with a rough suppression target of ~12 dB: a speaker-route overdub stem
carries reference bleed ~12 dB above the vocal in-band, and the first
listening-ladder rung that auditioned as acceptable attenuated the bleed
12 dB. The mechanism the design contemplates is offline, on-device NLMS
adaptive filtering (Sondhi & Berkley 1980) using the *exact clean reference
stem* as the far-end signal -- there is no real-time deadline, and the
measured alignment offset constrains where the echo path sits.

This module is the feasibility prototype for that mechanism: can NLMS with
the exact reference actually reach ~12 dB of in-band bleed suppression on a
real Pixel 10 speaker->mic capture? `analysis/scripts/run_echo_cancel_eval.py`
is the driver that composes it with the existing click gate and alignment.

Model and conventions
---------------------
NLMS models the capture (near-end, ``d``) as a causal FIR filtering of the
reference (far-end, ``x``)::

    d[n] ~= sum_k  h[k] * x[n - k],   k in [0, num_taps)

so the caller must present the pair with the echo path *causal and inside
the filter span*: the reference sample that produced capture sample ``n``
must sit at ``x[n - k]`` for some ``0 <= k < num_taps``. The driver arranges
this by shifting the capture onto the reference clock *minus a guard delay*
(the measured alignment offset has +/-2 ms error, and the alignment could
make the path marginally acausal without the guard).

Offline adaptation runs multiple ``passes`` over the same take with weights
carried across passes: the echo path is time-invariant within a take, so a
first pass converges the filter and the final pass's output is free of the
initial adaptation transient. This is exactly what "offline" buys over
real-time NLMS -- the product would do the same (adapt over the take, keep
the last pass's residual).

The residual is ``capture - echo_estimate``. Any component of the capture
uncorrelated with the reference (the performer's vocal, room noise) passes
through untouched by construction -- the echo estimate is built from the
reference alone; near-end signal affects only the *adaptation* (weight
misadjustment), i.e. how much bleed survives.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from overdub_analysis.vocal_inject import inband_rms

__all__ = [
    "NlmsResult",
    "nlms",
    "suppression_db",
    "suppression_profile",
    "tail_energy_fraction",
]


@dataclass(frozen=True)
class NlmsResult:
    """Result of an offline NLMS run.

    Attributes
    ----------
    residual :
        ``capture - echo_estimate`` from the final pass -- the echo-cancelled
        signal.
    echo_estimate :
        The filter's reconstruction of the echo (bleed) from the final pass.
    impulse_response :
        Final weights in impulse-response order: ``impulse_response[k]`` is
        the estimated echo-path coefficient at delay ``k`` samples.
    passes :
        Number of adaptation passes run.
    """

    residual: np.ndarray
    echo_estimate: np.ndarray
    impulse_response: np.ndarray
    passes: int


def nlms(
    reference: np.ndarray,
    capture: np.ndarray,
    *,
    num_taps: int,
    mu: float = 0.5,
    eps_rel: float = 1e-3,
    passes: int = 2,
) -> NlmsResult:
    """Cancel the reference's echo out of ``capture`` via offline NLMS.

    Parameters
    ----------
    reference :
        Far-end signal (the exact clean stem that was played). Same length as
        ``capture``; the caller has already placed the echo path causally
        within the filter span (see module docstring).
    capture :
        Near-end signal (bleed + anything uncorrelated with the reference).
    num_taps :
        FIR filter length in samples. Must cover the guard delay plus the
        echo path's multipath/reverb spread; check
        :func:`tail_energy_fraction` afterwards to confirm it was enough.
    mu :
        NLMS step size, in (0, 2). 0.5 is a conventional stable default.
    eps_rel :
        Regularization relative to the reference's mean power:
        ``eps = eps_rel * num_taps * mean(reference**2)``. Prevents unbounded
        updates during near-silent reference stretches.
    passes :
        Adaptation passes over the take, weights carried across passes; the
        returned signals come from the final pass.
    """
    x = np.asarray(reference, dtype=np.float64).ravel()
    d = np.asarray(capture, dtype=np.float64).ravel()
    if x.size != d.size:
        raise ValueError(f"reference ({x.size}) and capture ({d.size}) lengths differ")
    if num_taps < 1:
        raise ValueError(f"num_taps must be >= 1 (got {num_taps})")
    if x.size < num_taps:
        raise ValueError(f"signal ({x.size}) shorter than num_taps ({num_taps})")
    if not 0.0 < mu < 2.0:
        raise ValueError(f"mu must be in (0, 2) (got {mu})")
    if passes < 1:
        raise ValueError(f"passes must be >= 1 (got {passes})")

    n_samples = x.size
    # xpad lets the window at sample n be xpad[n : n + num_taps], i.e.
    # x[n - num_taps + 1 .. n] with implicit zeros before the start.
    xpad = np.concatenate([np.zeros(num_taps - 1), x])
    w = np.zeros(num_taps)
    eps = eps_rel * num_taps * float(np.mean(x * x)) + np.finfo(np.float64).tiny

    y = np.empty(n_samples)
    e = np.empty(n_samples)
    for _ in range(passes):
        # Sliding window norm, updated incrementally (clamped at 0 against
        # float drift over long takes).
        norm = float(np.dot(xpad[:num_taps], xpad[:num_taps]))
        for n in range(n_samples):
            win = xpad[n : n + num_taps]
            yn = float(np.dot(w, win))
            en = d[n] - yn
            w += (mu * en / (eps + norm)) * win
            y[n] = yn
            e[n] = en
            if n + 1 < n_samples:
                norm = max(0.0, norm + xpad[n + num_taps] ** 2 - xpad[n] ** 2)

    # w[k] multiplies win[k] = x[n - (num_taps - 1 - k)], so reversing w gives
    # the impulse response indexed by delay.
    return NlmsResult(
        residual=e,
        echo_estimate=y,
        impulse_response=w[::-1].copy(),
        passes=passes,
    )


def suppression_db(
    before: np.ndarray, after: np.ndarray, rate: int, lo: float, hi: float
) -> float:
    """In-band suppression: how far ``after`` sits below ``before``, in dB.

    Both signals are band-passed to ``lo``-``hi`` (the analysis band -- the
    band the bleed actually occupies and the listening-ladder rungs were
    rendered in), so the number is directly comparable to the ~12 dB
    listening-test target. Positive = energy was removed.
    """
    b = inband_rms(before, rate, lo, hi)
    a = inband_rms(after, rate, lo, hi)
    if a <= 0.0 or b <= 0.0:
        return float("inf") if b > a else 0.0
    return float(20.0 * np.log10(b / a))


def suppression_profile(
    before: np.ndarray,
    after: np.ndarray,
    rate: int,
    lo: float,
    hi: float,
    *,
    window_s: float = 1.0,
) -> list[tuple[float, float]]:
    """Per-window suppression over time: ``[(window_start_s, suppression_db)]``.

    Shows whether the filter is converged across the take (a flat profile) or
    still adapting (suppression climbing through the take) -- the honest way
    to report a single suppression number is alongside this profile.
    """
    if before.size != after.size:
        raise ValueError("before/after lengths differ")
    win = int(round(window_s * rate))
    if win < 1:
        raise ValueError(f"window_s {window_s} too small for rate {rate}")
    out: list[tuple[float, float]] = []
    for start in range(0, before.size - win + 1, win):
        seg_b = before[start : start + win]
        seg_a = after[start : start + win]
        out.append((start / rate, suppression_db(seg_b, seg_a, rate, lo, hi)))
    return out


def tail_energy_fraction(impulse_response: np.ndarray, tail_frac: float = 0.1) -> float:
    """Fraction of the estimated path's energy in its final ``tail_frac`` of taps.

    A filter long enough for the real echo path decays before its end; if the
    last taps still hold a meaningful share of the energy (say > ~5%), the
    path's reverb tail was truncated and ``num_taps`` should be raised before
    trusting the suppression number.
    """
    h = np.asarray(impulse_response, dtype=np.float64).ravel()
    total = float(np.dot(h, h))
    if total <= 0.0:
        return 0.0
    n_tail = max(1, int(round(tail_frac * h.size)))
    tail = h[-n_tail:]
    return float(np.dot(tail, tail) / total)
