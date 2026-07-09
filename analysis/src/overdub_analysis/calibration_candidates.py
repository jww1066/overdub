"""Musical calibration-signal candidates for the per-take alignment gate.

Context (doc/design-summary.md "Beat-period aliasing" item, decided
2026-07-09): every take emits a calibration signal into the playback stream
at a known sample position during the lead-in. It serves two roles at once --
(1) the anchor centering the GCC-PHAT lag search (narrower than half the
beat period, so a one-beat alias is excluded by construction), and (2) the
per-take rejection gate ``|gcc_offset - signal_offset| <= 2 ms`` (gate
failure -> re-take prompt). The laboratory chirp in ``calibration_click.py``
proves the mechanism; its *sound* is not required.

The hard requirements the emitted signal must meet (design-summary.md):
  - energy concentrated in 500-4000 Hz (the measured speaker->mic passband);
  - >= ~2 kHz of bandwidth within it (sub-ms, cycle-unambiguous
    matched-filter peak);
  - an aperiodic single-peak autocorrelation (sidelobes ~10+ dB down within
    the +/-90 ms anchored window -- the alias-resistance requirement);
  - a deterministic waveform at a known position (so the generator and the
    matched-filter detector use the identical template);
  - enough level x duration for ~10 dB detection quality (pulse compression:
    a longer signal can be proportionally quieter).

Duration, level, envelope, and timbre are free, so this module prototypes
three *musical* candidates to A/B against those requirements
(doc/prototype-plan.md "calibration-signal bake-off"):

  - **accented_downbeat**: a short downward-chirp "blip" (~30 ms, ~3000->700
    Hz log sweep, exponential decay) intended to read as an accented count-in
    downbeat. Timbrally distinct from a static-pitch metronome tick -- that
    distinctness is itself a requirement (see ``count_in_scenario``), or the
    beat-period alias returns via the neighboring count-in clicks.
  - **log_sweep_riser**: a low-level ~300 ms logarithmic 500->4000 Hz riser.
    Long and quiet; pulse compression buys ~30 dB of processing gain so it
    detects at a low emitted level.
  - **shaker_burst**: a ~100 ms band-limited noise burst with a shaker-like
    envelope, fixed seed. Broadband in-band, impulse-like autocorrelation.

Each generator is a pure function of ``(rate, seed)`` returning a
``CandidateSpec`` whose ``template`` is the waveform aligned at onset sample
0 -- the same convention as ``calibration_click.click_template`` -- so the
emitted signal and the matched-filter template are bit-identical by
construction. All three are confined to 500-4000 Hz during generation, so the
raw template is the correct matched filter (no extra band-limiting needed at
detect time).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import butter, sosfiltfilt

__all__ = [
    "BAND_LO_HZ",
    "BAND_HI_HZ",
    "DEFAULT_RATE",
    "CandidateSpec",
    "CandidateMetrics",
    "accented_downbeat",
    "log_sweep_riser",
    "shaker_burst",
    "ALL_CANDIDATES",
    "SELECTED_CANDIDATE_FACTORY",
    "detect_template",
    "TemplateDetection",
    "evaluate_candidate",
    "count_in_scenario",
    "CountInResult",
]

# The speaker->mic usable band (doc/test2-sweep-results.md). Every candidate
# is confined here during generation, and the aperiodicity / detection
# metrics operate on this band. Single source of truth -- do not restate.
BAND_LO_HZ = 500.0
BAND_HI_HZ = 4000.0
DEFAULT_RATE = 48000


@dataclass(frozen=True)
class CandidateSpec:
    """A musical calibration-signal candidate.

    Attributes
    ----------
    name :
        Short kebab id ("accented-downbeat", ...).
    description :
        One-line human description of the timbre/intent.
    template :
        The waveform, onset at sample 0. Confined to 500-4000 Hz.
    rate :
        Sample rate the template was generated at.
    seed :
        RNG seed used (kept in the spec so regeneration is reproducible).
    params :
        Generation parameters, for the record / for re-derivation.
    """

    name: str
    description: str
    template: np.ndarray
    rate: int
    seed: int
    params: dict = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        return self.template.size / float(self.rate)

    @property
    def onset_sample(self) -> int:
        """Index of the signal's first sample -- always 0 by convention."""
        return 0


