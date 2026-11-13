"""C14: s4 score stage outputs: base similarity per target x profile, family similarities, sigma table, weights used."""

import copy
import logging

import numpy as np
import pandas as pd
import pytest

from gsop import similarity as S
from gsop.config import load_all
from gsop.provenance import read_json
from gsop.runner import BodyRun, hash_frame
from synth import IDS, make_synth

CFG = load_all()


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    syn = make_synth(3000)
    cfg = copy.deepcopy(CFG)
    cfg["purposes"]["profiles"]["moon"] = ["base", "landing_mobility", "power_night"]
    cfg["targets"]["moon"] = {"t1": {"lat": -89.0, "lon_e": 0.0, "source": "synthetic"}}
    tmp = tmp_path_factory.mktemp("s4")
    br = BodyRun("moon", cfg, syn.earth, {"t1": syn.targets["moon"]}, tmp / "res", tmp / "work", 20, 1, 8 * 2**30,
                 hash_frame(syn.earth))
    import logging as lg
    records = []

    class H(lg.Handler):
        def emit(self, rec):
            records.append(rec.getMessage())
    h = H()
    lg.getLogger("gsop.pipeline").addHandler(h)
    lg.getLogger("gsop.pipeline").setLevel(lg.INFO)
    try:
        br.run(("gates", "score"))
    finally:
        lg.getLogger("gsop.pipeline").removeHandler(h)
    return br, syn, tmp / "res", records


@pytest.mark.parametrize("profile", ["base", "landing_mobility", "power_night"])
def test_planted_analog_ranks_first_for_every_profile(run, profile):
    br, syn, res, _ = run
    df = pd.read_parquet(res / f"t1__{profile}" / "base_scores.parquet")
    assert df.loc[df["score"].idxmax(), "tile_id"] == IDS["exact"]
    assert df["score"].max() == pytest.approx(100.0, abs=1e-3)
    assert df["score"].dtype == np.float32 and ((df["score"] >= 0) & (df["score"] <= 100)).all()


def test_scores_are_for_gated_tiles_only_and_carry_family_similarities(run):
    br, syn, res, _ = run
    df = pd.read_parquet(res / "t1__base" / "base_scores.parquet")
    gate = pd.read_parquet(res / "gates__base.parquet").set_index("tile_id")
    assert set(df["tile_id"]) == set(gate.index[gate["code"] == 0])
    fams = list(CFG["weights"]["moon"])
    for f in fams:
        col = df[f"fam_{f}"]
        assert col.dtype == np.float32 and ((col >= 0) & (col <= 1)).all()
    row = df[df["tile_id"] == IDS["exact"]].iloc[0]
    assert all(row[f"fam_{f}"] == pytest.approx(1.0) for f in fams)
    weights = read_json(res / "t1__base" / "weights_used.json")["weights"]
    recomputed = 100 * sum(weights[f] * df[f"fam_{f}"].to_numpy(np.float64) for f in fams)
    np.testing.assert_allclose(df["score"], recomputed, atol=2e-3)


def test_illumination_match_is_the_illumination_family_alone(run):
    _, _, res, _ = run
    df = pd.read_parquet(res / "t1__base" / "base_scores.parquet")
    np.testing.assert_array_equal(df["illum_match"], df["fam_illumination"])


def test_sigma_table_lists_the_three_terms_and_the_binding_one(run):
    _, syn, res, _ = run
    t = read_json(res / "t1__base" / "sigma_table.json")
    assert "0.25" in t["rule"]
    for c, row in t["columns"].items():
        assert row["sigma"] == pytest.approx(max(row["target_spread"] or 0, row["measurement_uncertainty"] or 0, row["iqr_floor"]))
        assert row["binding"] in ("target_spread", "measurement_uncertainty", "iqr_floor")
        assert row["iqr_floor"] == pytest.approx(0.25 * row["iqr_earth"])
    assert read_json(res / "t1__base" / "summary.json")["sigma"]["slope_med"] == pytest.approx(t["columns"]["slope_med"]["sigma"])


def test_weights_used_are_the_profile_weights(run):
    _, _, res, _ = run
    b = read_json(res / "t1__base" / "weights_used.json")
    p = read_json(res / "t1__power_night" / "weights_used.json")
    assert sum(b["weights"].values()) == pytest.approx(1.0) and sum(p["weights"].values()) == pytest.approx(1.0)
    assert b["multipliers"] == {} and p["multipliers"]["illumination"] == 2.5
    assert p["weights"]["illumination"] > b["weights"]["illumination"]
    assert b["weights"] == pytest.approx(b["derived_base_weights"])


def test_run_time_and_memory_are_logged_and_stored(run):
    _, _, res, records = run
    s = read_json(res / "t1__base" / "summary.json")
    assert s["seconds"] > 0 and s["rss_mb"] > 0
    assert any(m.startswith("t1__base:") and "gated tiles scored" in m and "MB" in m for m in records)


def test_sigma_terms_unit():
    t = S.sigma_terms(1.0, 2.0, 40.0)
    assert t["sigma"] == pytest.approx(10.0) and t["binding"] == "iqr_floor"
    assert S.sigma_terms(5.0, 0.5, 4.0)["binding"] == "target_spread"
    assert S.sigma_terms(None, 3.0, 4.0)["binding"] == "measurement_uncertainty"
    assert S.sigma_terms(0.0, None, 0.0)["binding"] == "minimum"
