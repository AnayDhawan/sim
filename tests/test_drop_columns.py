import copy

import pytest

from gsop import pipeline as P
from gsop.config import load_all
from gsop.synthetic import make_earth, target_profile

CFG = load_all()
MOON = {"slope_med": 4.0, "slope_p90": 9.0, "relief": 150.0, "rough_a": 0.4, "rough_b": 4.0, "sun_max_elev": 40.0,
        "sun_low_share": 0.2, "water_index": 0.5, "t_mean": 280.0, "t_coldest": 262.0, "silica_index": 1.0,
        "ti_proxy": 18.0}
MARS = {**MOON, "insol_annual": 200.0, "dust_index": 0.4, "air_density": 1.0}
AUX = {"lat": 18.0, "elevation_m": -2500.0, "thermal_inertia_si": 300.0}


def _cfg(drop):
    cfg = copy.deepcopy(CFG)
    cfg["run"]["drop_columns"] = drop
    return cfg


def test_list_form_is_global_and_unchanged():
    assert P.drop_columns_for({"drop_columns": []}, "moon") == []
    assert P.drop_columns_for({}, "mars") == []
    assert P.drop_columns_for({"drop_columns": ["water_index", "dust_index"]}, "moon") == ["water_index", "dust_index"]
    assert P.drop_columns_for({"drop_columns": ["water_index"]}, "mars") == ["water_index"]


def test_mapping_form_is_per_body():
    run = {"drop_columns": {"all": ["silica_index"], "moon": ["t_mean"], "mars": ["rough_a", "dust_index"]}}
    assert P.drop_columns_for(run, "moon") == ["silica_index", "t_mean"]
    assert P.drop_columns_for(run, "mars") == ["silica_index", "rough_a", "dust_index"]
    assert P.drop_columns_for({"drop_columns": {"mars": ["rough_a"]}}, "moon") == []


def test_mapping_form_rejects_unknown_keys_and_typos():
    with pytest.raises(ValueError, match="unknown key"):
        P.drop_columns_for({"drop_columns": {"venus": []}}, "moon")
    with pytest.raises(ValueError, match="not a column"):
        P.drop_columns_for({"drop_columns": {"moon": ["dust_index"]}}, "moon", CFG["weights"]["moon"])   # Mars-only
    with pytest.raises(ValueError, match="not a column"):
        P.drop_columns_for({"drop_columns": {"mars": ["rough_aa"]}}, "mars", CFG["weights"]["mars"])


@pytest.fixture(scope="module")
def earth():
    return make_earth(2000, seed=3)


def test_a_mars_drop_does_not_touch_the_moon_job(earth):
    cfg = _cfg({"mars": ["rough_a", "rough_b"]})
    moon = P.prepare_job("moon", "t", "base", cfg, earth, target_profile(MOON))
    assert "roughness" in moon.fam_cols and moon.dropped_columns == []
    tp = target_profile({k: v for k, v in MARS.items() if k not in ("rough_a", "rough_b")}, aux=AUX)
    tp["unavailable"] = ["rough_a", "rough_b"]
    mars = P.prepare_job("mars", "t", "base", cfg, earth, tp)
    assert "roughness" not in mars.fam_cols and mars.dropped_columns == ["rough_a", "rough_b"]
    assert sum(mars.profile_weights.values()) == pytest.approx(1.0)


def test_unavailable_column_still_stops_unless_dropped_for_that_body(earth):
    tp = target_profile({k: v for k, v in MOON.items() if k != "silica_index"})
    tp["unavailable"] = ["silica_index"]
    with pytest.raises(P.UnavailableColumns, match="silica_index"):
        P.prepare_job("moon", "t", "base", _cfg({"mars": ["silica_index"]}), earth, tp)
    job = P.prepare_job("moon", "t", "base", _cfg({"moon": ["silica_index"]}), earth, tp)
    assert "composition" not in job.fam_cols


def test_the_committed_run_yaml_drops_per_body():
    run = CFG["run"]
    moon = P.drop_columns_for(run, "moon", CFG["weights"]["moon"])
    mars = P.drop_columns_for(run, "mars", CFG["weights"]["mars"])
    assert set(moon) == {"water_index", "silica_index", "t_mean", "t_coldest", "ti_proxy"}     # E19
    assert "rough_a" not in moon and "rough_b" not in moon            # Moon roughness is built from LOLA 20 m
    left = P.active_body_cfg(CFG["weights"]["moon"], moon)
    assert list(left) == ["slope", "illumination", "roughness", "relief"]
    assert [c for f in left.values() for c in f["columns"]] == [
        "slope_med", "slope_p90", "sun_max_elev", "sun_low_share", "rough_a", "rough_b", "relief"]
    assert {"rough_a", "rough_b"} <= set(mars) and "air_density" not in mars and "insol_annual" not in mars
    for body, drop in (("moon", moon), ("mars", mars)):
        assert P.active_body_cfg(CFG["weights"][body], drop)


def test_golden_config_ignores_the_project_drop_list():
    from gsop.golden import golden_cfg
    assert golden_cfg(CFG)["run"]["drop_columns"] == [] and golden_cfg(CFG)["run"]["skip_profiles"] == {}


def test_skip_profiles_from_the_committed_config():
    assert P.skip_profiles_for(CFG, "moon") == {"ice_resources": ["water_index", "t_mean", "t_coldest", "ti_proxy"]}
    assert P.skip_profiles_for(CFG, "mars") == {"geology_life": ["silica_index", "water_index"]}
    for bad in ({"moon": {"base": ["x"]}}, {"moon": {"geology_life": ["x"]}}, {"mars": {"power_night": []}}):
        cfg = copy.deepcopy(CFG)
        cfg["run"]["skip_profiles"] = bad
        with pytest.raises(ValueError):
            P.skip_profiles_for(cfg, next(iter(bad)))


def test_a_skipped_profile_is_not_run_and_is_reported_with_its_missing_column(tmp_path, earth):
    from gsop.runner import BodyRun, hash_frame
    cfg = copy.deepcopy(CFG)
    cfg["run"].update({"drop_columns": [], "batch_runs": 25, "convergence_checkpoints": [25, 50],
                       "skip_profiles": {"moon": {"ice_resources": ["water_index"]}}})
    cfg["targets"]["moon"] = {"t1": {"lat": -89.0, "lon_e": 0.0, "source": "synthetic"}}
    br = BodyRun("moon", cfg, earth, {"t1": target_profile(MOON)}, tmp_path / "res", tmp_path / "work", 50, 1,
                 8 * 2**30, hash_frame(earth), use_store=False)
    assert "ice_resources" not in br.profiles and "base" in br.profiles
    br.run(("gates", "score"))
    assert not (tmp_path / "res" / "t1__ice_resources").exists()
    assert (tmp_path / "res" / "t1__base" / "base_scores.parquet").exists()
    why = br.unscored["t1__ice_resources"]
    assert why.startswith("not run") and "water_index" in why