def _bandpass(signal: np.ndarray, rate: int) -> np.ndarray:
    """Zero-phase 500-4000 Hz bandpass (the usable speaker->mic band)."""
    sos = butter(4, [BAND_LO_HZ, BAND_HI_HZ], btype="bandpass", fs=rate, output="sos")
    return sosfiltfilt(sos, signal)


def _normalize_peak(signal: np.ndarray, peak_dbfs: float) -> np.ndarray:
    """Scale ``signal`` to a target peak level in dBFS (negative dB)."""
    peak = float(np.max(np.abs(signal)))
    if peak <= 0:
        raise ValueError("cannot normalize a silent signal")
    return signal * (10.0 ** (peak_dbfs / 20.0) / peak)


# --- candidate generators ---------------------------------------------------


def accented_downbeat(rate: int = DEFAULT_RATE, *, seed: int = 101) -> CandidateSpec:
    """A short downward-chirp "blip" meant to read as an accented count-in downbeat.

    ~40 ms *linear* sweep from 3400 Hz down to 600 Hz (a 2800 Hz span -- >=2 kHz
    of occupied bandwidth within the band), with short raised-cosine fades and
    a mild exponential decay so it attacks and decays like a percussive
    accent. A *linear* sweep (not log) is used deliberately: a log sweep dwells
    longer at low frequencies, and combined with an attack-side decay that
    concentrates energy at the high-frequency start, the occupied bandwidth
    collapsed to ~1 kHz in an earlier prototype -- below the >=2 kHz
    requirement. The linear sweep distributes dwell time uniformly across the
    swept range, so the energy spans the full 2800 Hz. The pitch glide makes
    it timbrally distinct from a static-pitch metronome tick (validated by
    ``count_in_scenario``); the glide also gives a clean, aperiodic
    matched-filter peak (pulse compression of a chirp).
    """
    duration = 0.050
    f_start = 3400.0
    f_end = 500.0
    peak_dbfs = -3.0
    n = round(rate * duration)
    t = np.arange(n) / float(rate)
    # Linear chirp: f(t) = f0 + (f1-f0)*t/T; phase = integral 2*pi*f(t) dt.
    phase = 2.0 * np.pi * (f_start * t + 0.5 * (f_end - f_start) * t**2 / duration)
    # Short 5 ms raised-cosine fades for click-free edges. The envelope is
    # otherwise FLAT on purpose: an amplitude decay concentrates energy at the
    # attack side (one end of the sweep) and collapses the occupied bandwidth
    # below the >=2 kHz requirement -- measured at ~1.5 kHz with even a mild
    # exp(-2.5) decay. The accent character comes from the pitch glide itself
    # (a short "zwip"), not from amplitude decay.
    fade = round(rate * 0.005)
    env = np.ones(n)
    if 2 * fade < n:
        ramp = 0.5 * (1.0 - np.cos(np.pi * np.arange(fade) / fade))
        env[:fade] = ramp
        env[-fade:] = ramp[::-1]
    sig = env * np.sin(phase)
    sig = _bandpass(sig, rate)
    sig = _normalize_peak(sig, peak_dbfs)
    return CandidateSpec(
        name="accented-downbeat",
        description="short downward-chirp blip (~50 ms, 3400->500 Hz linear), accented downbeat",
        template=sig,
        rate=rate,
        seed=seed,
        params={"duration_s": duration, "f_start_hz": f_start, "f_end_hz": f_end, "peak_dbfs": peak_dbfs},
    )


