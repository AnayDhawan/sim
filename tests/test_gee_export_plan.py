"""Offline checks of the Earth Engine export plumbing: config, tiling plan, loader fallbacks and the no-login behaviour."""
import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine
from typer.testing import CliRunner

from gsop.cli import app
from gsop.earth import gee_export as GX
from gsop.earth.local_loaders import build_earth_table
from gsop.grid import Grid


def test_layers_config_has_every_source_and_flags_what_is_not_built():
    L = GX.load_layers()
    ids = GX.collection_ids(L)
    assert ids["dem_primary"] == "NASA/NASADEM_HGT/001" and ids["modis_lst"] == "MODIS/061/MOD11A2"
    assert set(L["not_built"]) == {"water_index", "silica_index", "dust_index"}
    assert all("/" in v for v in ids.values())


def test_exported_bands_are_real_feature_columns():
    from gsop.config import load_all
    f = load_all()["features"]
    cols = set(f["columns"]) | set(f["gate_layers"]) | set(f["flags"]) | {"land_frac"}
    assert set(GX.BAND_ORDER) <= cols
    assert not {"water_index", "silica_index", "dust_index"} & set(GX.BAND_ORDER)


def test_plan_windows_cover_the_window_exactly_once():
    g = Grid()
    win = (10, 20, 10 + 450, 20 + 230)
    blocks = GX.plan_windows(g, win, 200)
    assert len(blocks) == 3 * 2
    cells = np.zeros((230, 450), dtype=int)
    for ix0, iy0, ix1, iy1 in blocks:
        cells[iy0 - 20:iy1 - 20, ix0 - 10:ix1 - 10] += 1
    assert (cells == 1).all()


def test_driest_triplets_wrap_the_year():
    t = GX.month_triplets()
    assert len(t) == 12 and (11, 12, 1) in t and (12, 1, 2) in t and (1, 2, 3) in t


