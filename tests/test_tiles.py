"""C02: s1 tiles. Land mask -> tiles.parquet, chunked, count checked, resumable."""

import logging

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import Affine

from gsop import tiles as TL
from gsop.config import load_all
from gsop.grid import Grid
from gsop.provenance import StageStore

G = Grid()
RUN = load_all()["run"]


def write_raster(path, land, ix0=3000, iy0=1000, name="land_frac", nodata=None):
    h, w = land.shape
    with rasterio.open(path, "w", driver="GTiff", height=h, width=w, count=1, dtype="float32", crs="EPSG:6933",
                       transform=Affine(6000.0, 0, G.x0 + ix0 * 6000.0, 0, -6000.0, G.y_top - iy0 * 6000.0),
                       nodata=nodata) as ds:
        ds.write(land.astype("float32"), 1)
        ds.set_band_description(1, name)


@pytest.fixture()
def land():
    rng = np.random.default_rng(0)
    a = (rng.random((37, 23)) > 0.4).astype(float)
    a[0, 0], a[1, 1] = 0.5, 0.49                       # on and just under the land threshold
    return a


def test_columns_values_and_count(tmp_path, land):
    write_raster(tmp_path / "l.tif", land)
    rep = TL.build_tiles(tmp_path / "l.tif", tmp_path / "t.parquet", chunk_rows=5, expected=len(np.flatnonzero(land >= 0.5)))
    df = pd.read_parquet(tmp_path / "t.parquet")
    assert list(df.columns) == TL.COLUMNS
    assert len(df) == rep["n_land_tiles"] == int((land >= 0.5).sum()) and rep["far_off"] is False
    r = df.iloc[0]
    assert (r.ix, r.iy) == (3000, 1000) and r.tile_id == G.tile_id(3000, 1000) and r.land_frac == 0.5
    x, y = G.centre_xy(df.ix, df.iy)
    np.testing.assert_allclose(df["x"], x)
    np.testing.assert_allclose(df["y"], y)
    lon, lat = G.centre_lonlat(df.ix, df.iy)
    np.testing.assert_allclose(df["lon"], lon)
    np.testing.assert_allclose(df["lat"], lat)
    assert df["tile_id"].is_unique and df["tile_id"].dtype == np.int64
    assert ((df["ix"] == 3001) & (df["iy"] == 1001)).sum() == 0            # 0.49 is not land


@pytest.mark.parametrize("chunk", [1, 4, 37, 1000])
def test_chunk_size_does_not_change_the_output(tmp_path, land, chunk):
    write_raster(tmp_path / "l.tif", land)
    TL.build_tiles(tmp_path / "l.tif", tmp_path / "big.parquet", chunk_rows=10_000)
    TL.build_tiles(tmp_path / "l.tif", tmp_path / "c.parquet", chunk_rows=chunk)
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "big.parquet"), pd.read_parquet(tmp_path / "c.parquet"))


def test_nodata_is_not_land(tmp_path):
    a = np.ones((4, 4))
    a[1, 1] = -9999
    write_raster(tmp_path / "l.tif", a, nodata=-9999)
    rep = TL.build_tiles(tmp_path / "l.tif", tmp_path / "t.parquet")
    assert rep["n_land_tiles"] == 15


def test_count_far_from_the_plans_expectation_is_flagged(tmp_path, land):
    write_raster(tmp_path / "l.tif", land)
    rep = TL.build_tiles(tmp_path / "l.tif", tmp_path / "t.parquet", expected=4_000_000, far_off_frac=0.3)
    assert rep["far_off"] is True and "FAR OFF" in rep["message"] and "4,000,000" in rep["message"]
    assert TL.count_report(3_900_000, 4_000_000, 0.3)["far_off"] is False
    assert TL.count_report(5_500_000, 4_000_000, 0.3)["far_off"] is True
    assert TL.count_report(2_700_000, 4_000_000, 0.3)["far_off"] is True


def test_raster_without_land_frac_or_with_the_wrong_grid_is_refused(tmp_path):
    write_raster(tmp_path / "a.tif", np.ones((3, 3)), name="slope_med")
    with pytest.raises(ValueError, match="no land_frac band"):
        TL.build_tiles(tmp_path / "a.tif", tmp_path / "t.parquet")
    assert not (tmp_path / "t.parquet").exists() and not (tmp_path / "t.parquet.tmp").exists()
    with rasterio.open(tmp_path / "b.tif", "w", driver="GTiff", height=2, width=2, count=1, dtype="float32",
                       crs="EPSG:4326", transform=Affine(1, 0, 0, 0, -1, 0)) as ds:
        ds.write(np.ones((2, 2), "float32"), 1)
    with pytest.raises(ValueError, match="EPSG:6933"):
        TL.build_tiles(tmp_path / "b.tif", tmp_path / "t.parquet")


def test_overlapping_blocks_are_refused_adjacent_ones_merge(tmp_path):
    d = tmp_path / "blocks"
    d.mkdir()
    write_raster(d / "a.tif", np.ones((3, 3)), ix0=100, iy0=100)
    write_raster(d / "b.tif", np.ones((3, 3)), ix0=103, iy0=100)
    assert TL.build_tiles(d, tmp_path / "t.parquet")["n_land_tiles"] == 18
    write_raster(d / "c.tif", np.ones((3, 3)), ix0=102, iy0=101)
    with pytest.raises(ValueError, match="overlaps another raster block"):
        TL.build_tiles(d, tmp_path / "t2.parquet")


def test_failed_build_leaves_no_partial_file(tmp_path, land, monkeypatch):
    write_raster(tmp_path / "l.tif", land)
    TL.build_tiles(tmp_path / "l.tif", tmp_path / "t.parquet")
    before = (tmp_path / "t.parquet").read_bytes()
    monkeypatch.setattr(TL.Grid, "centre_lonlat", lambda self, ix, iy: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        TL.build_tiles(tmp_path / "l.tif", tmp_path / "t.parquet")
    assert (tmp_path / "t.parquet").read_bytes() == before
    assert sorted(p.name for p in tmp_path.glob("t.parquet*")) == ["t.parquet"]


def test_rerun_without_changes_is_skipped_and_a_change_reruns(tmp_path, land, caplog):
    write_raster(tmp_path / "l.tif", land)
    interim = tmp_path / "interim"
    with caplog.at_level(logging.INFO, logger="gsop.tiles"):
        a = TL.run_stage(tmp_path / "l.tif", interim, RUN)
        b = TL.run_stage(tmp_path / "l.tif", interim, RUN)
    assert a["skipped"] is False and b["skipped"] is True and b["n_land_tiles"] == a["n_land_tiles"]
    assert any("[skip] s1_tiles: up to date" in m for m in caplog.messages)
    assert TL.run_stage(tmp_path / "l.tif", interim, RUN, force=True)["skipped"] is False
    land[5, 5] = 0.0 if land[5, 5] else 1.0
    write_raster(tmp_path / "l.tif", land)
    assert TL.run_stage(tmp_path / "l.tif", interim, RUN)["skipped"] is False       # raster hash changed
    (interim / "tiles.parquet").unlink()
    assert TL.run_stage(tmp_path / "l.tif", interim, RUN)["skipped"] is False       # output missing
    run2 = dict(RUN, tiles=dict(RUN["tiles"], chunk_rows=7))
    assert TL.run_stage(tmp_path / "l.tif", interim, run2)["skipped"] is False      # setting changed
    assert StageStore(interim).read("s1_tiles")["outputs"] == ["tiles.parquet", "tiles_report.json"]
