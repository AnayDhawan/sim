"""C17: batched float32 scoring with online per-tile statistics. No N x runs matrix is ever allocated."""

import numpy as np
import pytest

from gsop import montecarlo as MC
from gsop import pipeline as P
from gsop.config import load_all
from gsop.synthetic import make_earth, plant, target_profile

CFG = load_all()
MOON = {"slope_med": 4.0, "slope_p90": 9.0, "relief": 150.0, "rough_a": 0.4, "rough_b": 4.0, "sun_max_elev": 40.0,
        "sun_low_share": 0.2, "water_index": 0.5, "t_mean": 280.0, "t_coldest": 262.0, "silica_index": 1.0,
        "ti_proxy": 18.0}


def _job(n=1000, unc=True):
    earth = plant(make_earth(n, seed=9), 5, MOON)
    cfg = dict(CFG)
    job = P.prepare_job("moon", "t", "base", cfg, earth, target_profile(MOON))
    if unc:                                          # jitter every column so the scores really vary run to run
        job.spec.meas_unc = {c: 0.1 * abs(job.spec.target[c]) for c in job.spec.columns}
        job.spec.earth_unc = {c: 0.05 * abs(job.spec.target[c]) for c in job.spec.columns}
    return job


def _sim(job, runs, work, workers=1, **kw):
    r = CFG["run"]
    return MC.simulate(job.X, job.spec, runs, work, workers=workers, chunk_tiles=300, cand_cfg=r["candidates"],
                       robust_cfg=r["robust"], checkpoints=[], **kw)


def _direct(job, runs):
    """All scores of every run, the thing the engine must never build at scale: N x runs, here 1,000 x 60."""
    return np.stack([MC.score_tiles(job.X, job.spec, *MC.draw_run(job.spec, r), 300) for r in range(runs)])


def test_mean_variance_min_max_equal_a_direct_computation(tmp_path):
    job = _job()
    job.spec.batch_runs = 10
    runs = 60
    res = _sim(job, runs, tmp_path / "w")
    S = _direct(job, runs).astype(np.float64)
    st = res.stats
    assert st.n_runs == runs and len(st.mean) == job.X.shape[1]
    np.testing.assert_allclose(st.mean, S.mean(axis=0), rtol=0, atol=1e-5)
    np.testing.assert_allclose(st.variance(), S.var(axis=0, ddof=1), rtol=1e-5, atol=1e-5)
    np.testing.assert_allclose(st.std(), S.std(axis=0, ddof=1), rtol=1e-5, atol=1e-5)
    np.testing.assert_array_equal(st.minimum, S.min(axis=0).astype(np.float32))
    np.testing.assert_array_equal(st.maximum, S.max(axis=0).astype(np.float32))
    assert st.variance().max() > 0                                   # the data really varied
    np.testing.assert_allclose(res.mean_score, st.mean)


def test_candidate_table_carries_std_min_max(tmp_path):
    job = _job()
    res = _sim(job, 30, tmp_path / "w")
    c = res.candidates
    assert {"mc_mean", "mc_std", "mc_min", "mc_max"} <= set(c.columns)
    assert (c["mc_min"] <= c["mc_mean"] + 1e-6).all() and (c["mc_mean"] <= c["mc_max"] + 1e-6).all()
    assert (c["mc_std"] >= 0).all()
    i = int(c["row"].iloc[0])
    assert c["mc_std"].iloc[0] == pytest.approx(res.stats.std()[i], rel=1e-6)


def test_stats_do_not_depend_on_the_batch_layout_or_workers(tmp_path):
    a, b = _job(), _job()
    a.spec.batch_runs, b.spec.batch_runs = 10, 25
    ra, rb = _sim(a, 50, tmp_path / "a"), _sim(b, 50, tmp_path / "b")
    np.testing.assert_allclose(ra.stats.mean, rb.stats.mean, atol=1e-9)
    np.testing.assert_allclose(ra.stats.variance(), rb.stats.variance(), rtol=1e-6, atol=1e-8)
    c = _job()
    c.spec.batch_runs = 10
    rc = _sim(c, 50, tmp_path / "c", workers=2)
    r1 = _sim(a, 50, tmp_path / "a2")
    np.testing.assert_array_equal(rc.stats.mean, r1.stats.mean)       # same batches: bit-identical across workers
    np.testing.assert_array_equal(rc.stats.m2, r1.stats.m2)


def test_two_stats_over_disjoint_runs_merge_to_the_stats_of_all_runs():
    rng = np.random.default_rng(0)
    S = rng.normal(50, 10, (100, 40))

    def stats_of(x):
        n = len(x)
        return MC.MCStats(n, x.mean(0), ((x - x.mean(0)) ** 2).sum(0), x.min(0).astype(np.float32),
                          x.max(0).astype(np.float32), np.full((3, 40), n, np.int32))
    merged = stats_of(S[:30]).extend(stats_of(S[30:]))
    whole = stats_of(S)
    assert merged.n_runs == 100
    np.testing.assert_allclose(merged.mean, whole.mean, rtol=1e-12)
    np.testing.assert_allclose(merged.m2, whole.m2, rtol=1e-12)
    np.testing.assert_array_equal(merged.minimum, whole.minimum)
    assert (merged.counts == 100).all()
    empty = MC.MCStats.empty(40, 3)
    assert empty.extend(whole).n_runs == 100 and whole.extend(MC.MCStats.empty(40, 3)).n_runs == 100


def test_alloc_guard_refuses_an_n_by_runs_matrix_in_debug_mode(monkeypatch):
    monkeypatch.setattr(MC, "DEBUG_ALLOC", True)
    MC.alloc((3, 1_000), np.uint16, 1_000)
    MC.alloc((1_000,), np.float64, 1_000)
    with pytest.raises(AssertionError, match="N x runs matrix"):
        MC.alloc((2000, 1_000), np.float32, 1_000)
    monkeypatch.setattr(MC, "DEBUG_ALLOC", False)
    assert MC.alloc((2000, 10), np.float32, 10).shape == (2000, 10)         # off outside debug mode


def test_a_whole_run_in_debug_mode_never_allocates_a_run_matrix(tmp_path, monkeypatch):
    monkeypatch.setattr(MC, "DEBUG_ALLOC", True)
    job = _job()
    res = _sim(job, 30, tmp_path / "w")
    assert res.stats.n_runs == 30


def test_memory_plan_counts_the_statistics_arrays():
    plan = MC.memory_plan(1_000_000, 12, 1, 8 * 2**30, 0.4)
    assert plan["fixed_per_worker_bytes"] >= 1_000_000 * 40
