"""E28 validation amendment (gated_out sites, not_testable, ungated informational block)."""

import numpy as np
import pandas as pd
import pytest

from gsop import validate as V
from gsop.config import load_all
from gsop.gates import apply_gates
from gsop.provenance import SLOPE_LABEL, read_json

CFG = load_all()
GATES = CFG["gates"]
USED = ["slope_med"]


def _earth():
    """Four clusters of 9 tiles, about 1 km apart inside each cluster, far apart between clusters."""
    rows = []
    sites = {"good": (10.0, 10.0), "good2": (12.0, 30.0), "farm": (20.0, 50.0), "forest": (-2.0, -60.0),
             "farm_noterrain": (30.0, 70.0), "desert": (25.0, 90.0)}
    tid = 0
    for name, (la, lo) in sites.items():
        for k in range(9):
            r = {"tile_id": tid, "lat": la + 0.01 * (k // 3), "lon": lo + 0.01 * (k % 3), "water_ice_frac": 0.0,
                 "ndvi_median": 0.1, "built_crop_frac": 0.0, "slope_med": 1.0 + k}
            if name == "farm":
                r.update(built_crop_frac=1.0, ndvi_median=0.4)
            if name == "forest":
                r.update(ndvi_median=0.8)
            if name == "farm_noterrain":
                r.update(built_crop_frac=1.0, slope_med=np.nan)
            rows.append(r)
            tid += 1
    return pd.DataFrame(rows), sites


def _ks(sites, primary, controls):
    mk = lambda n: {"lat": sites[n][0], "lon": sites[n][1], "bodies": ["moon"], "confirmed": True}  # noqa: E731
    return {"criteria": {**CFG["known_sites"]["criteria"]}, "primary": {n: mk(n) for n in primary},
            "secondary": {}, "gate_tests": {"gt": {"lat": sites["forest"][0], "lon": sites["forest"][1]}},
            "negative_controls": {n: mk(n) for n in controls}}


def _run(tmp_path, primary, controls, scorer=True):
    earth, sites = _earth()
    gate = apply_gates(earth, GATES, USED)
    passed = gate["passed"].to_numpy()
    sc = pd.Series(earth["slope_med"].to_numpy()[passed], index=earth["tile_id"].to_numpy()[passed])
    fn = (lambda t, rows: earth["slope_med"].to_numpy()[rows] * 0.5) if scorer else None
    return V.validate_body("moon", _ks(sites, primary, controls), 5.0, earth, {"t1": gate}, {"t1": sc},
                           tmp_path / "validation.json", gates_cfg=GATES, used_columns=USED, ungated_scorer=fn)


def test_gated_out_primary_is_excluded_from_the_median_and_has_an_ungated_score(tmp_path):
    doc = _run(tmp_path, ["good", "good2", "farm"], ["desert"])
    r = doc["results"]
    farm = r["primary"]["farm"]
    assert farm["status"] == "gated_out" and farm["rank_pct"] is None
    assert farm["first_gate_reason"] == "vegetated" and farm["gate_reasons"] == {"vegetated": 9}
    u = farm["ungated_terrain_only"]
    assert u["label"] == "outside the pre-registered test, informational" and u["status"] == "computed"
    assert u["per_target"]["t1"]["best_score"] == pytest.approx(4.5)          # 0.5 * slope 9, open-water gate kept
    assert "open water or ice gate and the missing-data rule still apply" in u["rule"]
    assert r["n_scorable_primary_sites"] == 2 and r["gated_out_primary_sites"] == ["farm"]
    med = np.median([r["primary"]["good"]["rank_pct"], r["primary"]["good2"]["rank_pct"]])
    assert r["primary_median_rank_pct"] == pytest.approx(med)
    assert r["criteria_status"]["primary_median_ge_min"]["status"] in ("pass", "fail")
    assert "farm" in r["criteria_status"]["primary_median_ge_min"]["reason"]
    assert doc["slope_ground_scale_corrected"] is False and doc["slope_limitation"] == SLOPE_LABEL["slope_limitation"]


def test_fewer_than_two_scorable_primary_sites_is_not_testable(tmp_path):
    doc = _run(tmp_path, ["good", "farm"], ["desert"])
    st = doc["results"]["criteria_status"]["primary_median_ge_min"]
    assert st["status"] == "not_testable" and "fewer than 2" in st["reason"]
    assert doc["results"]["pass"]["primary_median_ge_min"] is None
    assert doc["results"]["pass"]["all"] in (None, False)


def test_gated_out_control_is_not_counted_below_the_maximum(tmp_path):
    doc = _run(tmp_path, ["good", "good2"], ["forest"])
    r = doc["results"]
    assert r["negative_controls"]["forest"]["status"] == "gated_out"
    assert r["criteria_status"]["controls_below_max"]["status"] == "not_testable"
    assert r["pass"]["controls_below_max"] is None
    doc = _run(tmp_path, ["good", "good2"], ["forest", "desert"])
    assert doc["results"]["criteria_status"]["controls_below_max"]["reason"] == "max over ['desert']"
    assert doc["results"]["gate_tests"]["gt"]["rejected"] is True             # gate tests unchanged


def test_gated_out_site_without_terrain_says_no_terrain_yet(tmp_path):
    doc = _run(tmp_path, ["good", "good2", "farm_noterrain"], ["desert"])
    s = doc["results"]["primary"]["farm_noterrain"]
    assert s["status"] == "gated_out" and s["ungated_terrain_only"]["status"] == "no_terrain_yet"


def test_criteria_block_carries_the_amendment_and_a_new_hash(tmp_path):
    doc = _run(tmp_path, ["good", "good2"], ["desert"])
    pre = doc["preregistered"]
    assert pre["criteria"]["primary_min_scorable_sites"] == 2
    assert pre["amendment"].startswith("E28 (2026-11-14") and "gated_out" in pre["gated_out_rule"]
    assert V.verify_preregistration(tmp_path / "validation.json")


def _run_scores(tmp_path, primary, controls, low_sites=(), body="moon", control_bodies=("moon",)):
    """Score = slope_med, except tiles of `low_sites` get score 0 (bottom of the ranking)."""
    earth, sites = _earth()
    gate = apply_gates(earth, GATES, USED)
    passed = gate["passed"].to_numpy()
    score = earth["slope_med"].to_numpy().copy()
    for n in low_sites:
        la, lo = sites[n]
        score[(abs(earth["lat"] - la) < 0.1).to_numpy() & (abs(earth["lon"] - lo) < 0.1).to_numpy()] = 0.0
    sc = pd.Series(score[passed], index=earth["tile_id"].to_numpy()[passed])
    ks = _ks(sites, primary, controls)
    for n in controls:
        ks["negative_controls"][n]["bodies"] = list(control_bodies)
    for n in primary:
        ks["primary"][n]["bodies"] = [body]
    return V.validate_body(body, ks, 5.0, earth, {"t1": gate}, {"t1": sc}, tmp_path / f"v_{body}.json",
                           gates_cfg=GATES, used_columns=USED)


def test_scorable_sand_sea_control_with_low_rank_passes(tmp_path):
    doc = _run_scores(tmp_path, ["good", "good2"], ["desert"], low_sites=["desert"])
    r = doc["results"]
    assert r["negative_controls"]["desert"]["status"] == "scored" and r["negative_controls"]["desert"]["rank_pct"] == 0.0
    assert r["criteria_status"]["controls_below_max"]["status"] == "pass"


def test_scorable_sand_sea_control_with_high_rank_fails(tmp_path):
    doc = _run_scores(tmp_path, ["good", "good2"], ["desert"])
    r = doc["results"]
    assert r["negative_controls"]["desert"]["rank_pct"] > 25
    assert r["criteria_status"]["controls_below_max"]["status"] == "fail" and r["pass"]["controls_below_max"] is False


def test_both_controls_gated_out_is_not_testable(tmp_path):
    doc = _run_scores(tmp_path, ["good", "good2"], ["forest", "farm"])
    r = doc["results"]
    assert {v["status"] for v in r["negative_controls"].values()} == {"gated_out"}
    assert r["criteria_status"]["controls_below_max"]["status"] == "not_testable"


def test_moon_only_controls_do_not_apply_to_mars(tmp_path):
    doc = _run_scores(tmp_path, ["good", "good2"], ["desert"], body="mars", control_bodies=("moon",))
    assert doc["results"]["negative_controls"] == {}
    assert doc["results"]["criteria_status"]["controls_below_max"]["status"] == "not_testable"
    assert "control_rule" in doc["preregistered"] and doc["preregistered"]["control_rule"].startswith("E30")


def test_real_config_has_the_two_moon_sand_sea_controls():
    nc = CFG["known_sites"]["negative_controls"]
    assert nc["rub_al_khali"]["bodies"] == ["moon"] and nc["namib_sand_sea"]["bodies"] == ["moon"]
    assert "bodies" not in nc["amazon_basin"] and "bodies" not in nc["congo_basin"]      # Mars controls unchanged