def log_sweep_riser(rate: int = DEFAULT_RATE, *, seed: int = 202) -> CandidateSpec:
    """A low-level ~300 ms logarithmic 500->4000 Hz riser.

    Long and quiet (peak ~-18 dBFS): it sits underneath a count-in as a
    barely-audible "riser" cue. Pulse compression gives a sharp, unambiguous
    matched-filter peak despite the low emitted level -- the time-bandwidth
    product (~0.3 s x ~3500 Hz) buys ~30 dB of processing gain, the concrete
    instance of "a longer signal can be proportionally quieter." A single
    monotonic log sweep is aperiodic (no beat-period self-similarity).
    """
    duration = 0.300
    f_start = BAND_LO_HZ
    f_end = BAND_HI_HZ
    peak_dbfs = -18.0
    n = round(rate * duration)
    t = np.arange(n) / float(rate)
    ratio = f_end / f_start
    # f(t) = f_start * ratio^(t/T); phase = integral 2*pi*f(t) dt
    #      = 2*pi * f_start * T / ln(ratio) * (ratio^(t/T) - 1)
    phase = 2.0 * np.pi * (f_start * duration / np.log(ratio)) * (ratio ** (t / duration) - 1.0)
    # Gentle 5 ms raised-cosine fades so the riser itself doesn't click; the
    # matched-filter peak comes from the sweep, not from hard edges.
    fade = round(rate * 0.005)
    env = np.ones(n)
    if fade > 0 and 2 * fade < n:
        ramp = 0.5 * (1.0 - np.cos(np.pi * np.arange(fade) / fade))
        env[:fade] = ramp
        env[-fade:] = ramp[::-1]
    sig = env * np.sin(phase)
    sig = _bandpass(sig, rate)
    sig = _normalize_peak(sig, peak_dbfs)
    return CandidateSpec(
        name="log-sweep-riser",
        description="low-level ~300 ms log sweep 500->4000 Hz riser (pulse-compressed detection)",
        template=sig,
        rate=rate,
        seed=seed,
        params={"duration_s": duration, "f_start_hz": f_start, "f_end_hz": f_end, "peak_dbfs": peak_dbfs},
    )


def shaker_burst(rate: int = DEFAULT_RATE, *, seed: int = 303) -> CandidateSpec:
    """A ~100 ms band-limited noise burst with a shaker-like envelope.

    Fixed-seed white noise band-limited to 500-4000 Hz, shaped with a fast
    attack and an exponential-ish "shake" decay (a slight two-lobed envelope
    evoking a single shake). Noise is maximally aperiodic (autocorrelation ~
    impulse -> no beat-period alias risk), and the deterministic seed means
    the emitted waveform and the matched-filter template are identical. The
    ~100 ms x ~3500 Hz time-bandwidth product gives ~25 dB of processing gain.
    """
    duration = 0.100
    peak_dbfs = -12.0
    rng = np.random.default_rng(seed)
    n = round(rate * duration)
    t = np.arange(n) / float(rate)
    # Two-lobed shaker envelope: fast attack (8 ms) then decay, with a small
    # secondary lobe around 55 ms for a "shake" feel.
    attack = 0.008
    env = np.ones(n)
    a = round(rate * attack)
    if a > 0:
        env[:a] = np.linspace(0.0, 1.0, a)
    env *= np.exp(-np.linspace(0.0, 4.0, n))
    lobe_center = round(rate * 0.055)
    lobe = np.exp(-((np.arange(n) - lobe_center) ** 2) / (2.0 * (rate * 0.010) ** 2))
    env = np.maximum(env, 0.35 * lobe)
    sig = env * rng.standard_normal(n)
    sig = _bandpass(sig, rate)
    sig = _normalize_peak(sig, peak_dbfs)
    return CandidateSpec(
        name="shaker-burst",
        description="~100 ms band-limited noise burst, shaker envelope, fixed seed",
        template=sig,
        rate=rate,
        seed=seed,
        params={"duration_s": duration, "peak_dbfs": peak_dbfs, "noise_seed": seed},
    )


ALL_CANDIDATES = [accented_downbeat, log_sweep_riser, shaker_burst]

# Selection (post-audition, 2026-07-09; see doc/design-summary.md "Beat-period
# aliasing"): the log-sweep-riser is the emitted calibration signal for v1 --
# most processing gain (detects at the lowest emitted level) and an
# unobtrusive "riser under the count-in" character. The other two stay as
# documented fallbacks for later design. This alias is the one place the
# selection lives in code; the port implements this waveform.
SELECTED_CANDIDATE_FACTORY = log_sweep_riser


# --- generalized matched-filter detector -------------------------------------


