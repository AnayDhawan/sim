"""C18: per-run top 1%, 5%, 10% membership with argpartition; deterministic ties; counters exact."""

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


def reference_topk(scores, k):
    """Obvious definition: sort by (-score, row)."""
    return np.lexsort((np.arange(scores.size), -scores))[:k]


@pytest.mark.parametrize("seed", range(5))
def test_matches_the_obvious_definition_on_random_scores(seed):
    rng = np.random.default_rng(seed)
    s = rng.random(10_000).astype(np.float32)
    ks = MC.top_ks(s.size, (0.01, 0.05, 0.10))
    for k, got in zip(ks, MC._top_sets(s, ks)):
        assert got.tolist() == reference_topk(s, k).tolist()


def test_ties_at_the_cutoff_go_to_the_lower_row_index():
    s = np.zeros(1000, np.float32)
    s[[10, 900]] = 5.0                       # two clear leaders
    s[100:400] = 3.0                         # 300 tied tiles compete for the remaining places
    sets = MC._top_sets(s, [10, 50, 100])
    for k, got in zip((10, 50, 100), sets):
        assert got.tolist() == reference_topk(s, k).tolist()
    assert sets[0].tolist() == [10, 900] + list(range(100, 108))
    assert set(sets[0]) <= set(sets[1]) <= set(sets[2])            # nested


def test_all_equal_scores_give_the_first_rows_and_are_repeatable():
    s = np.full(500, 7.0, np.float32)
    a = MC._top_sets(s, [5, 25, 50])
    b = MC._top_sets(s.copy(), [5, 25, 50])
    assert a[2].tolist() == list(range(50)) and [x.tolist() for x in a] == [x.tolist() for x in b]


def test_ties_do_not_depend_on_row_order_of_the_input_memory():
    rng = np.random.default_rng(1)
    s = rng.integers(0, 20, 5000).astype(np.float32)               # heavy ties
    ks = MC.top_ks(s.size, (0.01, 0.05, 0.10))
    got = [x.tolist() for x in MC._top_sets(s, ks)]
    for k, g in zip(ks, got):
        assert g == reference_topk(s, k).tolist()


def _job(n=3000):
    earth = plant(make_earth(n, seed=4), 77, MOON)
    job = P.prepare_job("moon", "t", "base", CFG, earth, target_profile(MOON))
    job.spec.meas_unc = {c: 0.05 * abs(job.spec.target[c]) for c in job.spec.columns}
    job.spec.batch_runs = 10
    return job, 77


def _sim(job, runs, work, workers=1):
    r = CFG["run"]
    return MC.simulate(job.X, job.spec, runs, work, workers=workers, chunk_tiles=1000, cand_cfg=r["candidates"],
                       robust_cfg=r["robust"], checkpoints=[])


def test_planted_analog_is_in_every_top_set_in_every_run(tmp_path):
    job, row = _job()
    res = _sim(job, 40, tmp_path / "w")
    i = int(np.flatnonzero(job.gated_rows == row)[0])
    assert (res.counts[:, i] == 40).all()
    c = res.candidates.set_index("row").loc[i]
    assert c["freq_top1"] == c["freq_top5"] == c["freq_top10"] == 1.0


def test_counts_equal_a_direct_count_and_the_sets_are_nested(tmp_path):
    job, _ = _job(2000)
    runs = 30
    res = _sim(job, runs, tmp_path / "w")
    n = job.X.shape[1]
    ks = MC.top_ks(n, job.spec.top_fracs)
    direct = np.zeros((3, n), np.int64)
    for r in range(runs):
        s = MC.score_tiles(job.X, job.spec, *MC.draw_run(job.spec, r), 1000)
        for j, k in enumerate(ks):
            direct[j, reference_topk(s, k)] += 1
    np.testing.assert_array_equal(res.counts, direct)
    assert (res.counts[0] <= res.counts[1]).all() and (res.counts[1] <= res.counts[2]).all()
    assert res.counts.sum(axis=1).tolist() == [runs * k for k in ks]


def test_counters_are_identical_for_1_and_4_workers(tmp_path):
    job, _ = _job(2500)
    one = _sim(job, 40, tmp_path / "a", workers=1)
    four = _sim(job, 40, tmp_path / "b", workers=4)
    np.testing.assert_array_equal(one.counts, four.counts)


def test_counter_width_cannot_overflow_at_2000_runs_and_is_checked(tmp_path):
    assert 2000 < np.iinfo(np.uint16).max
    job, _ = _job(1000)
    job.spec.batch_runs = 70_000
    with pytest.raises(ValueError, match="overflow the uint16"):
        MC.simulate(job.X, job.spec, 10, tmp_path / "w", workers=1)
    assert not (tmp_path / "w").exists()
