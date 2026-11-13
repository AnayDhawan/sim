"""C21: Monte Carlo parallelism. Worker-count independence, per-batch timing, interrupt and resume."""

import logging

import numpy as np
import pandas as pd
import pytest

from gsop import montecarlo as MC
from gsop import pipeline as P
from gsop.config import load_all
from gsop.synthetic import make_earth, plant, target_profile

CFG = load_all()
MOON = {"slope_med": 4.0, "slope_p90": 9.0, "relief": 150.0, "rough_a": 0.4, "rough_b": 4.0, "sun_max_elev": 40.0,
        "sun_low_share": 0.2, "water_index": 0.5, "t_mean": 280.0, "t_coldest": 262.0, "silica_index": 1.0,
        "ti_proxy": 18.0}


def _job(n=2500):
    earth = plant(make_earth(n, seed=21), 99, MOON)
    job = P.prepare_job("moon", "t", "base", CFG, earth, target_profile(MOON))
    job.spec.meas_unc = {c: 0.06 * abs(job.spec.target[c]) for c in job.spec.columns}
    job.spec.batch_runs = 10
    return job


def _sim(job, runs, work, workers=1, **kw):
    r = CFG["run"]
    return MC.simulate(job.X, job.spec, runs, work, workers=workers, chunk_tiles=800, cand_cfg=r["candidates"],
                       robust_cfg=r["robust"], checkpoints=[], **kw)


def test_1_2_and_4_workers_agree_exactly_on_counters_and_closely_on_floats(tmp_path):
    job = _job()
    res = {w: _sim(job, 60, tmp_path / f"w{w}", workers=w) for w in (1, 2, 4)}
    for w in (2, 4):
        np.testing.assert_array_equal(res[1].counts, res[w].counts)
        np.testing.assert_allclose(res[1].stats.mean, res[w].stats.mean, rtol=0, atol=1e-9)
        np.testing.assert_allclose(res[1].stats.variance(), res[w].stats.variance(), rtol=1e-9, atol=1e-12)
        pd.testing.assert_frame_equal(res[1].candidates, res[w].candidates)
        assert (res[1].robust_mask == res[w].robust_mask).all()


def test_the_feature_array_is_memory_mapped_not_pickled():
    import pickle
    job = _job(4000)
    args = (job.spec.as_dict(), "x.npy", "work", 0, 50, 800)
    assert len(pickle.dumps(args)) < 4000                      # a path and a few numbers, not the array
    assert job.X.nbytes > 100_000


def test_each_batch_reports_its_time(tmp_path, caplog):
    job = _job(1200)
    with caplog.at_level(logging.INFO, logger="gsop.montecarlo"):
        _sim(job, 30, tmp_path / "w")
    p1 = [m for m in caplog.messages if m.startswith("pass 1: batch")]
    p2 = [m for m in caplog.messages if m.startswith("pass 2: batch")]
    assert len(p1) == 3 and len(p2) == 3
    assert "done in" in p1[0] and "of 3 this call" in p1[-1]


def test_interrupt_saves_finished_batches_and_the_rerun_resumes(tmp_path, monkeypatch, caplog):
    job = _job(1800)
    real = MC.pass1_batch
    calls = []

    def flaky(spec_d, x_path, work, batch_id, n_runs, chunk):
        calls.append(batch_id)
        if batch_id == 2:
            raise KeyboardInterrupt
        return real(spec_d, x_path, work, batch_id, n_runs, chunk)

    monkeypatch.setattr(MC, "pass1_batch", flaky)
    with caplog.at_level(logging.WARNING, logger="gsop.montecarlo"):
        with pytest.raises(KeyboardInterrupt):
            _sim(job, 50, tmp_path / "w", keep_work=True)
    assert calls == [0, 1, 2]
    assert sorted(p.name for p in (tmp_path / "w" / "pass1").glob("*.npz")) == ["batch_00000.npz", "batch_00001.npz"]
    assert any("interrupted after 2 of 5 batches" in m and "resume" in m for m in caplog.messages)

    calls.clear()
    monkeypatch.setattr(MC, "pass1_batch", lambda *a: (calls.append(a[3]), real(*a))[1])
    resumed = _sim(job, 50, tmp_path / "w")
    assert calls == [2, 3, 4]                                      # batches 0 and 1 were not recomputed
    fresh = _sim(_job(1800), 50, tmp_path / "fresh")
    np.testing.assert_array_equal(resumed.counts, fresh.counts)
    pd.testing.assert_frame_equal(resumed.candidates, fresh.candidates)


def test_an_interrupted_parallel_run_also_resumes(tmp_path):
    from gsop import parallel as PAR
    job = _job(1500)
    seen = []

    def stop(r):
        seen.append(r)
        raise KeyboardInterrupt

    x = tmp_path / "w"
    x.mkdir()
    np.save(x / "X.npy", job.X)
    MC._check_manifest(x, job.spec, MC.sha256_file(x / "X.npy"))
    args = [(job.spec.as_dict(), str(x / "X.npy"), str(x), b, 40, 800) for b in range(4)]
    with pytest.raises(KeyboardInterrupt):
        PAR.run_tasks(MC.pass1_batch, args, workers=2, on_result=stop, progress=False)
    done = len(list((x / "pass1").glob("*.npz")))
    assert 1 <= done <= 4                                          # whatever finished is saved, atomically
    res = _sim(job, 40, x)
    fresh = _sim(_job(1500), 40, tmp_path / "fresh")
    np.testing.assert_array_equal(res.counts, fresh.counts)