@dataclass(frozen=True)
class TemplateDetection:
    """Matched-filter detection of a known template in a capture.

    Mirrors ``calibration_click.ClickDetection`` but for an arbitrary
    template, so any candidate can be detected by the same instrument.

    Attributes
    ----------
    onset_sample :
        Index in the capture where the template starts.
    peak_value :
        Magnitude of the matched-filter output at the detected onset.
    quality_db :
        20*log10(peak / largest competing |peak| outside the exclusion
        window) -- a PSR-style trustworthiness metric. ``np.inf`` if nothing
        competes.
    """

    onset_sample: int
    peak_value: float
    quality_db: float


def detect_template(
    capture: np.ndarray,
    template: np.ndarray,
    rate: int,
    *,
    search_window: tuple[int | None, int | None] | None = None,
    quality_exclusion: int | None = None,
) -> TemplateDetection:
    """Locate ``template`` in ``capture`` via matched filter (magnitude, polarity-insensitive).

    Parameters
    ----------
    capture :
        1-D signal expected to contain the template (possibly delayed,
        band-limited, polarity-inverted, noisy).
    template :
        The known waveform to match (the candidate's ``template``).
    rate :
        Sample rate; kept for API symmetry with ``detect_click``.
    search_window :
        Optional ``(min_onset, max_onset)`` bound in samples restricting both
        the peak search and the competing-peak (quality) search. Either
        endpoint may be ``None``.
    quality_exclusion :
        Half-width in samples excluded from the competing-peak search around
        the detected peak. Defaults to the template length (spans the main
        lobe plus near reverb shoulder).

    Notes
    -----
    Uses the magnitude of the matched-filter output so a polarity-inverting
    playback/capture chain does not break detection. ``mf[k] = sum_i
    capture[k+i] * template[i]`` ('valid' correlation), so the argmax index
    is directly the template's onset in the capture.
    """
    y = np.asarray(capture, dtype=np.float64).ravel()
    tmpl = np.asarray(template, dtype=np.float64).ravel()
    if y.size < tmpl.size:
        raise ValueError(f"capture ({y.size}) shorter than template ({tmpl.size})")

    mf = np.abs(fftconvolve_local(y, tmpl))

    if search_window is not None:
        lo, hi = search_window
        mask = np.ones(mf.size, dtype=bool)
        idx = np.arange(mf.size)
        if lo is not None:
            mask &= idx >= lo
        if hi is not None:
            mask &= idx <= hi
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

    return TemplateDetection(onset_sample=onset, peak_value=peak, quality_db=quality_db)


def fftconvolve_local(y: np.ndarray, tmpl: np.ndarray) -> np.ndarray:
    """'valid' magnitude correlation of ``y`` with ``tmpl`` (onboard scipy if available)."""
    from scipy.signal import fftconvolve

    return np.abs(fftconvolve(y, tmpl[::-1], mode="valid"))


# --- metrics: the bake-off evaluation ---------------------------------------


@dataclass(frozen=True)
class CandidateMetrics:
    """All hard-requirement metrics for one candidate (the bake-off A/B row).

    Attributes
    ----------
    in_band_fraction :
        Fraction of total spectral energy inside 500-4000 Hz. Want most energy
        in-band (out-of-band energy is clipped/wasted by the speaker/mic).
    bw_90pct_hz :
        Frequency span holding the central 90% of in-band energy (f95 - f05).
        The ">=2 kHz bandwidth within the band" requirement. Want >= 2000.
    bw_10db_hz :
        -10 dB occupied span within the band (max - min in-band freq within
        10 dB of the in-band peak). Cross-check on bandwidth.
    worst_sidelobe_db :
        Largest off-zero autocorrelation lobe within +/- ``max_lag_ms``,
        relative to the zero-lag peak, in dB (negative). The aperiodicity /
        alias-resistance requirement. Want <= -10.
    beat_sidelobe_db :
        Largest autocorrelation lobe near +/- one beat period (default 187 ms,
        the boots.wav inter-onset interval), in dB relative to zero-lag.
        Reported for the record; a strong beat-period lobe is the specific
        alias risk the calibration signal exists to avoid.
    processing_gain_db :
        10*log10(duration_s * bw_10db_hz) -- the theoretical matched-filter
        processing gain. The "longer => proportionally quieter" lever: more
        gain means the signal can be emitted at a lower level and still
        detect. (Reference, not a gate.)
    peak_dbfs, rms_dbfs :
        Level of the template.
    detection :
        Dict ``snr_db -> (quality_db, onset_err_samples)`` under the simulated
        realistic capture path (band-limited + polarity-inverted + in-band
        noise at each SNR). The "~10 dB detection quality" requirement is
        judged here.
    """

    in_band_fraction: float
    bw_90pct_hz: float
    bw_10db_hz: float
    worst_sidelobe_db: float
    beat_sidelobe_db: float
    processing_gain_db: float
    peak_dbfs: float
    rms_dbfs: float
    detection: dict


