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
    cols = set(load_all()["features"]["columns"]) | set(load_all()["features"]["gate_layers"]) | {"land_frac"}
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


def _tif(path, names, with_desc):
    g = Grid()
    with rasterio.open(path, "w", driver="GTiff", height=3, width=3, count=len(names), dtype="float32", crs="EPSG:6933",
                       transform=Affine(6000, 0, g.x0 + 3000 * 6000, 0, -6000, g.y_top - 1000 * 6000)) as ds:
        for i, n in enumerate(names, 1):
            ds.write(np.full((3, 3), float(i), dtype="float32"), i)
            if with_desc:
                ds.set_band_description(i, n)


def test_loader_reads_band_names_from_a_sidecar_when_the_tiff_has_none(tmp_path):
    _tif(tmp_path / "x.tif", ["land_frac", "slope_med"], with_desc=False)
    (tmp_path / "x.tif.bands.json").write_text(json.dumps(["land_frac", "slope_med"]))
    df = build_earth_table(tmp_path / "x.tif", tmp_path / "o" / "e.parquet")
    assert "slope_med" in df.columns and (df["slope_med"] == 2.0).all()


def test_add_solar_adds_columns_but_never_overwrites(tmp_path):
    _tif(tmp_path / "y.tif", ["land_frac", "sun_max_elev"], with_desc=True)
    df = build_earth_table(tmp_path / "y.tif", tmp_path / "o" / "e.parquet", add_solar=True)
    assert (df["sun_max_elev"] == 2.0).all()                       # the raster's own band is kept
    assert {"sun_low_share", "insol_annual"} <= set(df.columns)
    plain = build_earth_table(tmp_path / "y.tif", tmp_path / "o2" / "e.parquet")
    assert "sun_low_share" not in plain.columns                   # nothing is added unless asked
