"""--lat-band robustness run option and scripts/compare_runs.py (DECISIONS E29), plus the slope label stamp."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gsop.provenance import SLOPE_LABEL, run_meta


def test_run_meta_carries_the_slope_label():
    m = run_meta("h", {}, {})
    assert m["slope_ground_scale_corrected"] is False and m["slope_limitation"] == SLOPE_LABEL["slope_limitation"]
    assert "30 deg" in SLOPE_LABEL["slope_limitation"]


def test_lat_band_restricts_scored_tiles_and_names_the_results_folder(tmp_path, monkeypatch):
    import gsop.cli as cli
    from typer.testing import CliRunner

    e = pd.DataFrame({"tile_id": range(6), "lat": [-45.0, -40.0, -25.0, 19.9, 20.0, 41.0], "lon": 0.0})
    sub = cli.restrict_lat_band(e, (20.0, 40.0))
    assert list(sub["lat"]) == [-40.0, -25.0, 20.0] and list(sub.index) == [0, 1, 2]
    assert cli.band_label((20.0, 40.0)) == "_lat20-40" and cli.band_label(None) == ""
    proc = tmp_path / "data" / "processed"
    proc.mkdir(parents=True)
    e.to_parquet(proc / "earth_features_6km.parquet")
    (proc / "targets_moon.parquet").write_bytes(b"x")
    seen = {}

    class FakeRun:
        def __init__(self, body, cfg, earth, tprofs, res_dir, work_dir, *a, **k):
            seen.update(n=len(earth), res=Path(res_dir).name, work=Path(work_dir).name, hash=a[3])
            self.extra_meta, self.unscored = {}, {}

        def run(self, stages):
            seen["extra"] = dict(self.extra_meta)

    monkeypatch.setattr(cli, "data_dir", lambda sub: (tmp_path / "data" / sub))
    monkeypatch.setattr(cli, "results_dir", lambda b=None: tmp_path / "results" / b)
    monkeypatch.setattr(cli, "BodyRun", FakeRun)
    monkeypatch.setattr(cli.P, "load_target_profiles", lambda p: {})
    r = CliRunner().invoke(cli.app, ["run", "--body", "moon", "--runs", "50", "--lat-band", "20", "40"])
    assert r.exit_code == 0, r.output
    assert seen["n"] == 3 and seen["res"] == "moon_lat20-40" and seen["work"] == "moon_lat20-40"
    assert seen["hash"].endswith("_lat20-40") and seen["extra"]["lat_band_abs_deg"] == [20.0, 40.0]
    assert "results/moon_lat20-40/" in " ".join(r.output.split())
    r = CliRunner().invoke(cli.app, ["run", "--body", "moon", "--lat-band", "40", "20"])
    assert r.exit_code == 2


def test_compare_runs_reports_overlap_and_top20_outside_band(tmp_path):
    from gsop.grid import Grid
    spec = importlib.util.spec_from_file_location("compare_runs", Path(__file__).parents[1] / "scripts" / "compare_runs.py")
    CR = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(CR)
    g = Grid()
    iy_in, iy_out = int(g.cell_of_lonlat(0.0, 30.0)[1]), int(g.cell_of_lonlat(0.0, 5.0)[1])
    tid_in = [iy_in * g.ncols + i for i in range(200)]
    tid_out = [iy_out * g.ncols + i for i in range(100)]
    lat_in, lat_out = float(g.centre_lonlat(0, iy_in)[1]), float(g.centre_lonlat(0, iy_out)[1])
    full, band = tmp_path / "moon", tmp_path / "moon_lat20-40"
    for d, tids in ((full, tid_in + tid_out), (band, tid_in)):
        j = d / "t1__base"
        j.mkdir(parents=True)
        score = np.arange(len(tids), dtype=float)[::-1]          # first tiles score highest
        if d is full:
            score = np.r_[score[:200] - 100, np.arange(100, dtype=float) + 1000]   # out-of-band tiles score highest
        pd.DataFrame({"tile_id": tids, "score": score}).to_parquet(j / "base_scores.parquet")
        lats = [lat_in] * 200 + ([lat_out] * 100 if d is full else [])
        pd.DataFrame({"tile_id": tids, "lat": lats, "lon": 0.0, "mc_median": score,
                      "robust": [True] * len(tids)}).to_parquet(j / "mc_summary.parquet")
    (band / "run_meta.json").write_text(json.dumps({"lat_band_abs_deg": [20.0, 40.0]}))
    res = CR.compare(full, band)
    j = res["jobs"]["t1__base"]
    assert j["jaccard_top1pct"] == 0.0                                    # full top 3 of 300 are all outside the band
    assert j["jaccard_top1pct_inband"] == 0.0
    assert j["jaccard_robust"] == pytest.approx(200 / 300) and j["jaccard_robust_inband"] == pytest.approx(1.0)
    assert j["n_top20_robust_full_inside_band"] == 0 and len(j["top20_robust_full_outside_band"]) == 20
    assert all(abs(t["lat"]) < 20 for t in j["top20_robust_full_outside_band"])
    same = CR.compare(band, band, (20.0, 40.0))["jobs"]["t1__base"]
    assert same["jaccard_top1pct"] == 1.0 and same["jaccard_robust"] == 1.0
