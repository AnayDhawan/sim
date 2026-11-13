"""A16: resumable stages. Finished stages are skipped by input + config + code hash, a crash resumes at the unfinished
stage, a changed config value reruns exactly the stages that depend on it, --force / --from, atomic writes."""

import copy
import shutil

import pandas as pd
import pytest

from gsop import pipeline as P
from gsop import runner as R
from gsop.config import load_all
from gsop.provenance import StageStore, atomic_to_parquet, read_json
from gsop.runner import BodyRun, hash_frame, stage_name, stages_from
from gsop.synthetic import make_earth, plant, target_profile

CFG = load_all()
MOON = {"slope_med": 4.0, "slope_p90": 9.0, "relief": 150.0, "rough_a": 0.4, "rough_b": 4.0, "sun_max_elev": 40.0,
        "sun_low_share": 0.2, "water_index": 0.5, "t_mean": 280.0, "t_coldest": 262.0, "silica_index": 1.0,
        "ti_proxy": 18.0}
ALL = ("gates", "score", "simulate", "ml", "validate", "discover", "export")


def _cfg():
    cfg = copy.deepcopy(CFG)
    cfg["run"].update({"batch_runs": 25, "runs": 25, "convergence_checkpoints": [25]})
    cfg["run"]["ml"].update({"n_negatives": 200})
    cfg["purposes"]["profiles"]["moon"] = ["base"]
    cfg["targets"]["moon"] = {"t1": {"lat": -89.0, "lon_e": 0.0, "source": "synthetic"}}
    earth_row = {"lonar": 10, "haughton": 20, "ladakh_puga": 30}
    for n in list(cfg["known_sites"]["primary"]):
        if n not in earth_row:
            cfg["known_sites"]["primary"].pop(n)
    return cfg, earth_row


@pytest.fixture(scope="module")
def earth():
    e = make_earth(2000, seed=5)
    for r in (10, 20, 30):
        e = plant(e, r, {k: v * (1 + 0.01 * r / 10) for k, v in MOON.items()})
    return e


def _make(tmp, earth, cfg=None, rows=None):
    cfg0, earth_row = _cfg()
    cfg = cfg or cfg0
    for n, row in (rows or earth_row).items():
        if n in cfg["known_sites"]["primary"]:
            cfg["known_sites"]["primary"][n].update({"lat": float(earth.loc[row, "lat"]),
                                                     "lon": float(earth.loc[row, "lon"]), "bodies": ["moon", "mars"]})
    return BodyRun("moon", cfg, earth, {"t1": target_profile(MOON)}, tmp / "res", tmp / "work", 25, 1, 8 * 2**30,
                   hash_frame(earth))


@pytest.fixture(scope="module")
def finished(tmp_path_factory, earth):
    tmp = tmp_path_factory.mktemp("finished")
    br = _make(tmp, earth)
    br.run(ALL)
    return tmp


def _copy(finished, tmp_path):
    shutil.copytree(finished / "res", tmp_path / "res")
    return tmp_path


def _actions(br):
    return {(e["stage"].split("__")[0]): e["action"] for e in br.events}


def test_stage_name_and_from():
    assert stage_name("s5") == "simulate" and stage_name("Simulate") == "simulate"
    assert stages_from("s6") == ("ml", "validate", "discover", "export")
    assert stages_from("score") == ("score", "simulate", "ml", "validate", "discover", "export")
    with pytest.raises(ValueError, match="unknown stage"):
        stage_name("s12")


def test_second_run_skips_everything_with_a_reason(finished, tmp_path, earth):
    t = _copy(finished, tmp_path)
    br = _make(t, earth)
    br.run(ALL)
    stage_events = [e for e in br.events]
    assert stage_events and all(e["action"] == "skip" for e in stage_events)
    assert {e["reason"] for e in stage_events} <= {"up to date", "covered by a finished simulate stage"}
    assert br.timings == {}
    log = read_json(t / "res" / "run_meta.json")["stage_log"]
    assert log == br.events


def test_crash_mid_stage_resumes_at_the_unfinished_stage(tmp_path, earth, monkeypatch):
    br = _make(tmp_path, earth)
    real = P.run_job

    def boom(job, cfg, out_dir, runs, workers, work_dir, free, with_mc=True):
        if with_mc:
            raise RuntimeError("laptop lid closed")
        return real(job, cfg, out_dir, runs, workers, work_dir, free, with_mc=with_mc)

    monkeypatch.setattr(P, "run_job", boom)
    with pytest.raises(RuntimeError, match="lid"):
        br.run(("gates", "score", "simulate"))
    store = StageStore(tmp_path / "res")
    assert store.read("gates__base") and store.read("score__t1__base")
    assert store.read("simulate__t1__base") is None            # no marker for the stage that died
    monkeypatch.setattr(P, "run_job", real)
    br2 = _make(tmp_path, earth)
    br2.run(("gates", "score", "simulate"))
    acts = {e["stage"]: e["action"] for e in br2.events}
    assert acts["gates__base"] == "skip" and acts["score__t1__base"] == "skip"
    assert acts["simulate__t1__base"] == "run"
    assert (tmp_path / "res" / "t1__base" / "mc_summary.parquet").exists()
    assert "n_robust" in read_json(tmp_path / "res" / "t1__base" / "summary.json")


