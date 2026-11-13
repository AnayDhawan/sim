"""C19: pass 2 re-runs the same seeds for candidate tiles only: exact percentiles and rank-percentile range."""

import math

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
RUNS = 40


def _job(n=2400):
    earth = plant(make_earth(n, seed=12), 321, MOON)
    job = P.prepare_job("moon", "t", "base", CFG, earth, target_profile(MOON))
    job.spec.meas_unc = {c: 0.08 * abs(job.spec.target[c]) for c in job.spec.columns}
    job.spec.batch_runs = 10
    return job


@pytest.fixture(scope="module")
def finished(tmp_path_factory):
    job = _job()
    work = tmp_path_factory.mktemp("mc") / "w"
    r = CFG["run"]
    res = MC.simulate(job.X, job.spec, RUNS, work, workers=1, chunk_tiles=800, cand_cfg=r["candidates"],
                      robust_cfg=r["robust"], checkpoints=[], keep_work=True)
    cand = np.load(work / "candidates.npy")
    sc = np.array(np.memmap(work / "cand_scores.f32", dtype=np.float32, mode="r", shape=(RUNS, len(cand))))
    rk = np.array(np.memmap(work / "cand_rank.f32", dtype=np.float32, mode="r", shape=(RUNS, len(cand))))
    return job, res, cand, sc, rk


def test_candidates_are_robust_tiles_plus_the_top_share_by_mean_and_by_membership(finished):
    job, res, cand, _, _ = finished
    n = job.X.shape[1]
    kc = math.ceil(CFG["run"]["candidates"]["top_frac"] * n)
    assert set(np.flatnonzero(res.robust_mask)) <= set(cand)
    assert set(np.argsort(-res.mean_score, kind="stable")[:kc]) <= set(cand)
    assert len(cand) >= kc and (np.diff(cand) > 0).all()
    assert len(res.candidates) == len(cand)


def test_pass2_scores_equal_a_fresh_scoring_of_the_same_seeds(finished):
    job, _, cand, sc, _ = finished
    for r in (0, 7, RUNS - 1):
        w, t = MC.draw_run(job.spec, r)
        full = MC.score_tiles(job.X, job.spec, w, t, 800)
        np.testing.assert_array_equal(sc[r], full[cand])


def test_pass2_scores_equal_pass1_scores_for_the_same_runs(finished):
    """Pass 1 keeps only statistics of the scores; the mean, min and max of the stored pass-2 scores must equal them."""
    _, res, cand, sc, _ = finished
    np.testing.assert_allclose(sc.astype(np.float64).mean(axis=0), res.stats.mean[cand], atol=1e-4)
    np.testing.assert_array_equal(sc.min(axis=0), res.stats.minimum[cand])
    np.testing.assert_array_equal(sc.max(axis=0), res.stats.maximum[cand])


def test_percentiles_equal_numpys_on_the_stored_arrays(finished):
    _, res, cand, sc, rk = finished
    c = res.candidates
    p = np.percentile(sc, [5, 50, 95], axis=0)
    q = np.percentile(rk, [5, 50, 95], axis=0)
    np.testing.assert_allclose(c["mc_p05"], p[0], rtol=1e-6)
    np.testing.assert_allclose(c["mc_median"], p[1], rtol=1e-6)
    np.testing.assert_allclose(c["mc_p95"], p[2], rtol=1e-6)
    np.testing.assert_allclose(c["rank_pct_p05"], q[0], rtol=1e-6)
    np.testing.assert_allclose(c["rank_pct_p50"], q[1], rtol=1e-6)
    np.testing.assert_allclose(c["rank_pct_p95"], q[2], rtol=1e-6)
    assert (c["mc_p05"] <= c["mc_median"]).all() and (c["mc_median"] <= c["mc_p95"]).all()


def test_rank_percentile_is_the_share_of_all_tiles_scoring_lower(finished):
    job, _, cand, sc, rk = finished
    n = job.X.shape[1]
    for r in (3, 21):
        full = MC.score_tiles(job.X, job.spec, *MC.draw_run(job.spec, r), 800)
        expect = 100.0 * (full[None, :] < full[cand][:, None]).sum(axis=1) / n
        np.testing.assert_allclose(rk[r], expect, rtol=0, atol=1e-4)


def test_planted_analog_has_a_narrow_top_rank_range(finished):
    job, res, _, _, _ = finished
    i = int(np.flatnonzero(job.gated_rows == 321)[0])
    row = res.candidates.set_index("row").loc[i]
    assert row["rank_pct_p05"] > 99.9 and row["rank_pct_p95"] <= 100.0
    assert row["mc_p05"] > 50


def test_candidate_cap_keeps_robust_tiles_first_and_flags_truncation(tmp_path):
    job = _job()
    r = CFG["run"]
    cap = 20
    res = MC.simulate(job.X, job.spec, 20, tmp_path / "w", workers=1, chunk_tiles=800,
                      cand_cfg={"top_frac": 0.2, "max_candidates": cap}, robust_cfg=r["robust"], checkpoints=[])
    assert len(res.candidates) == cap and res.convergence["candidates_truncated"] is True
    n_rob = int(res.robust_mask.sum())
    assert n_rob <= cap and res.candidates["robust"].sum() == n_rob      # every robust tile survived the cap


def test_pass2_resumes_after_an_interruption(tmp_path):
    job = _job(1500)
    r = CFG["run"]
    kw = dict(workers=1, chunk_tiles=500, cand_cfg=r["candidates"], robust_cfg=r["robust"], checkpoints=[])
    a = MC.simulate(job.X, job.spec, 30, tmp_path / "w", keep_work=True, **kw)
    for f in sorted((tmp_path / "w" / "pass2").glob("*.done"))[1:]:     # pretend batches 1.. never finished
        f.unlink()
    b = MC.simulate(job.X, job.spec, 30, tmp_path / "w", **kw)
    for c in ("mc_median", "mc_p05", "mc_p95", "rank_pct_p05", "rank_pct_p95"):
        np.testing.assert_array_equal(a.candidates[c], b.candidates[c])
