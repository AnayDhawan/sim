import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine

from gsop.earth.local_loaders import build_earth_table
from gsop.grid import Grid


def _write(path, bands, x_left, y_top, crs="EPSG:6933", cell=6000.0):
    h, w = next(iter(bands.values())).shape
    with rasterio.open(path, "w", driver="GTiff", height=h, width=w, count=len(bands), dtype="float32", crs=crs,
                       transform=Affine(cell, 0, x_left, 0, -cell, y_top)) as ds:
        for i, (name, a) in enumerate(bands.items(), 1):
            ds.write(a.astype("float32"), i)
            ds.set_band_description(i, name)


def test_regional_raster_gets_global_tile_ids(tmp_path):
    g = Grid()
    ix0, iy0 = 3000, 1000
    x_left, y_top = g.x0 + ix0 * g.cell_m, g.y_top - iy0 * g.cell_m
    land = np.ones((4, 5))
    land[0, 0] = 0.1                                           # one sea cell
    bands = {"land_frac": land, "slope_med": np.arange(20.0).reshape(4, 5), "ndvi_median": np.zeros((4, 5))}
    _write(tmp_path / "e.tif", bands, x_left, y_top)
    df = build_earth_table(tmp_path / "e.tif", tmp_path / "out" / "earth.parquet")
    assert len(df) == 19 and (tmp_path / "out" / "grid.json").exists()
    assert "land_frac" not in df.columns and "water_ice_frac" not in df.columns   # absent stays absent
    row = df[(df.ix == ix0 + 1) & (df.iy == iy0)].iloc[0]
    assert row.tile_id == g.tile_id(ix0 + 1, iy0) and row.slope_med == 1.0
    lon, lat = g.centre_lonlat(ix0, iy0)
    assert abs(df.iloc[0].lat - float(lat)) < 1e-6 or len(df) == 19


def test_wrong_cell_size_or_crs_is_rejected(tmp_path):
    bands = {"land_frac": np.ones((3, 3))}
    _write(tmp_path / "a.tif", bands, 0.0, 0.0, cell=1000.0)
    with pytest.raises(ValueError, match="6000 m"):
        build_earth_table(tmp_path / "a.tif", tmp_path / "o.parquet")
    _write(tmp_path / "b.tif", bands, 0.0, 0.0, crs="EPSG:4326")
    with pytest.raises(ValueError, match="EPSG:6933"):
        build_earth_table(tmp_path / "b.tif", tmp_path / "o.parquet")


def test_missing_land_frac_is_an_error(tmp_path):
    _write(tmp_path / "c.tif", {"slope_med": np.ones((3, 3))}, 0.0, 0.0)
    with pytest.raises(ValueError, match="land_frac"):
        build_earth_table(tmp_path / "c.tif", tmp_path / "o.parquet")