@pytest.mark.parametrize("mutate, runs, skipped", [
    # the master seed feeds the Monte Carlo and the ML, not gates, base scores or validation
    (lambda c: c["run"].__setitem__("master_seed", 7), {"simulate", "ml", "discover"}, {"gates", "score", "validate"}),
    # ML settings touch only the ML stage
    (lambda c: c["run"]["ml"].__setitem__("n_negatives", 150), {"ml"}, {"gates", "score", "simulate", "validate", "discover"}),
    # a gate-test flag is read by validation and discovery's known-site list, not by scoring or the ML
    (lambda c: c["known_sites"]["gate_tests"]["samoylov"].__setitem__("confirmed", False), {"validate", "discover"},
     {"gates", "score", "simulate", "ml"}),
    # discovery distance
    (lambda c: c["run"]["discovery"].__setitem__("top_n", 5), {"discover"}, {"gates", "score", "simulate", "ml", "validate"}),
    # a gate threshold moves every tile table, so everything downstream reruns
    (lambda c: c["gates"]["tile_gates"].__setitem__("ndvi_median_max", 0.19),
     {"gates", "score", "simulate", "ml", "validate", "discover"}, set()),
])
def test_one_config_change_reruns_exactly_its_dependents(finished, tmp_path, earth, mutate, runs, skipped):
    t = _copy(finished, tmp_path)
    cfg, _ = _cfg()
    mutate(cfg)
    br = _make(t, earth, cfg)
    br.run(ALL)
    acts = _actions(br)
    assert {s for s, a in acts.items() if a == "run"} - {"score"} == runs - {"score"}
    assert all(acts[s] == "skip" for s in skipped), acts


def test_changed_code_reruns_every_stage(finished, tmp_path, earth, monkeypatch):
    t = _copy(finished, tmp_path)
    monkeypatch.setattr("gsop.provenance.code_version", lambda: "otherversion")
    br = _make(t, earth)
    br.run(("gates", "simulate", "validate"))
    assert br.events and all(e["action"] == "run" and e["reason"] == "code changed" for e in br.events)


def test_deleted_output_reruns_that_stage(finished, tmp_path, earth):
    t = _copy(finished, tmp_path)
    (t / "res" / "t1__base" / "mc_summary.parquet").unlink()
    br = _make(t, earth)
    br.run(("gates", "score", "simulate"))
    sim = next(e for e in br.events if e["stage"] == "simulate__t1__base")
    assert sim["action"] == "run" and "output missing: t1__base/mc_summary.parquet" in sim["reason"]
    assert (t / "res" / "t1__base" / "mc_summary.parquet").exists()


def test_force_reruns_one_stage_only(finished, tmp_path, earth):
    t = _copy(finished, tmp_path)
    br = _make(t, earth)
    br.run(ALL, force=["s5"])
    acts = {e["stage"]: (e["action"], e["reason"]) for e in br.events}
    assert acts["simulate__t1__base"] == ("run", "forced")
    assert acts["gates__base"][0] == "skip" and acts["score__t1__base"][0] == "skip"
    assert acts["validate__body"][0] == "skip"


def test_forcing_score_keeps_the_monte_carlo_fields_in_summary(finished, tmp_path, earth):
    t = _copy(finished, tmp_path)
    br = _make(t, earth)
    br.run(ALL, force=["score"])
    acts = {e["stage"]: e["action"] for e in br.events}
    assert acts["score__t1__base"] == "run" and acts["simulate__t1__base"] == "run"
    assert read_json(t / "res" / "t1__base" / "summary.json")["runs"] == 25


def test_from_stage_reruns_that_stage_and_later(finished, tmp_path, earth):
    t = _copy(finished, tmp_path)
    br = _make(t, earth)
    br.run(ALL, force=stages_from("s6"))
    acts = _actions(br)
    assert acts["gates"] == "skip" and acts["score"] == "skip" and acts["simulate"] == "skip"
    assert acts["ml"] == acts["validate"] == acts["discover"] == "run"


def test_atomic_parquet_never_leaves_a_half_written_file(tmp_path, monkeypatch):
    p = tmp_path / "x.parquet"
    atomic_to_parquet(pd.DataFrame({"a": [1, 2, 3]}), p)
    assert pd.read_parquet(p)["a"].tolist() == [1, 2, 3]

    def boom(self, path, *a, **k):
        open(path, "wb").write(b"PAR1 half")          # a partial file at the temp path
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", boom)
    with pytest.raises(OSError, match="disk full"):
        atomic_to_parquet(pd.DataFrame({"a": [9]}), p)
    assert pd.read_parquet(p)["a"].tolist() == [1, 2, 3]       # the old complete file is untouched
    assert [f.name for f in tmp_path.iterdir()] == ["x.parquet"]


def test_marker_records_outputs_and_code_version(finished):
    m = read_json(finished / "res" / ".stages" / "simulate__t1__base.json")
    assert "t1__base/mc_summary.parquet" in m["outputs"]
    assert len(m["key"]["code_version"]) == 10


def test_validate_stage_writes_the_baselines(finished):
    b = read_json(finished / "res" / "baselines.json")
    assert b["provisional"] is True and "t1" in b["targets"]
    assert {"equal", "liu2025", "no_illumination", "only_slope"} <= set(b["targets"]["t1"]["baselines"])
    assert "| primary index |" in (finished / "res" / "baselines.md").read_text(encoding="utf-8")
    assert "baselines.json" in read_json(finished / "res" / ".stages" / "validate__body.json")["outputs"]
