"""D04: best tile within the match radius of each known site and its rank percentile, per target and profile."""

import numpy as np
import pandas as pd
import pytest

from gsop import pipeline as P
from gsop import validate as V
from gsop.config import load_all
from gsop.provenance import read_json, write_json
from synth import IDS, make_synth

CFG = load_all()


@pytest.fixture(scope="module")
def setup():
    syn = make_synth(4000)
    e = syn.earth
    job = P.prepare_job("moon", "t1", "base", CFG, e, syn.targets["moon"])
    score, _, _ = P.base_score(job)
    tid = e["tile_id"].to_numpy()[job.gated_rows]
    scores = pd.Series(score, index=tid)
    gate = job.gate_df
    # a second profile with different gating, so profile-specific rank percentiles can be reported
    job2 = P.prepare_job("moon", "t1", "landing_mobility", CFG, e, syn.targets["moon"])
    s2, _, _ = P.base_score(job2)
    scores2 = pd.Series(s2, index=e["tile_id"].to_numpy()[job2.gated_rows])
    return syn, scores, gate, {"t1": {"base": scores, "landing_mobility": scores2}}


def site(e, tile, dlat=0.05):
    r = e.loc[tile]
    return {"lat": float(r["lat"]) + dlat, "lon": float(r["lon"]), "confirmed": True}      # ~5.6 km away: inside 20 km


def ks_for(e):
    worst = int(np.argmin(np.where(np.isfinite(e["slope_med"]), -e["slope_med"], np.inf)))
    return {"primary": {"planted": {**site(e, IDS["exact"]), "bodies": ["moon"]},
                        "trapped": {**site(e, IDS["gated_water"]), "bodies": ["moon"]}},
            "secondary": {}, "gate_tests": {"water_trap": {**site(e, IDS["gated_water"], 0.0), "expect": "rejected"}},
            "negative_controls": {"far": {**site(e, 3999), "confirmed": True}},
            "criteria": CFG["known_sites"]["criteria"]}


def run(setup, tmp_path, mc=None, with_profiles=True):
    syn, scores, gate, by_prof = setup
    ks = ks_for(syn.earth)
    out = tmp_path / "validation.json"
    doc = V.validate_body("moon", ks, 20.0, syn.earth, {"t1": gate}, {"t1": scores}, out, mc,
                          by_prof if with_profiles else None)
    return doc["results"], doc


def test_planted_site_gets_the_best_tile_within_radius_and_ranks_at_the_top(setup, tmp_path):
    res, _ = run(setup, tmp_path)
    p = res["primary"]["planted"]["per_target"]["t1"]
    assert p["status"] == "scored" and p["gates_passed"] is True
    assert p["best_tile"] == IDS["exact"] and p["best_score"] == pytest.approx(100.0, abs=1e-3)
    assert p["rank_pct"] > 99.9 and p["n_gated_tiles_in_radius"] >= 1
    assert res["primary"]["planted"]["rank_pct"] == p["rank_pct"]


def test_a_site_whose_tiles_are_all_gated_out_is_reported_rejected_with_the_reason_not_dropped(setup, tmp_path):
    res, _ = run(setup, tmp_path)
    t = res["primary"]["trapped"]
    p = t["per_target"]["t1"]
    assert t["status"] == "rejected" and p["status"] == "rejected" and p["gates_passed"] is False
    assert p["best_tile"] is None and p["rank_pct"] == 0.0
    assert p["rejected_reasons"].get("open_water_or_ice", 0) >= 1
    assert "trapped" in res["primary"]                                        # not dropped
    assert res["n_primary_sites"] == 2
    assert res["primary_median_rank_pct"] == pytest.approx(np.median([res["primary"]["planted"]["rank_pct"], 0.0]))


def test_table_has_one_row_per_site_and_target(setup, tmp_path):
    res, _ = run(setup, tmp_path)
    rows = res["site_table"]
    keys = {(r["group"], r["site"], r["target"]) for r in rows}
    assert keys == {("primary", "planted", "t1"), ("primary", "trapped", "t1"), ("negative_control", "far", "t1")}
    planted = next(r for r in rows if r["site"] == "planted")
    assert planted["best_tile"] == IDS["exact"] and planted["gates_passed"] is True and planted["rank_pct"] > 99


def test_mc_range_of_the_best_tile_is_reported_when_it_is_a_candidate(setup, tmp_path):
    mc = pd.DataFrame({"mc_p05": [91.0], "mc_median": [95.0], "mc_p95": [99.0], "rank_pct_p05": [99.2],
                       "rank_pct_p50": [99.8], "rank_pct_p95": [100.0], "freq_top5": [1.0], "robust": [True]},
                      index=pd.Index([IDS["exact"]], name="tile_id"))
    res, _ = run(setup, tmp_path, {"t1": mc})
    m = res["primary"]["planted"]["per_target"]["t1"]["mc"]
    assert m["mc_p05"] == 91.0 and m["mc_p95"] == 99.0 and m["robust"] is True
    assert res["primary"]["planted"]["per_target"]["t1"]["mc"] is not None
    (tmp_path / "x").mkdir()
    empty = run(setup, tmp_path / "x", {"t1": mc.iloc[0:0]})[0]            # best tile is not a candidate
    assert empty["primary"]["planted"]["per_target"]["t1"]["mc"] is None


def test_rank_percentile_is_given_for_every_profile(setup, tmp_path):
    res, _ = run(setup, tmp_path)
    by = res["primary"]["planted"]["per_target"]["t1"]["rank_pct_by_profile"]
    assert set(by) == {"base", "landing_mobility"} and by["base"] > 99.9
    assert 0 <= by["landing_mobility"] <= 100
    (tmp_path / "np").mkdir()
    res2, _ = run(setup, tmp_path / "np", with_profiles=False)
    assert "rank_pct_by_profile" not in res2["primary"]["planted"]["per_target"]["t1"]


def test_median_and_pass_flags_follow_the_preregistered_criteria(setup, tmp_path):
    res, doc = run(setup, tmp_path)
    assert doc["provisional"] is True and V.verify_preregistration(tmp_path / "validation.json")
    assert res["pass"]["primary_median_ge_min"] is False         # median of [~100, 0] is ~50 < 90
    assert res["gate_tests"]["water_trap"]["rejected"] is True
    assert res["pass"]["gate_tests_all_rejected"] is True
