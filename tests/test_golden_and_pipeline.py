import copy

import numpy as np
import pandas as pd
import pytest

from gsop import golden as GD
from gsop import pipeline as P
from gsop import tools as T
from gsop import validate as V
from gsop.config import load_all
from gsop.provenance import read_json, verify_manifest
from gsop.runner import BodyRun, hash_frame
from gsop.synthetic import make_earth, plant, target_profile

CFG = load_all()


def test_golden_inputs_are_exactly_the_checked_in_ones():
    assert GD.verify_inputs() == []


def test_golden_run_matches_expected_within_tolerance():
    res = GD.run_golden(workers=1)
    exp = read_json(GD.GOLDEN_DIR / "golden_expected.json")
    rows = GD.compare_golden(exp, res, CFG["run"]["compare"])
    bad = [r for r in rows if not r["ok"]]
    assert not bad, bad


def test_golden_worker_count_does_not_matter():
    a = GD.run_golden(workers=1)
    b = GD.run_golden(workers=2)
    assert all(r["ok"] for r in GD.compare_golden(a, b, {"score_abs": 1e-9, "mc_abs": 1e-9, "jaccard_min": 1.0}))


def test_compare_catches_a_real_difference():
    a = read_json(GD.GOLDEN_DIR / "golden_expected.json")
    b = copy.deepcopy(a)
    job = next(iter(b["bodies"]["moon"].values()))
    job["score_first100"][3] += 0.01
    rows = GD.compare_golden(a, b, CFG["run"]["compare"])
    assert any(not r["ok"] for r in rows)


MOON = {"slope_med": 4.0, "slope_p90": 9.0, "relief": 150.0, "rough_a": 0.4, "rough_b": 4.0, "sun_max_elev": 40.0,
        "sun_low_share": 0.2, "water_index": 0.5, "t_mean": 280.0, "t_coldest": 262.0, "silica_index": 1.0,
        "ti_proxy": 18.0}


def _body_run(tmp_path, body, earth, cfg):
    tp = {"t1": target_profile(MOON) if body == "moon" else target_profile(
        {**MOON, "insol_annual": 200.0, "dust_index": 0.4, "air_density": 1.0},
        aux={"lat": 18.0, "elevation_m": -2500.0, "thermal_inertia_si": 300.0})}
    return BodyRun(body, cfg, earth, tp, tmp_path / "res" / body, tmp_path / "work" / body, 50, 1, 8 * 2**30,
                   hash_frame(earth), use_store=True)


def _cfg():
    cfg = copy.deepcopy(CFG)
    cfg["run"].update({"batch_runs": 25, "convergence_checkpoints": [25, 50]})
    cfg["targets"]["moon"] = {"t1": {"lat": -89.0, "lon_e": 0.0, "source": "synthetic"}}
    cfg["targets"]["mars"] = {"t1": {"lat": 18.0, "lon_e": 77.0, "source": "synthetic"},
                              "arcadia": {"lat": None, "lon_e": None, "status": "unscored_no_target_data"}}
    cfg["run"]["ml"].update({"n_negatives": 300})
    # two real sites at planted tiles so validation and ML have something to find
    earth_lat = None
    return cfg, earth_lat


@pytest.fixture(scope="module")
def earth():
    e = make_earth(4000, seed=5)
    for r in (10, 20, 30):
        e = plant(e, r, {k: v * (1 + 0.01 * r / 10) for k, v in MOON.items()})
    for c in ("insol_annual", "dust_index", "air_density"):
        pass
    return e


