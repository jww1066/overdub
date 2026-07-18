"""Calibration click: the in-basis ground-truth marker for Test 2's +/-2 ms bar.

Why this exists (doc/prototype-plan.md "Ground-truth correction", 2026-07-08):
Test 2's recovered-offset accuracy bar needs a ground truth in the *same
measurement basis* as the GCC-PHAT offset (the captured WAV's own sample
clock) and on the *same route* (built-in speaker -> built-in mic). The
loopback rig measures a different route in a different basis, so it cannot
serve. Instead a short, exactly-known chirp is prepended to the bundled
reference track; matched-filtering a capture against the known template --
an instrument independent of the GCC-PHAT correlator being judged -- gives a
per-capture ground truth:

    ground_truth_offset = detected onset in capture - CLICK_ONSET in reference

directly comparable to ``gcc_phat(reference, capture).offset_samples`` for
the same capture (same sign convention: positive = capture lags reference).

Design choices
--------------
- **Linear chirp, 500-4000 Hz, Hann-windowed, 20 ms.** Confined to the
  empirically usable speaker->mic band (doc/test2-sweep-results.md: speaker
  bass rolloff below ~500 Hz, mic-noise domination above ~4 kHz), so the
  acoustic path passes it. Matched filtering compresses the chirp into a
  sharp, unambiguous peak (a windowed *tone* would have cycle-level
  ambiguity), and spreading the energy over 20 ms buys detection SNR without
  clipping the speaker.
- **Exactly 1.000 s of lead-in** (0.200 s silence + 0.020 s chirp + 0.780 s
  silence) before the original signal. The round total makes it trivial for
  analyses to trim the lead-in and correlate beatbox-only content. Captures
  made with the *click-less* asset must be analyzed against a click-less
  reference -- against the new reference their offsets shift by the whole
  lead-in and land outside the plausible lag window.
- **Detection is polarity-insensitive** (peak of |matched filter|): an
  acoustic speaker->mic path may invert polarity, which must not flip the
  detected onset to a sidelobe.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import fftconvolve

__all__ = [
    "CLICK_F_LO_HZ",
    "CLICK_F_HI_HZ",
    "CLICK_DURATION_S",
    "PRE_SILENCE_S",
    "POST_SILENCE_S",
    "LEAD_IN_S",
    "CLICK_AMPLITUDE",
    "click_template",
    "prepend_click",
    "detect_click",
    "PrependResult",
    "ClickDetection",
]

# The single source of truth for the click's shape and placement. The prepend
# script and every future detector import these; do not restate the numbers
# elsewhere (doc/test2-step2-plan.md item 11).
CLICK_F_LO_HZ = 500.0
CLICK_F_HI_HZ = 4000.0
CLICK_DURATION_S = 0.020
PRE_SILENCE_S = 0.200
POST_SILENCE_S = 0.780
LEAD_IN_S = PRE_SILENCE_S + CLICK_DURATION_S + POST_SILENCE_S  # exactly 1.0 s
CLICK_AMPLITUDE = 0.9


@dataclass(frozen=True)
class PrependResult:
    """Signal with the calibration lead-in prepended.

    Attributes
    ----------
    samples :
        Lead-in (silence + chirp + silence) followed by the original signal.
    click_onset_sample :
        Index of the chirp's first sample (== PRE_SILENCE_S * rate).
    lead_in_samples :
        Total lead-in length; the original signal starts here (== LEAD_IN_S * rate).
    """

    samples: np.ndarray
    click_onset_sample: int
    lead_in_samples: int


@dataclass(frozen=True)
class ClickDetection:
    """Matched-filter detection of the calibration click in a capture.

    Attributes
    ----------
    onset_sample :
        Index in the capture where the chirp template starts.
    peak_value :
        Magnitude of the matched-filter output at the detected onset.
    quality_db :
        20*log10(peak / largest competing |peak| outside the exclusion
        window) -- a PSR-style trustworthiness metric. A capture that does
        not contain the click scores low; gate on this before trusting the
        onset (np.inf if nothing competes).
    """

    onset_sample: int
    peak_value: float
    quality_db: float


def click_template(rate: int) -> np.ndarray:
    """Return the calibration chirp at ``rate`` (Hann-windowed linear chirp).

    Deterministic function of ``rate`` and the module constants only, so the
    generator and any detector are guaranteed to use the identical waveform.
    """
    n = round(rate * CLICK_DURATION_S)
    if n < 2:
        raise ValueError(f"rate {rate} too low for a {CLICK_DURATION_S}s template")
    t = np.arange(n) / float(rate)
    # Linear chirp: instantaneous frequency f0 + (f1-f0)*t/T.
    phase = 2.0 * np.pi * (
        CLICK_F_LO_HZ * t
        + (CLICK_F_HI_HZ - CLICK_F_LO_HZ) * t**2 / (2.0 * CLICK_DURATION_S)
    )
    return CLICK_AMPLITUDE * np.hanning(n) * np.sin(phase)


def prepend_click(signal: np.ndarray, rate: int) -> PrependResult:
    """Return ``signal`` with the 1.0 s calibration lead-in prepended."""
    s = np.asarray(signal, dtype=np.float64).ravel()
    if s.size == 0:
        raise ValueError("signal must be non-empty")
    pre = round(rate * PRE_SILENCE_S)
    post = round(rate * POST_SILENCE_S)
    tmpl = click_template(rate)
    out = np.concatenate([np.zeros(pre), tmpl, np.zeros(post), s])
    return PrependResult(
        samples=out,
        click_onset_sample=pre,
        lead_in_samples=pre + tmpl.size + post,
    )


def detect_click(
    capture: np.ndarray,
    rate: int,
    *,
    template: np.ndarray | None = None,
    search_window: tuple[int | None, int | None] | None = None,
    quality_exclusion: int | None = None,
) -> ClickDetection:
    """Locate the calibration click in ``capture`` via matched filter.

    Parameters
    ----------
    capture :
        1-D signal expected to contain the click (possibly delayed,
        band-limited by the acoustic path, polarity-inverted, and noisy).
    rate :
        Sample rate; must match the rate the reference was generated at.
    template :
        Matched-filter template to search for. Defaults to ``click_template(rate)``
        (the canonical calibration click); callers that need a *different* known
        signal (e.g. `overdub_analysis.pc_loopback`'s distinct per-channel chirps)
        can pass their own template and reuse the same detection/quality logic.
    search_window :
        Optional ``(min_onset, max_onset)`` bound in samples restricting both
        the peak search and the competing-peak (quality) search -- same idea
        as ``gcc_phat``'s ``lag_window``: a capture's click onset is
        physically bounded (click position in reference + a plausible 0-300 ms
        round-trip), and constraining the search keeps late beatbox content
        from ever competing. Either endpoint may be ``None``.
    quality_exclusion :
        Half-width in samples of the region around the detected peak excluded
        from the competing-peak search. Defaults to the template length,
        which spans the matched filter's main lobe plus the near reverb
        shoulder without hiding genuinely competing peaks.

    Notes
    -----
    Detection uses the *magnitude* of the matched-filter output, so a
    polarity-inverting playback/capture chain does not break it. The matched
    filter is ``mf[k] = sum_i capture[k+i] * template[i]``, so the argmax
    index is directly the template's onset in the capture.
    """
    y = np.asarray(capture, dtype=np.float64).ravel()
    tmpl = click_template(rate) if template is None else np.asarray(template, dtype=np.float64).ravel()
    if y.size < tmpl.size:
        raise ValueError(f"capture ({y.size}) shorter than click template ({tmpl.size})")

    # 'valid' correlation: mf[k] aligns template[0] with capture[k].
    mf = np.abs(fftconvolve(y, tmpl[::-1], mode="valid"))

    if search_window is not None:
        lo, hi = search_window
        mask = np.ones(mf.size, dtype=bool)
        if lo is not None:
            mask &= np.arange(mf.size) >= lo
        if hi is not None:
            mask &= np.arange(mf.size) <= hi
        if not mask.any():
            raise ValueError(f"search_window {search_window} selects no onsets in [0, {mf.size - 1}]")
    else:
        mask = None

    candidates = mf if mask is None else np.where(mask, mf, -np.inf)
    onset = int(np.argmax(candidates))
    peak = float(mf[onset])

    exclusion = tmpl.size if quality_exclusion is None else int(quality_exclusion)
    side_mask = np.ones(mf.size, dtype=bool) if mask is None else mask.copy()
    side_mask[max(0, onset - exclusion) : min(mf.size, onset + exclusion + 1)] = False
    sidelobes = mf[side_mask]
    if sidelobes.size == 0 or sidelobes.max() <= 0 or peak <= 0:
        quality_db = float("inf")
    else:
        quality_db = float(20.0 * np.log10(peak / sidelobes.max()))

    return ClickDetection(onset_sample=onset, peak_value=peak, quality_db=quality_db)