def _band_energy_span(spec: np.ndarray, freqs: np.ndarray, lo: float, hi: float) -> tuple[float, float, float]:
    """Return (in_band_fraction, 90%-energy bandwidth Hz, -10 dB span Hz)."""
    power = np.abs(spec) ** 2
    total = float(power.sum())
    if total <= 0:
        raise ValueError("silent spectrum")
    inband = (freqs >= lo) & (freqs <= hi)
    in_band_fraction = float(power[inband].sum() / total)
    f_in = freqs[inband]
    p_in = power[inband]
    if p_in.size == 0 or p_in.sum() <= 0:
        return in_band_fraction, 0.0, 0.0
    # 90%-energy span: cumulative energy across ascending in-band frequency.
    order = np.argsort(f_in)
    f_sorted = f_in[order]
    cdf = np.cumsum(p_in[order]) / float(p_in.sum())
    f05 = float(f_sorted[np.searchsorted(cdf, 0.05)])
    f95 = float(f_sorted[np.searchsorted(cdf, 0.95)])
    bw_90 = f95 - f05
    # -10 dB span within the band.
    peak = float(p_in.max())
    above = f_in[p_in >= peak / 10.0]
    bw_10 = float(above.max() - above.min()) if above.size > 1 else 0.0
    return in_band_fraction, bw_90, bw_10


def _autocorrelation(signal: np.ndarray) -> np.ndarray:
    """Plain (non-PHAT) autocorrelation via FFT, full length, zero-lag at index 0."""
    nfft = 1 << int(np.ceil(np.log2(2 * signal.size - 1)))
    X = np.fft.fft(signal, n=nfft)
    ac = np.real(np.fft.ifft(X * np.conj(X)))
    return ac  # ac[k] = sum_n signal[n] signal[n+k]; ac[0] is the energy


