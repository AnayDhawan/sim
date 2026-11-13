import numpy as np
import pandas as pd
import pytest

from gsop import gates as G
from gsop import similarity as S
from gsop.config import load_all
from gsop.synthetic import make_earth

CFG = load_all()


def test_exact_match_is_one_and_far_is_zero():
    x = np.array([5.0, 5.0, 500.0], dtype=np.float32)
    s = S.column_similarity(x, 5.0, 1.0)
    assert s[0] == pytest.approx(1.0) and s[1] == pytest.approx(1.0)
    assert s[2] == pytest.approx(0.0, abs=1e-12)


def test_sigma_floor_is_the_max_of_three_terms():
    assert S.sigma_rule(1.0, 2.0, 40.0) == pytest.approx(10.0)
    assert S.sigma_rule(None, None, 8.0) == pytest.approx(2.0)
    assert S.sigma_rule(5.0, 0.5, 4.0) == pytest.approx(5.0)
    assert S.sigma_rule(0.0, None, 0.0) > 0


def test_iqr_floor_prevents_collapse_for_unmatchable_variable():
    rng = np.random.default_rng(0)
    x = rng.uniform(20, 90, 100_000)              # Earth never gets near 1.5 deg Sun elevation
    sig = S.sigma_rule(0.0, None, S.iqr(x))
    s = S.column_similarity(x, 1.5, sig)
    assert np.isfinite(s).all()
    assert (s > 0).mean() > 0.9                    # no mass underflow to exactly 0
    assert len(np.unique(s)) > 1000                # no ties from underflow


def test_tile_score_range():
    rng = np.random.default_rng(0)
    fam = {"a": rng.random(10).astype(np.float32), "b": rng.random(10).astype(np.float32)}
    sc = S.tile_score(fam, {"a": 0.5, "b": 0.5})
    assert (sc >= 0).all() and (sc <= 100).all()


def _earth():
    return make_earth(8, seed=1)


def test_each_gate_fails_with_the_right_reason():
    df = _earth()
    df.loc[0, "water_ice_frac"] = 0.9
    df.loc[1, "ndvi_median"] = 0.5
    df.loc[2, "built_crop_frac"] = 0.5
    df.loc[3, "slope_med"] = 20.0
    df.loc[4, "slope_med"] = np.nan
    df.loc[5, ["water_ice_frac", "ndvi_median", "built_crop_frac"]] = [0.0, 0.0, 0.0]
    df.loc[5, "slope_med"] = 1.0
    for i in (6, 7):
        df.loc[i, ["water_ice_frac", "ndvi_median", "built_crop_frac", "slope_med"]] = [0.0, 0.0, 0.0, 1.0]
    out = G.apply_gates(df, CFG["gates"], ["slope_med"], "slope_med <= 8")
    r = out["reason"].tolist()
    assert r[0] == "open_water_or_ice" and r[1] == "vegetated" and r[2] == "built_or_cropland"
    assert r[3] == "extra_gate" and r[4] == "missing_data"
    assert r[5] == "ok" and bool(out["passed"].iloc[5])


def test_missing_gate_layer_is_missing_data_not_pass():
    df = _earth().drop(columns=["ndvi_median"])
    out = G.apply_gates(df, CFG["gates"], ["slope_med"])
    assert (out["reason"] == "missing_data").all()


def test_extra_gate_expressions():
    assert G.extra_gate_expr(CFG["purposes"], "landing_mobility", "moon") == "slope_med <= 8"
    assert G.extra_gate_expr(CFG["purposes"], "landing_mobility", "mars") == "slope_p90 <= 30"
    assert G.extra_gate_expr(CFG["purposes"], "base", "moon") is None
    with pytest.raises(ValueError):
        G.eval_extra_gate(pd.DataFrame({"x": [1.0]}), "x ~ 3")


def test_mars_target_check_warns_by_default():
    ok = G.mars_target_check({"lat": 18.4, "elevation_m": -2500, "thermal_inertia_si": 300}, CFG["gates"])
    assert not ok["fails_own_gate"]
    bad = G.mars_target_check({"lat": 18.4, "elevation_m": 2500, "thermal_inertia_si": 80}, CFG["gates"])
    assert bad["fails_own_gate"] and set(bad["failed"]) == {"elevation", "thermal_inertia"}
    assert bad["mode"] == "warn" and not bad["skip"]
    unknown = G.mars_target_check({"lat": 18.4}, CFG["gates"])
    assert set(unknown["unknown"]) == {"elevation", "thermal_inertia"}
