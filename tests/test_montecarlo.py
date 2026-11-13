import threading

import numpy as np
import pandas as pd
import psutil
import pytest

from gsop import montecarlo as MC
from gsop import pipeline as P
from gsop.config import load_all
from gsop.synthetic import make_earth, plant, target_profile

CFG = load_all()
MOON_TARGET = {"slope_med": 4.0, "slope_p90": 9.0, "relief": 150.0, "rough_a": 0.4, "rough_b": 4.0,
               "sun_max_elev": 40.0, "sun_low_share": 0.2, "water_index": 0.5, "t_mean": 280.0,
               "t_coldest": 262.0, "silica_index": 1.0, "ti_proxy": 18.0}


def _job(n=6000, seed=3, plant_row=123, decoy_row=456, profile="base"):
    earth = make_earth(n, seed=seed)
    earth = plant(earth, plant_row, MOON_TARGET)
    # decoy matches the slope family only, everything else is far from the target
    earth.loc[decoy_row, ["slope_med", "slope_p90"]] = [MOON_TARGET["slope_med"], MOON_TARGET["slope_p90"]]
    earth.loc[decoy_row, ["relief", "rough_a", "rough_b", "water_index", "t_mean", "t_coldest", "silica_index",
                          "ti_proxy", "sun_max_elev", "sun_low_share"]] = [900, 3.0, 30.0, 0.0, 250.0, 215.0, 1.4, 90.0,
                                                                            88.0, 0.9]
    earth.loc[decoy_row, ["water_ice_frac", "ndvi_median", "built_crop_frac"]] = [0.0, 0.0, 0.0]
    return P.prepare_job("moon", "planted", profile, CFG, earth, target_profile(MOON_TARGET)), earth


def _run(job, runs, workers, work, **kw):
    cfg = CFG["run"]
    return MC.simulate(job.X, job.spec, runs, work, workers=workers, chunk_tiles=2500,
                       cand_cfg=cfg["candidates"], robust_cfg=cfg["robust"], checkpoints=[50, 100], **kw)


def test_run_streams_equal_seedsequence_spawn():
    kids = np.random.SeedSequence(20261114).spawn(5)
    for r in (0, 3, 4):
        a = np.random.default_rng(kids[r].spawn(3)[0]).random(4)
        b = MC.run_streams(20261114, r)[0].random(4)
        assert np.array_equal(a, b)


def test_planted_analog_ranks_first_and_is_robust(tmp_path):
    job, earth = _job()
    res = _run(job, 100, 1, tmp_path / "w")
    row_planted = int(np.flatnonzero(job.gated_rows == 123)[0])
    c = res.candidates.set_index("row")
    assert c.loc[row_planted, "robust"]
    assert c["mc_median"].idxmax() == row_planted
    assert c.loc[row_planted, "rank_pct_p05"] > 99.9
    assert c.loc[row_planted, "freq_top1"] == 1.0
    # one-family decoy must not be robust (it may be gated out or simply not a candidate)
    gated = np.flatnonzero(job.gated_rows == 456)
    if gated.size:
        assert not bool(res.robust_mask[gated[0]])


def test_base_score_of_planted_tile_is_100():
    job, _ = _job()
    score, _, _ = P.base_score(job)
    row = int(np.flatnonzero(job.gated_rows == 123)[0])
    assert score[row] == pytest.approx(100.0, abs=1e-3)
    assert int(np.argmax(score)) == row


def test_same_seed_identical_twice_and_resume_is_a_noop(tmp_path):
    job, _ = _job(n=3000)
    a = _run(job, 100, 1, tmp_path / "a", keep_work=True)
    b = _run(job, 100, 1, tmp_path / "b")
    pd.testing.assert_frame_equal(a.candidates, b.candidates)
    assert np.array_equal(a.counts, b.counts)
    again = _run(job, 100, 1, tmp_path / "a")            # resumes from the kept batch files
    pd.testing.assert_frame_equal(a.candidates, again.candidates)


def test_worker_count_does_not_change_output(tmp_path):
    job, _ = _job(n=3000)
    job.spec.batch_runs = 10
    one = _run(job, 60, 1, tmp_path / "w1")
    four = _run(job, 60, 4, tmp_path / "w4")
    assert np.array_equal(one.counts, four.counts)
    assert np.allclose(one.mean_score, four.mean_score, rtol=0, atol=1e-9)
    pd.testing.assert_frame_equal(one.candidates, four.candidates)


def test_manifest_mismatch_refuses_to_mix(tmp_path):
    job, _ = _job(n=2000)
    _run(job, 50, 1, tmp_path / "w", keep_work=True)
    job.spec.master_seed += 1
    with pytest.raises(RuntimeError, match="manifest mismatch"):
        _run(job, 50, 1, tmp_path / "w")


def test_memory_stays_inside_the_chunk_budget(tmp_path):
    n, ncols = 4_000_000, 12
    rng = np.random.default_rng(0)
    X = rng.random((ncols, n), dtype=np.float32)
    cols = [f"c{i}" for i in range(ncols)]
    fam = {"a": cols[:6], "b": cols[6:]}
    spec = MC.MCSpec(columns=cols, families=fam, ranges={"a": (0.3, 0.5), "b": (0.5, 0.7)}, multipliers={},
                     target={c: 0.5 for c in cols}, meas_unc={}, earth_unc={}, sigma={c: 0.2 for c in cols},
                     batch_runs=2)
    free = psutil.virtual_memory().available
    plan = MC.memory_plan(n, ncols, 1, free, 0.40)
    assert plan["fits"]
    proc = psutil.Process()
    base = proc.memory_info().rss
    peak = [base]
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            peak[0] = max(peak[0], proc.memory_info().rss)
            stop.wait(0.05)

    th = threading.Thread(target=sample)
    th.start()
    try:
        MC.simulate(X, spec, 2, tmp_path / "big", workers=1, chunk_tiles=plan["chunk_tiles"],
                    cand_cfg={"top_frac": 0.01, "max_candidates": 50_000}, checkpoints=[])
    finally:
        stop.set()
        th.join()
    extra = peak[0] - base
    # the run adds X's contiguous copy (it is saved once) plus per-run arrays; all inside the budget
    assert extra < plan["budget_bytes"]
    assert extra < 12 * n * 4 * 2 + plan["fixed_per_worker_bytes"] * 3
