"""C07: per-column Gaussian similarity, family mean, tile score; NaN means missing; no underflow NaN;
one function for a single run and the Monte Carlo inner loop."""

import numpy as np
import pytest

from gsop import montecarlo as MC
from gsop import similarity as S

COLS = ["a", "b", "c", "d", "e"]
FAM = {"f1": ["a", "b"], "f2": ["c"], "f3": ["d", "e"]}
IDX = {c: i for i, c in enumerate(COLS)}
TARGET = {"a": 4.0, "b": 9.0, "c": 150.0, "d": 0.4, "e": 40.0}
SIGMA = {"a": 1.0, "b": 2.0, "c": 30.0, "d": 0.1, "e": 8.0}
W = {"f1": 0.5, "f2": 0.3, "f3": 0.2}


def X_of(rows):
    return np.array([[r[c] for c in COLS] for r in rows], dtype=np.float32).T.copy()


def test_exact_target_match_is_one_per_column_and_100_overall():
    X = X_of([TARGET])
    score, fam = S.score_block(X, IDX, FAM, W, TARGET, SIGMA, return_families=True)
    assert score.dtype == np.float32 and score[0] == pytest.approx(100.0, abs=1e-4)
    assert all(v[0] == pytest.approx(1.0) for v in fam.values())
    for c in COLS:
        assert S.column_similarity(X[IDX[c]], TARGET[c], SIGMA[c])[0] == pytest.approx(1.0)


def test_family_score_is_the_mean_of_its_columns():
    row = {**TARGET, "b": TARGET["b"] + SIGMA["b"]}                 # one sigma off on b only
    X = X_of([row])
    _, fam = S.score_block(X, IDX, FAM, W, TARGET, SIGMA, return_families=True)
    assert fam["f1"][0] == pytest.approx((1.0 + np.exp(-0.5)) / 2, rel=1e-6)
    assert fam["f2"][0] == pytest.approx(1.0) and fam["f3"][0] == pytest.approx(1.0)


def test_tile_score_is_100_times_the_weighted_sum():
    row = {**TARGET, "c": TARGET["c"] + 2 * SIGMA["c"]}
    score = S.score_block(X_of([row]), IDX, FAM, W, TARGET, SIGMA)
    assert score[0] == pytest.approx(100 * (0.5 + 0.3 * np.exp(-2.0) + 0.2), rel=1e-5)


def test_far_values_underflow_to_zero_without_nan():
    far = [{**TARGET, "a": 1e4}, {**TARGET, "a": 1e30}, {**TARGET, "a": -1e30}, {**TARGET, "a": np.inf},
           {**TARGET, "a": -np.inf}]
    X = X_of(far)
    with np.errstate(all="raise"):                                  # the function must silence its own warnings
        s = S.column_similarity(X[IDX["a"]], TARGET["a"], SIGMA["a"])
    assert np.isfinite(s).all() and (s == 0).all()
    score = S.score_block(X, IDX, FAM, W, TARGET, SIGMA)
    assert np.isfinite(score).all()
    assert score == pytest.approx(np.full(5, 100 * (0.5 * 0.5 + 0.5)), rel=1e-5)     # f1 half, f2 and f3 full


def test_nan_marks_the_tile_missing_and_is_never_scored_as_zero():
    rows = [TARGET, {**TARGET, "c": np.nan}, {**TARGET, "d": np.nan}]
    X = X_of(rows)
    score, fam = S.score_block(X, IDX, FAM, W, TARGET, SIGMA, return_families=True)
    assert S.valid_mask(score).tolist() == [True, False, False]
    assert np.isnan(fam["f2"][1]) and np.isnan(fam["f3"][2]) and np.isfinite(fam["f1"]).all()
    zero_filled = X.copy()
    zero_filled[np.isnan(zero_filled)] = 0
    assert np.isfinite(S.score_block(zero_filled, IDX, FAM, W, TARGET, SIGMA)).all()     # what must NOT happen


def test_nan_in_a_family_with_zero_weight_does_not_poison_the_tile():
    X = X_of([{**TARGET, "c": np.nan}])
    score = S.score_block(X, IDX, FAM, {"f1": 0.7, "f2": 0.0, "f3": 0.3}, TARGET, SIGMA)
    assert score[0] == pytest.approx(100.0, abs=1e-4)


def test_all_zero_weights_is_an_error():
    with pytest.raises(ValueError, match="all family weights are zero"):
        S.score_block(X_of([TARGET]), IDX, FAM, {"f1": 0, "f2": 0, "f3": 0}, TARGET, SIGMA)


def test_single_run_and_monte_carlo_loop_use_the_same_numbers():
    rng = np.random.default_rng(4)
    rows = [{c: TARGET[c] + SIGMA[c] * rng.normal() for c in COLS} for _ in range(3000)]
    X = X_of(rows)
    single = S.score_block(X, IDX, FAM, W, TARGET, SIGMA)
    spec = MC.MCSpec(columns=COLS, families=FAM, ranges={f: (0.1, 0.5) for f in FAM}, multipliers={}, target=TARGET,
                     meas_unc={}, earth_unc={}, sigma=SIGMA)
    for chunk in (7, 1000, 3000):
        np.testing.assert_array_equal(MC.score_tiles(X, spec, W, TARGET, chunk), single)


def test_base_pipeline_path_agrees_with_score_block():
    rng = np.random.default_rng(5)
    X = X_of([{c: TARGET[c] + SIGMA[c] * rng.normal() for c in COLS} for _ in range(500)])
    fam = S.family_scores({c: X[IDX[c]] for c in COLS}, TARGET, SIGMA, FAM)
    np.testing.assert_array_equal(S.tile_score(fam, W), S.score_block(X, IDX, FAM, W, TARGET, SIGMA))


def test_sigma_floor_still_the_max_of_three_terms():
    assert S.sigma_rule(1.0, 2.0, 40.0) == pytest.approx(10.0)


def test_throughput_is_reported():
    r = S.throughput(n_tiles=100_000, repeats=1)
    assert r["tiles_per_second"] > 1e5 and r["n_cols"] == 15
