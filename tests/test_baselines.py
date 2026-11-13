"""D07: baselines (single variable, equal weights, Liu 2025, Mashal 2025, no_illumination) against the primary index."""

import json

import numpy as np
import pytest

from gsop import pipeline as P
from gsop import validate as V
from gsop import weights as W
from gsop.config import load_all
from synth import IDS, SINGLE_FAMILY_BASE, SINGLE_FAMILY_ORDER, make_synth

CFG = load_all()


def site_at(e, tile, dlat=0.04):
    return {"lat": float(e.loc[tile, "lat"]) + dlat, "lon": float(e.loc[tile, "lon"]), "confirmed": True}


@pytest.fixture(scope="module")
def syn():
    return make_synth(4000)


def report(syn, body, site_tile):
    e = syn.earth
    job = P.prepare_job(body, "t1", "base", CFG, e, syn.targets[body])
    rows = job.gated_rows
    sets = {**W.alt_weight_sets(body, CFG["weights"]), **V.single_variable_sets(list(job.fam_cols))}
    ks = {"primary": {"s": {**site_at(e, site_tile), "bodies": [body]}}, "negative_controls": {"c": site_at(e, 3999)},
          "secondary": {}, "gate_tests": {}, "criteria": CFG["known_sites"]["criteria"]}
    return V.compute_baselines(body, "t1", P.fam_arrays(job), job.profile_weights, sets, e["lat"].to_numpy()[rows],
                               e["lon"].to_numpy()[rows], ks, 20.0), job


def test_every_baseline_is_scored_and_compared(syn):
    rep, job = report(syn, "moon", IDS["exact"])
    names = set(rep["baselines"])
    assert {"liu2025", "no_illumination", "equal"} <= names
    assert {f"only_{f}" for f in job.fam_cols} <= names
    for n, m in rep["baselines"].items():
        assert 0.0 <= m["top1pct_overlap_jaccard"] <= 1.0 and -1.0 <= m["spearman_vs_primary"] <= 1.0, n
        assert sum(m["weights"].values()) == pytest.approx(1.0)
        assert m["comparability"] and "primary_median_rank_pct" in m


def test_mars_has_mashal_and_no_liu(syn):
    rep, _ = report(syn, "mars", IDS["exact"])
    assert "mashal2025" in rep["baselines"] and "liu2025" not in rep["baselines"]
    w = rep["baselines"]["mashal2025"]["weights"]
    assert {f for f, v in w.items() if v > 0} == {"composition", "water", "sunlight"}         # the rest are 0


def test_a_baseline_equal_to_the_primary_overlaps_fully_and_beats_nothing(syn):
    e = syn.earth
    job = P.prepare_job("moon", "t1", "base", CFG, e, syn.targets["moon"])
    rows = job.gated_rows
    ks = {"primary": {}, "negative_controls": {}, "secondary": {}, "gate_tests": {}, "criteria": {}}
    rep = V.compute_baselines("moon", "t", P.fam_arrays(job), job.profile_weights, {"same": dict(job.profile_weights)},
                              e["lat"].to_numpy()[rows], e["lon"].to_numpy()[rows], ks, 20.0)
    m = rep["baselines"]["same"]
    assert m["top1pct_overlap_jaccard"] == pytest.approx(1.0) and m["spearman_vs_primary"] == pytest.approx(1.0)
    assert rep["beats_primary"] == []
    assert m["comparability"].startswith("custom baseline")


def test_site_that_matches_one_family_is_beaten_by_the_single_variable_baseline_and_it_says_so(syn):
    tile = SINGLE_FAMILY_BASE + SINGLE_FAMILY_ORDER.index("slope")
    rep, _ = report(syn, "moon", tile)
    assert rep["primary"]["primary_median_rank_pct"] < rep["baselines"]["only_slope"]["primary_median_rank_pct"]
    assert rep["baselines"]["only_slope"]["beats_primary_on_site_ranks"] is True
    assert "only_slope" in rep["beats_primary"] and "BASELINES THAT BEAT" in rep["verdict"]
    md = V.baselines_markdown(rep)
    assert "only_slope **(beats primary)**" in md and "| primary index |" in md
    assert "NOT apples-to-apples" in md


def test_exact_analog_site_is_not_beaten_by_any_baseline(syn):
    rep, _ = report(syn, "moon", IDS["exact"])
    assert rep["primary"]["primary_median_rank_pct"] > 99.9
    assert rep["beats_primary"] == [] and rep["verdict"].startswith("No baseline")


def test_comparability_labels_follow_the_baseline_kind(syn):
    rep, _ = report(syn, "moon", IDS["exact"])
    b = rep["baselines"]
    assert b["equal"]["comparability"].startswith("apples-to-apples")
    assert b["no_illumination"]["comparability"].startswith("apples-to-apples")
    assert b["only_relief"]["comparability"].startswith("apples-to-apples")
    assert b["liu2025"]["comparability"].startswith("NOT apples-to-apples")


def test_site_rank_pcts_handles_a_site_with_no_tile_and_is_json_ready():
    lat, lon = np.array([0.0, 1.0, 2.0]), np.array([0.0, 0.0, 0.0])
    s = np.array([1.0, 3.0, 2.0])
    out = V.site_rank_pcts(s, lat, lon, {"near1": {"lat": 1.0, "lon": 0.0}, "nowhere": {"lat": 50.0, "lon": 50.0}}, 20.0)
    assert out == {"near1": pytest.approx(100 * 2 / 3), "nowhere": 0.0}
    json.dumps(out)


def test_single_variable_sets_are_one_family_each():
    sets = V.single_variable_sets(["a", "b", "c"])
    assert sets["only_b"] == {"a": 0.0, "b": 1.0, "c": 0.0}
