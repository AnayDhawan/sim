import numpy as np
import pytest

from gsop import grid as GR
from gsop import operators as O


def test_slope_of_a_plane():
    y, x = np.mgrid[0:40, 0:40]
    dem = np.tan(np.radians(10)) * 100.0 * x                              # 10 deg slope, 100 m cells
    s = O.slope_deg(dem, 100.0)
    assert np.nanmedian(s) == pytest.approx(10.0, abs=1e-6)
    assert np.isnan(s[0, 0])


def test_plane_rms_removes_plane_and_sees_noise():
    k = 10
    y, x = np.mgrid[0:50, 0:50].astype(float)
    plane = 3.0 * x + 2.0 * y
    assert np.nanmax(O.plane_rms(plane, k)) == pytest.approx(0.0, abs=1e-9)
    rng = np.random.default_rng(0)
    noisy = plane + rng.normal(0, 2.0, plane.shape)
    assert np.nanmedian(O.plane_rms(noisy, k)) == pytest.approx(2.0, rel=0.25)


def test_tile_features_flat_and_ramp():
    n = 260                                        # 240 cells = 12 km of tiles (2 x 2) plus a 500 m margin each side
    dem = np.tile(np.arange(n) * 5.0, (n, 1))      # 5 m rise per 50 m cell, slope 0.1
    f = O.tile_features(dem, 50.0, tile_m=6000, slope_baseline_m=500, rough_baselines_m=(150.0, 1000.0),
                        margin_m=500.0)
    assert f["slope_med"].shape == (2, 2)
    assert np.nanmedian(f["slope_med"]) == pytest.approx(np.degrees(np.arctan(0.1)), abs=1e-6)
    assert np.nanmax(f["rough_a"]) < 1e-9
    assert np.nanmin(f["relief"]) > 0


def test_baseline_must_divide_cell():
    with pytest.raises(ValueError):
        O.tile_features(np.zeros((120, 120)), 70.0)


def test_window_profile_returns_median_and_spread():
    rng = np.random.default_rng(0)
    n = int((15000 + 1000) / 50)
    dem = rng.normal(0, 3, (n + 20, n + 20))
    p = O.window_profile(dem, 50.0, rough_baselines_m=(150.0, 1000.0))
    assert set(p) == {"slope_med", "slope_p90", "relief", "rough_a", "rough_b"}
    assert all(np.isfinite(v[0]) and v[2] > 0 for v in p.values())


def test_grid_dimensions_and_roundtrip():
    g = GR.Grid()
    assert g.ncols == 5790 and g.nrows == 2448
    lon, lat = 77.5, 18.4
    ix, iy = g.cell_of_lonlat(lon, lat)
    clon, clat = g.centre_lonlat(ix, iy)
    assert abs(clon - lon) < 0.1 and abs(clat - lat) < 0.1
    assert tuple(int(v) for v in g.split_id(g.tile_id(ix, iy))) == (int(ix), int(iy))


def test_haversine_known_distance():
    assert GR.haversine_km(0, 0, 0, 1) == pytest.approx(111.195, abs=0.05)
    assert GR.wrap_lon(222.84) == pytest.approx(-137.16)
