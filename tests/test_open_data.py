import math

import numpy as np
import pytest
import rasterio
import yaml
from rasterio.transform import from_origin

from gsop.config import load_all
from gsop.earth import open_data as OD
from gsop.earth.local_loaders import build_earth_table
from gsop.grid import Grid

OP = load_all()["features"]["operator"]
M_PER_DEG = 111_320.0


def _geo_tif(path, lon0, lat1, lon1, lat0, cell_deg, fn, nodata=None):
    """Geographic (EPSG:4326) raster of fn(lon, lat) with cells of cell_deg."""
    w, h = int(round((lon1 - lon0) / cell_deg)), int(round((lat1 - lat0) / cell_deg))
    lon = lon0 + (np.arange(w) + 0.5) * cell_deg
    lat = lat1 - (np.arange(h) + 0.5) * cell_deg
    a = fn(lon[None, :], lat[:, None]).astype("float32")
    with rasterio.open(path, "w", driver="GTiff", height=h, width=w, count=1, dtype="float32", crs="EPSG:4326",
                       transform=from_origin(lon0, lat1, cell_deg, cell_deg), nodata=nodata) as ds:
        ds.write(a, 1)
    return path


def _ramp_ns(lon, lat):          # rises 0.1 m per m of true northing, so the true slope is atan(0.1) = 5.71 deg
    return 0.1 * (lat - 20.0) * M_PER_DEG + 0 * lon


def _ramp_ew(lat0):              # rises 0.1 m per m of true easting at latitude lat0
    return lambda lon, lat: 0.1 * (lon - 10.0) * M_PER_DEG * math.cos(math.radians(lat0)) + 0 * lat


def test_tile_window_and_global_extent():
    g = Grid()
    assert OD.tile_window(g, None) == (0, 0, g.ncols, g.nrows)
    ix0, iy0, ix1, iy1 = OD.tile_window(g, (10.0, 59.0, 12.0, 61.0))
    lon, lat = g.centre_lonlat(np.array([ix0, ix1 - 1]), np.array([iy0, iy1 - 1]))
    assert ix1 > ix0 and iy1 > iy0
    with pytest.raises(ValueError):
        OD.tile_window(g, (12.0, 59.0, 10.0, 61.0))


@pytest.mark.parametrize("lat_box, fn_name", [((19.0, 21.0), "ns"), ((59.0, 61.0), "ew60")])
def test_slope_matches_ground_truth_on_equal_area_grid(tmp_path, lat_box, fn_name):
    """The grid is cylindrical equal-area, so a projected 500 m cell is not 500 m on the ground away from 30 deg.
    A plane with a true slope of 5.71 deg must come out as 5.71 deg at 20 and 60 deg latitude, not a distorted value."""
    fn = _ramp_ns if fn_name == "ns" else _ramp_ew(60.0)
    dem = _geo_tif(tmp_path / "dem.tif", 10.0, lat_box[1], 12.0, lat_box[0], 0.004, fn)
    g = Grid()
    win = OD.tile_window(g, (10.2, lat_box[0] + 0.3, 11.8, lat_box[1] - 0.3))
    feats, left = OD.terrain_features(dem, win, g, OP, rows_per_chunk=7)
    assert set(feats) == {"slope_med", "slope_p90", "relief"}
    assert {"rough_a", "rough_b"} <= set(left)
    med = feats["slope_med"][np.isfinite(feats["slope_med"])]
    assert med.size > 20
    assert np.allclose(med, math.degrees(math.atan(0.1)), atol=0.25), (med.min(), med.max())
    assert np.nanmin(feats["relief"]) > 0


def test_uncorrected_slope_would_be_wrong_at_60_degrees():
    """Guards the correction itself: the same plane through the plain operator (no kx) is off by a lot at 60 deg."""
    from gsop import operators as O
    kx = math.cos(math.radians(60.0)) / math.cos(math.radians(30.0))
    # projected cell 500 m, east-west ground spacing 500 * kx; a true 0.1 gradient gives dz of 0.1 * 500 * kx per cell
    z = np.tile(np.arange(5) * 0.1 * 500.0 * kx, (5, 1))
    plain = O.slope_deg(z, 500.0)[2, 2]
    fixed = O.slope_deg(z, 500.0, np.full(5, kx))[2, 2]
    assert fixed == pytest.approx(math.degrees(math.atan(0.1)), abs=1e-6)
    assert abs(plain - fixed) > 2.0


def test_coarse_dem_leaves_terrain_out_and_says_why(tmp_path):
    """A ~1.8 km relief grid cannot give a 500 m slope: the columns are left out, never substituted."""
    dem = _geo_tif(tmp_path / "etopo_like.tif", 10.0, 21.0, 12.0, 19.0, 1.0 / 60.0, _ramp_ns)
    feats, left = OD.terrain_features(dem, OD.tile_window(Grid(), (10.2, 19.3, 11.8, 20.7)), Grid(), OP)
    assert feats == {}
    assert set(left) == set(OD.TERRAIN_COLUMNS)
    assert "coarser than the 500 m slope baseline" in left["slope_med"]


def test_build_rasters_feeds_the_local_loader(tmp_path):
    land = _geo_tif(tmp_path / "land.tif", 10.0, 21.0, 12.0, 19.0, 0.004, lambda lon, lat: 1.0 + 0 * lon + 0 * lat)
    tmean = _geo_tif(tmp_path / "t.tif", 10.0, 21.0, 12.0, 19.0, 0.05, lambda lon, lat: 300.0 + 0 * lon + 0 * lat)
    dem = _geo_tif(tmp_path / "dem.tif", 10.0, 21.0, 12.0, 19.0, 0.004, _ramp_ns)
    spec = {"dem": str(dem), "layers": {"land_frac": {"file": str(land)}, "t_mean": {"file": str(tmean)},
                                        "silica_index": {"file": None}, "ndvi_median": None}}
    rep = OD.build_rasters(spec, OP, tmp_path / "earth" / "e.tif", (10.2, 19.3, 11.8, 20.7))
    assert rep["bands"][0] == "land_frac" and {"slope_med", "slope_p90", "relief", "t_mean"} <= set(rep["bands"])
    assert "silica_index" in rep["left_out"] and "ndvi_median" in rep["left_out"] and "rough_a" in rep["left_out"]
    assert (tmp_path / "earth" / "open_data_report.json").exists()
    df = build_earth_table(tmp_path / "earth" / "e.tif", tmp_path / "out" / "earth.parquet")
    assert len(df) > 20 and "silica_index" not in df.columns and "rough_a" not in df.columns   # absent stays absent
    assert df["t_mean"].dropna().eq(300.0).all()


def test_land_frac_is_required_and_terrain_columns_cannot_be_layers(tmp_path):
    with pytest.raises(ValueError, match="land_frac"):
        OD.build_rasters({"layers": {}}, OP, tmp_path / "a.tif", (10.2, 19.3, 11.8, 20.7))
    with pytest.raises(ValueError, match="terrain column"):
        OD.build_rasters({"layers": {"slope_med": {"file": "x.tif"}}}, OP, tmp_path / "b.tif", (10.2, 19.3, 11.8, 20.7))


def test_config_template_has_no_invented_files():
    spec = yaml.safe_load(open("config/open_data.yaml", encoding="utf-8"))
    assert spec["dem"] is None and all(v["file"] is None for v in spec["layers"].values())
