"""C10: every gate with reason codes, bitmask for several failures, near-miss, chunk-safe, thresholds from config."""

import copy

import numpy as np
import pandas as pd
import pytest

from gsop import gates as G
from gsop.config import load_all

CFG = load_all()
GATES = CFG["gates"]


def tiles(rows):
    base = {"slope_med": 3.0, "water_index": 0.5, "water_ice_frac": 0.0, "ndvi_median": 0.05, "built_crop_frac": 0.0}
    df = pd.DataFrame([{**base, **r} for r in rows])
    df.insert(0, "tile_id", np.arange(len(df), dtype=np.int64))
    return df


def test_each_gate_has_its_reason():
    df = tiles([{}, {"water_ice_frac": 0.6}, {"ndvi_median": 0.3}, {"built_crop_frac": 0.3}, {"slope_med": 12.0},
                {"slope_med": np.nan}, {"ndvi_median": np.nan}])
    g = G.apply_gates(df, GATES, ["slope_med", "water_index"], "slope_med <= 8")
    assert g["reason"].tolist() == ["ok", "open_water_or_ice", "vegetated", "built_or_cropland", "extra_gate",
                                    "missing_data", "missing_data"]
    assert g["passed"].tolist() == [True] + [False] * 6


def test_a_tile_can_fail_several_gates_and_keeps_every_reason():
    df = tiles([{"water_ice_frac": 0.9, "ndvi_median": 0.5, "built_crop_frac": 0.4, "slope_med": 20.0}])
    g = G.apply_gates(df, GATES, ["slope_med"], "slope_med <= 8")
    assert g.loc[0, "reason"] == "open_water_or_ice"                # one reporting reason, by priority
    assert G.decode_mask(int(g.loc[0, "mask"])) == ["open_water_or_ice", "vegetated", "built_or_cropland", "extra_gate"]


def test_missing_data_is_reported_first_but_other_failures_stay_in_the_mask():
    df = tiles([{"water_ice_frac": 0.9, "slope_med": np.nan}])
    g = G.apply_gates(df, GATES, ["slope_med"])
    assert g.loc[0, "reason"] == "missing_data"
    assert G.decode_mask(int(g.loc[0, "mask"])) == ["open_water_or_ice", "missing_data"]


def test_missing_gate_layer_column_counts_as_missing_data():
    df = tiles([{}]).drop(columns=["ndvi_median"])
    assert G.apply_gates(df, GATES, ["slope_med"]).loc[0, "reason"] == "missing_data"


def test_a_column_used_only_by_the_target_weights_gates_the_tile():
    df = tiles([{"water_index": np.nan}])
    assert G.apply_gates(df, GATES, ["slope_med"]).loc[0, "passed"]
    assert not G.apply_gates(df, GATES, ["slope_med", "water_index"]).loc[0, "passed"]


def test_near_miss_flags_passing_tiles_within_ten_percent_of_a_threshold():
    t = GATES["tile_gates"]
    df = tiles([{"ndvi_median": t["ndvi_median_max"] * 0.95},          # passes, 5% below the threshold
                {"ndvi_median": t["ndvi_median_max"] * 0.5},           # passes comfortably
                {"ndvi_median": t["ndvi_median_max"] * 1.05},          # fails: rejected, never a near miss
                {"slope_med": 7.5}])                                   # passes the extra gate within 10%
    g = G.apply_gates(df, GATES, ["slope_med"], "slope_med <= 8")
    assert g["near"].tolist() == [G.NEAR_BIT["vegetated"], 0, 0, G.NEAR_BIT["extra_gate"]]
    assert g["passed"].tolist() == [True, True, False, True]


def test_near_miss_band_comes_from_config():
    df = tiles([{"ndvi_median": 0.17}])
    assert G.apply_gates(df, GATES, ["slope_med"]).loc[0, "near"] == 0
    wide = copy.deepcopy(GATES)
    wide["near_miss_frac"] = 0.2
    assert G.apply_gates(df, wide, ["slope_med"]).loc[0, "near"] == G.NEAR_BIT["vegetated"]


def test_no_threshold_is_hard_coded():
    df = tiles([{"water_ice_frac": 0.4, "ndvi_median": 0.15, "built_crop_frac": 0.1}])
    assert G.apply_gates(df, GATES, ["slope_med"]).loc[0, "passed"]
    strict = copy.deepcopy(GATES)
    strict["tile_gates"].update({"open_water_or_ice_frac_max": 0.3, "ndvi_median_max": 0.1, "built_or_crop_frac_max": 0.05})
    g = G.apply_gates(df, strict, ["slope_med"])
    assert G.decode_mask(int(g.loc[0, "mask"])) == ["open_water_or_ice", "vegetated", "built_or_cropland"]


def test_chunked_evaluation_equals_one_pass():
    from gsop.synthetic import make_earth
    e = make_earth(5000, seed=3)
    e.loc[::17, "slope_med"] = np.nan
    whole = G.apply_gates(e, GATES, ["slope_med", "relief"], "slope_med <= 8", chunk_rows=10**9)
    for chunk in (1, 7, 999, 5000):
        pd.testing.assert_frame_equal(G.apply_gates(e, GATES, ["slope_med", "relief"], "slope_med <= 8", chunk_rows=chunk), whole)


def test_empty_input():
    g = G.apply_gates(tiles([{}]).iloc[:0], GATES, ["slope_med"])
    assert len(g) == 0


def test_counts_and_passed_rejected_tables():
    df = tiles([{}, {"water_ice_frac": 0.9, "ndvi_median": 0.5}, {"ndvi_median": 0.19}, {"slope_med": np.nan}])
    g = G.apply_gates(df, GATES, ["slope_med"])
    c = G.reason_counts(g)
    assert c["n_tiles"] == 4 and c["n_passed"] == 2 and c["n_rejected"] == 2
    assert c["primary"] == {"open_water_or_ice": 1, "missing_data": 1}
    assert c["any"]["vegetated"] == 1 and c["any"]["open_water_or_ice"] == 1
    assert c["near_miss"]["vegetated"] == 1
    passed, rejected = G.passed_rejected(g)
    assert passed["tile_id"].tolist() == [0, 2] and rejected["tile_id"].tolist() == [1, 3]
    assert "reason" in rejected.columns and "mask" in rejected.columns and "near" in passed.columns
    assert "2 of 4 tiles pass" in G.format_counts(c, "moon/base")