def _sidelobe_db(ac: np.ndarray, rate: int, excl_ms: float, lo_ms: float, hi_ms: float) -> float:
    """Largest |ac| lag in (excl, lo..hi] both signs, in dB vs ac[0]; -inf if none."""
    zero = float(ac[0])
    if zero <= 0:
        return float("-inf")
    nfft = ac.size
    idx = np.arange(nfft)
    lag = np.where(idx > nfft // 2, idx - nfft, idx)
    excl = round(excl_ms * 1e-3 * rate)
    lo = round(lo_ms * 1e-3 * rate)
    hi = round(hi_ms * 1e-3 * rate)
    in_scan = (np.abs(lag) > excl) & (np.abs(lag) >= lo) & (np.abs(lag) <= hi)
    mag = np.abs(ac)
    mag[~in_scan] = 0.0
    m = float(mag.max())
    if m <= 0:
        return float("-inf")
    return float(20.0 * np.log10(m / zero))


def _simulated_capture(template: np.ndarray, rate: int, delay_samples: int, snr_db: float, rng: np.random.Generator) -> np.ndarray:
    """Realistic speaker->mic path: delay, band-limit, polarity-invert, in-band noise at SNR."""
    d = int(delay_samples)
    out = np.zeros(template.size + abs(d), dtype=np.float64)
    if d >= 0:
        out[d : d + template.size] = template
    else:
        k = -d
        if k < template.size:
            out[: template.size - k] = template[k:]
    clean = -_bandpass(out, rate)  # polarity-inverted, band-limited
    sig_power = float(np.mean(clean**2))
    if sig_power <= 0:
        raise ValueError("clean capture has zero power")
    noise_power = sig_power / (10.0 ** (snr_db / 10.0))
    noise = _bandpass(rng.standard_normal(clean.size), rate)
    nfac = noise_power / (float(np.mean(noise**2)) + 1e-30)
    return clean + noise * np.sqrt(nfac)


def evaluate_candidate(
    spec: CandidateSpec,
    *,
    snrs_db: tuple[float, ...] = (-6.0, 0.0, 6.0, 10.0),
    max_lag_ms: float = 90.0,
    exclusion_ms: float = 5.0,
    beat_lag_ms: float = 187.0,
    beat_window_ms: float = 20.0,
    detection_delay_samples: int = 3000,
    seed: int = 7,
) -> CandidateMetrics:
    """Measure every hard requirement for ``spec`` (the bake-off A/B row).

    Parameters
    ----------
    snrs_db :
        In-band SNRs at which to measure detection quality under the simulated
        realistic capture path.
    max_lag_ms :
        Half-width of the anchored window within which autocorrelation
        sidelobes must be ~10+ dB down (the +/-90 ms product gate window).
    exclusion_ms :
        Half-width around zero lag excluded from the sidelobe search (the
        compressed-pulse main lobe is wider than 1 sample for these signals).
    beat_lag_ms, beat_window_ms :
        The inter-onset period to probe for a beat-period self-similarity lobe
        (default 187 ms = boots.wav), +/- ``beat_window_ms``.
    detection_delay_samples :
        Delay injected for the detection test (true onset = this value).
    seed :
        RNG seed for the noise added in the detection test.
    """
    rate = spec.rate
    tmpl = np.asarray(spec.template, dtype=np.float64).ravel()
    n = tmpl.size

    # Spectral band concentration + bandwidth.
    spec_fft = np.fft.rfft(tmpl)
    freqs = np.fft.rfftfreq(n, d=1.0 / rate)
    in_band_fraction, bw_90, bw_10 = _band_energy_span(spec_fft, freqs, BAND_LO_HZ, BAND_HI_HZ)

    # Aperiodicity: plain autocorrelation of the band-limited template.
    bp = _bandpass(tmpl, rate)
    ac = _autocorrelation(bp)
    worst = _sidelobe_db(ac, rate, exclusion_ms, exclusion_ms, max_lag_ms)
    beat = _sidelobe_db(ac, rate, exclusion_ms, beat_lag_ms - beat_window_ms, beat_lag_ms + beat_window_ms)

    # Detection quality under the simulated realistic capture path. The
    # quality-exclusion half-width is the compressed-pulse main-lobe width
    # (~1/bandwidth, a few ms), NOT the template length: a pulse-compressed
    # signal's matched-filter peak is narrow regardless of how long the
    # template is, and excluding the whole template length would wipe every
    # competitor in the short test capture (the bug that returned quality=inf
    # for the 300 ms riser / 100 ms shaker).
    rng = np.random.default_rng(seed)
    pulse_width = max(round(rate / max(bw_10, 500.0)), round(rate * 0.001))
    exclusion_samples = 4 * pulse_width  # main lobe + near reverb shoulder
    detection: dict = {}
    for snr in snrs_db:
        cap = _simulated_capture(tmpl, rate, detection_delay_samples, snr, rng)
        det = detect_template(cap, tmpl, rate, quality_exclusion=exclusion_samples)
        true_onset = detection_delay_samples  # template onset is 0
        onset_err = abs(det.onset_sample - true_onset)
        detection[snr] = (det.quality_db, onset_err)

    peak_dbfs = float(20.0 * np.log10(np.max(np.abs(tmpl)) + 1e-30))
    rms_dbfs = float(20.0 * np.log10(np.sqrt(np.mean(tmpl**2)) + 1e-30))
    pg = float(10.0 * np.log10((n / float(rate)) * max(bw_10, 1.0)))

    return CandidateMetrics(
        in_band_fraction=in_band_fraction,
        bw_90pct_hz=bw_90,
        bw_10db_hz=bw_10,
        worst_sidelobe_db=worst,
        beat_sidelobe_db=beat,
        processing_gain_db=pg,
        peak_dbfs=peak_dbfs,
        rms_dbfs=rms_dbfs,
        detection=detection,
    )


@dataclass(frozen=True)
class CountInResult:
    """Outcome of the count-in timbral-uniqueness scenario for one candidate.

    The accented-downbeat candidate lives among the other count-in metronome
    ticks; if it is not timbrally distinct, its matched filter can lock onto a
    neighboring tick one beat away -- the beat-period alias returning through
    the back door (design-summary.md). This places the candidate as tick 1 of
    a count-in and matched-filters the *whole count-in* against the
    candidate's template.

    Attributes
    ----------
    downbeat_onset_sample :
        Where the candidate was placed (tick 1). The detector must recover it.
    detected_onset_sample :
        Matched-filter argmax over the whole count-in.
    dominance_db :
        20*log10(downbeat_peak / largest competing tick peak). The
        timbral-uniqueness requirement: want >= 10 dB (the candidate dominates
        its neighbors by >= 10 dB).
    tick_rel_db :
        Per-tick matched-filter peak relative to the downbeat peak (dB; the
        downbeat itself is 0.0). Non-accent ticks should be well below 0.
    """

    downbeat_onset_sample: int
    detected_onset_sample: int
    dominance_db: float
    tick_rel_db: tuple


def _metronome_tick(n: int, freq_hz: float, rate: int) -> np.ndarray:
    """A short Hann-windowed sine -- a plain metronome tick (non-accent)."""
    t = np.arange(n) / float(rate)
    return np.hanning(n) * np.sin(2.0 * np.pi * freq_hz * t)


def count_in_scenario(
    spec: CandidateSpec,
    *,
    bpm: float = 120.0,
    ticks: int = 4,
    tick_freq_hz: float = 1500.0,
    tick_duration_s: float = 0.012,
    rate: int | None = None,
) -> CountInResult:
    """Place ``spec`` as the accented downbeat among ``ticks`` metronome ticks.

    The candidate is tick 1 (at sample 0); ticks 2..N are plain
    ``tick_freq_hz`` metronome ticks at the beat period. The whole count-in is
    matched-filtered against the candidate's template: the downbeat must be
    recovered and must dominate the other ticks by >= 10 dB (timbral
    uniqueness vs the count-in -- the requirement that keeps the beat-period
    alias from returning via neighboring clicks).
    """
    r = rate if rate is not None else spec.rate
    period = round(60.0 / bpm * r)
    tick_n = round(r * tick_duration_s)
    tmpl = np.asarray(spec.template, dtype=np.float64).ravel()
    total = period * ticks + tmpl.size
    count_in = np.zeros(total, dtype=np.float64)
    tick_onsets: list[int] = []
    for i in range(ticks):
        onset = i * period
        tick_onsets.append(onset)
        if i == 0:
            count_in[onset : onset + tmpl.size] += tmpl
        else:
            tk = _metronome_tick(tick_n, tick_freq_hz, r)
            count_in[onset : onset + tk.size] += tk
    # 'valid' correlation: mf[k] aligns tmpl[0] with count_in[k], so the
    # downbeat (placed at onset 0) self-matches at mf[0] -- the largest peak,
    # since the template matches itself exactly. A competing tick at onset o
    # produces its (small, cross-correlation) peak near mf[o].
    from scipy.signal import fftconvolve

    mf = np.abs(fftconvolve(count_in, tmpl[::-1], mode="valid"))
    valid_len = mf.size
    downbeat_peak = float(mf[0])
    # Per-tick peak: search a small window around each tick onset (the
    # compressed-pulse width, a few ms, either side).
    half = max(round(r * 0.003), 1)
    tick_peaks: list[float] = []
    for onset in tick_onsets:
        lo = max(0, onset - half)
        hi = min(valid_len, onset + half + 1)
        tick_peaks.append(float(mf[lo:hi].max()))
    competing = max(p for i, p in enumerate(tick_peaks) if i != 0)
    dominance = (
        float(20.0 * np.log10(downbeat_peak / competing))
        if downbeat_peak > 0 and competing > 0
        else float("inf")
    )
    detected = int(np.argmax(mf))
    tick_rel = tuple(
        float(20.0 * np.log10(p / downbeat_peak)) if downbeat_peak > 0 and p > 0 else float("-inf")
        for p in tick_peaks
    )
    return CountInResult(
        downbeat_onset_sample=0,
        detected_onset_sample=detected,
        dominance_db=dominance,
        tick_rel_db=tick_rel,
    )
