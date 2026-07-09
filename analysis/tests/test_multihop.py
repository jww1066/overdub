"""Tests for the Test 3 multi-hop Monte Carlo error model (multihop.py).

Statistical assertions are checked against closed-form expectations with
Monte Carlo tolerances at fixed seeds, so failures mean the model changed,
not that the dice rolled badly.
"""

import numpy as np
import pytest

from overdub_analysis.multihop import (
    HopModel,
    max_pairwise_offset,
    simulate_track_errors,
)


def test_zero_model_gives_zero_range():
    model = HopModel(bias_half_range_ms=0.0, noise_std_ms=0.0)
    e = simulate_track_errors(model, n_tracks=4, trials=100, rng=np.random.default_rng(0))
    assert np.all(e == 0.0)
    assert np.all(max_pairwise_offset(e) == 0.0)


def test_noise_only_two_tracks_matches_gaussian_difference():
    # Without the reference track, N=2 range = |e1 - e2| ~ |N(0, sqrt(2)*sigma)|;
    # its 95th percentile is 1.96 * sqrt(2) * sigma.
    sigma = 1.0
    model = HopModel(bias_half_range_ms=0.0, noise_std_ms=sigma)
    e = simulate_track_errors(model, n_tracks=2, trials=200_000, rng=np.random.default_rng(1))
    r = max_pairwise_offset(e, include_reference_track=False)
    expected = 1.959964 * np.sqrt(2.0) * sigma
    assert np.percentile(r, 95) == pytest.approx(expected, rel=0.03)


def test_bias_only_uniform_range_percentile():
    # Range of 4 iid uniforms on width w has CDF F(r) = 4r^3 - 3r^4 (r = R/w);
    # the 95th percentile is r95 ~ 0.9024, so R95 ~ 0.9024 * 2b.
    b = 5.0
    model = HopModel(bias_half_range_ms=b, noise_std_ms=0.0)
    e = simulate_track_errors(model, n_tracks=4, trials=200_000, rng=np.random.default_rng(2))
    r = max_pairwise_offset(e, include_reference_track=False)
    assert np.percentile(r, 95) == pytest.approx(0.90239 * 2.0 * b, rel=0.02)


def test_noise_growth_scales_later_hops():
    model = HopModel(bias_half_range_ms=0.0, noise_std_ms=1.0, noise_growth_per_hop=2.0)
    e = simulate_track_errors(model, n_tracks=3, trials=100_000, rng=np.random.default_rng(3))
    stds = e.std(axis=0)
    assert stds[0] == pytest.approx(1.0, rel=0.03)
    assert stds[1] == pytest.approx(2.0, rel=0.03)
    assert stds[2] == pytest.approx(4.0, rel=0.03)


def test_certain_unsigned_outlier_shifts_all_tracks_together():
    # p=1, fixed sign, no other error: every track lands at +outlier_ms, so the
    # pairwise range is zero among the overdubs — but 40 ms vs the original
    # reference track, which is exactly why the reference is in the mix.
    model = HopModel(
        noise_std_ms=0.0, outlier_prob=1.0, outlier_ms=40.0, outlier_signed=False
    )
    e = simulate_track_errors(model, n_tracks=4, trials=50, rng=np.random.default_rng(4))
    assert np.all(e == 40.0)
    assert np.all(max_pairwise_offset(e, include_reference_track=False) == 0.0)
    assert np.all(max_pairwise_offset(e, include_reference_track=True) == 40.0)


def test_median_of_reads_rejects_minority_outliers_and_keeps_majority_ones():
    # With 3 reads and p=1 every read is an outlier, so the median is too;
    # with p=0 the median of noiseless reads is exactly zero.
    hit = HopModel(noise_std_ms=0.0, outlier_prob=1.0, outlier_ms=40.0,
                   outlier_signed=False, reads_per_track=3)
    e = simulate_track_errors(hit, n_tracks=2, trials=50, rng=np.random.default_rng(5))
    assert np.all(e == 40.0)

    clean = HopModel(noise_std_ms=0.0, outlier_prob=0.0, reads_per_track=3)
    e = simulate_track_errors(clean, n_tracks=2, trials=50, rng=np.random.default_rng(6))
    assert np.all(e == 0.0)


def test_median_of_three_reduces_outlier_rate():
    # Single read: track is displaced with prob p. Median of 3: displaced only
    # if >= 2 of 3 reads are outliers ~ 3p^2(1-p) + p^3 -- for p = 1/9 that is
    # ~3.4% instead of ~11.1%.
    p = 1.0 / 9.0
    trials = 200_000
    single = HopModel(noise_std_ms=0.0, outlier_prob=p, outlier_ms=40.0,
                      outlier_signed=False, reads_per_track=1)
    med3 = HopModel(noise_std_ms=0.0, outlier_prob=p, outlier_ms=40.0,
                    outlier_signed=False, reads_per_track=3)
    e1 = simulate_track_errors(single, n_tracks=1, trials=trials, rng=np.random.default_rng(7))
    e3 = simulate_track_errors(med3, n_tracks=1, trials=trials, rng=np.random.default_rng(8))
    rate1 = float(np.mean(np.abs(e1) > 1.0))
    rate3 = float(np.mean(np.abs(e3) > 1.0))
    assert rate1 == pytest.approx(p, rel=0.05)
    assert rate3 == pytest.approx(3 * p**2 * (1 - p) + p**3, rel=0.10)


def test_invalid_parameters_raise():
    with pytest.raises(ValueError):
        HopModel(bias_half_range_ms=-1.0)
    with pytest.raises(ValueError):
        HopModel(outlier_prob=1.5)
    with pytest.raises(ValueError):
        HopModel(reads_per_track=0)
    with pytest.raises(ValueError):
        HopModel(noise_growth_per_hop=0.0)
    model = HopModel()
    with pytest.raises(ValueError):
        simulate_track_errors(model, n_tracks=0, trials=10, rng=np.random.default_rng(0))
    with pytest.raises(ValueError):
        max_pairwise_offset(np.zeros(5))