def test_dry_run_prints_a_plan_and_needs_no_login(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(app, ["s2", "earth", "--source", "gee", "--bbox", "74,17,80,22", "--dry-run"])
    assert r.exit_code == 0, r.output
    plan = json.loads((tmp_path / "data/raw/earth/gsop_earth_export_plan.json").read_text())
    assert plan["tasks"] and plan["band_order"][0] == "land_frac"


def test_a_missing_login_stops_loudly_and_is_not_worked_around(monkeypatch):
    import ee
    monkeypatch.setattr(ee, "Initialize", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no credentials")))
    with pytest.raises(RuntimeError, match="Not working around this"):
        GX.init()
    r = CliRunner().invoke(app, ["check-operators"])
    assert r.exit_code == 1 and "Not working around this" in " ".join(r.output.split())


def _tif(path, names, with_desc, ix0=3000, iy0=1000, h=3, w=3, fill=None):
    g = Grid()
    with rasterio.open(path, "w", driver="GTiff", height=h, width=w, count=len(names), dtype="float32", crs="EPSG:6933",
                       transform=Affine(6000, 0, g.x0 + ix0 * 6000, 0, -6000, g.y_top - iy0 * 6000)) as ds:
        for i, n in enumerate(names, 1):
            ds.write(np.full((h, w), float(i) if fill is None else fill, dtype="float32"), i)
            if with_desc:
                ds.set_band_description(i, n)


def test_exporter_and_loader_agree_on_band_names(tmp_path, monkeypatch):
    """Review item 3: the loader used to read a sidecar nobody wrote, and the exporter wrote a plan nobody read."""
    monkeypatch.chdir(tmp_path)
    tasks = GX.run((74.0, 17.0, 80.0, 22.0), "lonar_test", dry_run=True)
    folder = tmp_path / "data" / "raw" / "earth"
    desc = tasks[0]["description"]
    _tif(folder / f"{desc}.tif", GX.BAND_ORDER, with_desc=False)          # what a Drive download looks like: no descriptions
    df = build_earth_table(folder, tmp_path / "o" / "e.parquet")
    assert set(GX.BAND_ORDER) - {"land_frac"} <= set(df.columns)
    assert (df["slope_med"] == GX.BAND_ORDER.index("slope_med") + 1).all()   # band 5 landed in slope_med
    assert "ti_is_fallback" in df.columns
    _tif(folder / "stranger.tif", GX.BAND_ORDER, with_desc=False)         # not in any plan: refuse to guess
    (folder / f"{desc}.tif").rename(tmp_path / "moved.tif")
    with pytest.raises(ValueError, match="refusing to guess"):
        build_earth_table(folder, tmp_path / "o2" / "e.parquet")


def test_per_band_download_names_give_the_band(tmp_path):
    _tif(tmp_path / "abc123.land_frac.tif", ["x"], with_desc=False)
    _tif(tmp_path / "abc123.slope_med.tif", ["x"], with_desc=False, fill=7.0)
    df = build_earth_table(tmp_path, tmp_path / "o" / "e.parquet")
    assert (df["slope_med"] == 7.0).all() and len(df) == 9


def test_blocks_of_a_chunked_export_are_concatenated_and_overlaps_are_refused(tmp_path):
    _tif(tmp_path / "a.tif", ["land_frac", "slope_med"], True, ix0=3000, iy0=1000)
    _tif(tmp_path / "b.tif", ["land_frac", "slope_med"], True, ix0=3003, iy0=1000)
    df = build_earth_table(tmp_path, tmp_path / "o" / "e.parquet")
    assert len(df) == 18 and df["tile_id"].is_unique
    _tif(tmp_path / "c.tif", ["land_frac", "slope_med"], True, ix0=3001, iy0=1000)
    with pytest.raises(ValueError, match="overlap"):
        build_earth_table(tmp_path, tmp_path / "o2" / "e.parquet")


def test_blocks_with_different_columns_are_refused(tmp_path):
    _tif(tmp_path / "a.tif", ["land_frac", "slope_med"], True, ix0=3000)
    _tif(tmp_path / "b.tif", ["land_frac", "relief"], True, ix0=3010)
    with pytest.raises(ValueError, match="same columns"):
        build_earth_table(tmp_path, tmp_path / "o" / "e.parquet")


def test_add_solar_adds_columns_but_never_overwrites(tmp_path):
    _tif(tmp_path / "y.tif", ["land_frac", "sun_max_elev"], with_desc=True)
    df = build_earth_table(tmp_path / "y.tif", tmp_path / "o" / "e.parquet", add_solar=True)
    assert (df["sun_max_elev"] == 2.0).all()                       # the raster's own band is kept
    assert {"sun_low_share", "insol_annual"} <= set(df.columns)
    plain = build_earth_table(tmp_path / "y.tif", tmp_path / "o2" / "e.parquet")
    assert "sun_low_share" not in plain.columns                   # nothing is added unless asked


def test_verify_exit_code_is_not_swallowed(monkeypatch):
    """Review item 2: typer.Exit is a RuntimeError, so raising it inside `except RuntimeError` turned PASS into exit 1."""
    ok = [{"id": "A/B", "reachable": True, "bands_missing": []}, {"id": "C/D", "reachable": True, "bands_missing": []}]
    monkeypatch.setattr(GX, "verify", lambda project=None: ok)
    r = CliRunner().invoke(app, ["s2", "earth", "--source", "gee", "--verify"])
    assert r.exit_code == 0 and "[FAIL]" not in r.output and "PASS" in r.output
    bad = ok + [{"id": "E/F", "reachable": True, "bands_missing": ["DEM"]}]
    monkeypatch.setattr(GX, "verify", lambda project=None: bad)
    r = CliRunner().invoke(app, ["s2", "earth", "--source", "gee", "--verify"])
    assert r.exit_code == 1 and "E/F" in r.output
    monkeypatch.setattr(GX, "verify", lambda project=None: (_ for _ in ()).throw(RuntimeError("no login")))
    r = CliRunner().invoke(app, ["s2", "earth", "--source", "gee", "--verify"])
    assert r.exit_code == 1 and "no login" in r.output


def test_dem_fallback_is_the_non_deprecated_collection():
    assert GX.load_layers()["dem"]["fallback"]["id"] == "COPERNICUS/DEM/GLO30_2024_1"