def test_full_pipeline_moon_and_merge(tmp_path, earth):
    cfg, _ = _cfg()
    for n, row in (("lonar", 10), ("haughton", 20), ("ladakh_puga", 30)):
        cfg["known_sites"]["primary"][n].update({"lat": float(earth.loc[row, "lat"]), "lon": float(earth.loc[row, "lon"]),
                                                 "bodies": ["moon", "mars"]})
    for k in ("mcmurdo_dry_valleys", "atacama_salars", "mdrs_utah"):
        cfg["known_sites"]["primary"].pop(k)
    br = _body_run(tmp_path, "moon", earth, cfg)
    br.run()
    res = tmp_path / "res" / "moon"
    assert (res / "t1__base" / "mc_summary.parquet").exists()
    assert (res / "t1__landing_mobility" / "base_scores.parquet").exists()
    v = read_json(res / "validation.json")
    assert v["status"] == "computed" and v["provisional"] is True
    assert V.verify_preregistration(res / "validation.json")
    assert v["results"]["primary"]["lonar"]["rank_pct"] > 90          # planted tile is the best match
    assert (res / "t1__base" / "ml.json").exists() and (res / "t1__base" / "discovery.json").exists()
    assert verify_manifest(res / "export") == []
    exp = read_json(res / "export" / "candidates__t1__base.json")
    assert exp["candidates"][0]["robust"] in (True, False) and "illum_match" in exp["candidates"][0]
    fid = read_json(res / "export" / "fidelity.json")
    assert 0 <= fid["per_purpose"]["base"]["fidelity"] <= 100
    # resume: nothing re-runs, outputs identical
    br2 = _body_run(tmp_path, "moon", earth, cfg)
    br2.run()
    assert br2.timings == {}
    assert read_json(res / "run_meta.json")["earth_hash"] == hash_frame(earth)

    # mars run (D5 low confidence labels, D6 gate, D10 unscored arcadia) then merge
    brm = _body_run(tmp_path, "mars", earth, cfg)
    brm.run()
    assert "arcadia" in brm.unscored and "no target data" in brm.unscored["arcadia"]
    s = read_json(tmp_path / "res" / "mars" / "t1__landing_mobility" / "summary.json")
    assert s["confidence"] == "low" and s["fails_own_gate"] is False
    assert read_json(tmp_path / "res" / "mars" / "t1__base" / "summary.json")["confidence"] == "standard"
    warns = T.merge_results(tmp_path / "res" / "moon", tmp_path / "res" / "mars", tmp_path / "all")
    assert warns == [] or all("git commits" in w for w in warns)
    idx = read_json(tmp_path / "all" / "index.json")
    assert {v["body"] for v in idx["views"]} == {"moon", "mars"}
    assert verify_manifest(tmp_path / "all") == []


def test_unavailable_column_stops_the_run_loudly(earth):
    cfg, _ = _cfg()
    tp = target_profile({k: v for k, v in MOON.items() if k != "water_index"})
    tp["unavailable"] = ["water_index"]
    with pytest.raises(P.UnavailableColumns, match="water_index"):
        P.prepare_job("moon", "t1", "base", cfg, earth, tp)
    cfg["run"]["drop_columns"] = ["water_index"]               # a deliberate, logged decision
    job = P.prepare_job("moon", "t1", "base", cfg, earth, tp)
    assert "cold_dry" not in job.fam_cols and job.dropped_columns == ["water_index"]
    assert sum(job.profile_weights.values()) == pytest.approx(1.0)


def test_mars_target_failing_its_own_gate_still_runs_and_is_labelled(earth):
    cfg, _ = _cfg()
    tp = target_profile({**MOON, "insol_annual": 200.0, "dust_index": 0.4, "air_density": 1.0},
                        aux={"lat": 18.0, "elevation_m": 3000.0, "thermal_inertia_si": 50.0})
    job = P.prepare_job("mars", "t1", "base", cfg, earth, tp)
    assert job.mars_check["fails_own_gate"] and not job.mars_check["skip"]
    cfg["gates"]["mars_target_check"]["mode"] = "strict"
    with pytest.raises(P.UnavailableColumns):
        P.prepare_job("mars", "t1", "base", cfg, earth, tp)


def test_validation_gate_tests_and_unconfirmed_warning():
    ks = CFG["known_sites"]
    want = sorted(f"{grp}/{n}" for grp in ("primary", "secondary", "gate_tests", "negative_controls")
                  for n, s in ks[grp].items() if not s.get("confirmed", False))
    assert sorted(V.unconfirmed_sites(ks)) == want
    # a site flips to confirmed only with a source comment on its line in the yaml (issue #10)
    text = open("config/known_sites.yaml", encoding="utf-8").read().splitlines()
    for grp in ("primary", "secondary", "gate_tests"):
        for n, s in ks[grp].items():
            if s.get("confirmed"):
                line = next(l for l in text if l.strip().startswith(f"{n}:"))
                assert "#" in line, f"{n} is confirmed without a source comment"
    unconfirmed = V.unconfirmed_sites({"primary": {"x": {"confirmed": False}}, "secondary": {}, "gate_tests": {},
                                       "negative_controls": {}})
    assert unconfirmed == ["primary/x"]
