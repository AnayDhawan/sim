"""D09: sensitivity to dropping a family, to the weight ranges and to the sigma IQR multiplier."""

import copy

import numpy as np
import pytest

from gsop import pipeline as P
from gsop import sensitivity as SE
from gsop.config import load_all
from gsop.config import validate
from gsop.provenance import read_json
from gsop.runner import BodyRun, hash_frame
from synth import IDS, make_synth

CFG = load_all()


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    syn = make_synth(3000)
    cfg = copy.deepcopy(CFG)
    cfg["run"].update({"batch_runs": 20, "convergence_checkpoints": [20]})
    cfg["run"]["sensitivity"] = {"runs": 40, "range_factors": [0.5, 1.5], "iqr_factors": [0.15, 0.25, 0.35]}
    job = P.prepare_job("moon", "t1", "base", cfg, syn.earth, syn.targets["moon"])
    job.spec.meas_unc = {c: 0.04 * abs(job.spec.target[c]) for c in job.spec.columns}      # so runs differ
    job.spec.batch_runs = 20
    rep = SE.run_sensitivity(job, cfg, tmp_path_factory.mktemp("sens"), runs=40)
    return syn, cfg, job, rep


def test_report_has_every_section_and_a_run_time(case):
    _, _, job, rep = case
    assert set(rep["drop_one_family"]) == set(job.profile_weights)
    assert set(rep["weight_ranges"]) == {"x0.5", "x1.5"}
    assert set(rep["sigma_iqr_factor"]) == {"0.15", "0.25", "0.35"}
    assert rep["seconds_total"] > 0 and rep["reference"]["seconds"] > 0 and rep["mc_runs"] == 40


def test_the_primary_iqr_factor_reproduces_the_index(case):
    _, _, job, rep = case
    d = rep["sigma_iqr_factor"]["0.25"]
    assert d["top1pct_overlap_jaccard"] == pytest.approx(1.0) and d["spearman"] == pytest.approx(1.0)
    assert d["overlap_jaccard"] == pytest.approx(1.0)                  # same spec, same seeds: same robust set


def test_other_iqr_factors_change_the_index(case):
    _, _, _, rep = case
    assert rep["sigma_iqr_factor"]["0.15"]["spearman"] < 1.0
    assert rep["sigma_iqr_factor"]["0.35"]["spearman"] < 1.0


def test_drop_one_family_overlaps_are_valid_and_differ_from_one(case):
    _, _, _, rep = case
    vals = [d["top1pct_overlap_jaccard"] for d in rep["drop_one_family"].values()]
    assert all(0 <= v <= 1 for v in vals) and min(vals) < 1.0
    assert all(-1 <= d["spearman"] <= 1 for d in rep["drop_one_family"].values())


def test_planted_analog_survives_every_variant(case):
    _, _, _, rep = case
    s = rep["survivors"]
    assert IDS["exact"] in s["tile_ids"] and s["n_survivors"] >= 1
    assert s["n_survivors"] <= s["n_reference_robust"]
    assert rep["reference"]["n_robust"] >= 1


def test_scale_ranges_keeps_the_midpoint_and_scales_the_width():
    r = SE.scale_ranges({"a": (0.2, 0.4), "b": (0.0, 0.02)}, 2.0)
    assert r["a"] == pytest.approx((0.1, 0.5))
    assert r["b"][0] == 0.001 and r["b"][1] == pytest.approx(0.03)            # lower end never below 0.001
    assert SE.scale_ranges({"a": (0.2, 0.4)}, 1.0)["a"] == pytest.approx((0.2, 0.4))


def test_sigma_with_iqr_factor_uses_the_jobs_other_two_terms(case):
    _, _, job, _ = case
    same = SE.sigma_with_iqr_factor(job, 0.25)
    for c, v in same.items():
        assert v == pytest.approx(job.sigma[c], rel=1e-6)
    wide = SE.sigma_with_iqr_factor(job, 1.0)
    assert all(wide[c] >= same[c] for c in same) and any(wide[c] > same[c] for c in same)


def test_markdown_table_lists_everything(case):
    md = SE.markdown(case[3])
    assert "Drop one family" in md and "sigma IQR factor 0.35" in md and "weight ranges x0.5" in md
    assert "Survivors:" in md and "Total run time" in md


def test_runner_writes_the_files_and_resumes(tmp_path):
    syn = make_synth(2000)
    cfg = copy.deepcopy(CFG)
    cfg["run"].update({"batch_runs": 20, "convergence_checkpoints": [20]})
    cfg["run"]["sensitivity"] = {"runs": 20, "range_factors": [1.5], "iqr_factors": [0.35]}
    cfg["purposes"]["profiles"]["moon"] = ["base"]
    cfg["targets"]["moon"] = {"t1": {"lat": -89.0, "lon_e": 0.0, "source": "synthetic"}}
    mk = lambda: BodyRun("moon", cfg, syn.earth, {"t1": syn.targets["moon"]}, tmp_path / "res", tmp_path / "work", 20, 1,
                         8 * 2**30, hash_frame(syn.earth))
    br = mk()
    br.run(("gates",))
    br.run_sensitivity()
    j = read_json(tmp_path / "res" / "t1__base" / "sensitivity.json")
    assert j["survivors"]["n_survivors"] >= 1 and (tmp_path / "res" / "t1__base" / "sensitivity.md").exists()
    br2 = mk()
    br2.run(("gates",))
    br2.run_sensitivity()
    assert [e["action"] for e in br2.events if e["stage"].startswith("sensitivity")] == ["skip"]
    cfg["run"]["sensitivity"]["iqr_factors"] = [0.2]
    br3 = mk()
    br3.run(("gates",))
    br3.run_sensitivity()
    assert [e["action"] for e in br3.events if e["stage"].startswith("sensitivity")] == ["run"]


def test_config_block_is_validated():
    bad = copy.deepcopy(CFG)
    bad["run"]["sensitivity"]["range_factors"] = []
    with pytest.raises(Exception, match="sensitivity.range_factors"):
        validate(bad)
