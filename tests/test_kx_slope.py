"""kx slope correction (DECISIONS E12, E25) on a plane of known ground slope at several latitudes.

The plane is built on the EPSG:6933 grid: a projected cell of 500 m is 500 * kx ground metres east-west and 500 / kx
north-south, kx = cos(lat) / cos(30 deg). A plane with ground gradient (gx, gy) then has a projected step of
gx * 500 * kx per column and gy * 500 / kx per row. The corrected operators must return atan(hypot(gx, gy)).
"""

import math

import numpy as np
import pytest

from gsop import operators as O
from gsop.earth import gee_export as GE
from gsop.earth import gee_operators as GO

LATS = [0.0, 15.0, 30.0, 45.0, 60.0, 75.0]


def _plane(lat: float, gx: float, gy: float, n: int = 12, cell: float = 500.0) -> np.ndarray:
    k = math.cos(math.radians(lat)) / math.cos(math.radians(30.0))
    j, i = np.mgrid[0:n, 0:n]
    return gx * cell * k * i - gy * cell / k * j        # rows run north to south


@pytest.mark.parametrize("lat", LATS)
@pytest.mark.parametrize("gx,gy", [(0.1, 0.0), (0.0, 0.1), (0.06, 0.08)])
def test_corrected_slope_recovers_the_ground_slope(lat, gx, gy):
    z = _plane(lat, gx, gy)
    want = math.degrees(math.atan(math.hypot(gx, gy)))
    lat_rows = np.full(z.shape[0], lat)
    ee_mirror = GE.horn_slope_deg_np(z, 500.0, lat_rows)[1:-1, 1:-1]
    np.testing.assert_allclose(ee_mirror, want, rtol=1e-9)
    kx_rows = GE.ground_scale_kx(lat_rows)
    numpy_op = O.slope_deg(z, 500.0, kx_rows)
    np.testing.assert_allclose(numpy_op[np.isfinite(numpy_op)], want, rtol=1e-9)
    np.testing.assert_allclose(GO.horn_slope_mirror(z, 500.0, kx_rows)[1:-1, 1:-1], want, rtol=1e-9)


@pytest.mark.parametrize("lat", [0.0, 60.0, 75.0])
def test_uncorrected_slope_is_off_away_from_30_degrees(lat):
    z = _plane(lat, 0.1, 0.0)
    plain = GE.horn_slope_deg_np(z, 500.0)[1:-1, 1:-1]
    k = math.cos(math.radians(lat)) / math.cos(math.radians(30.0))
    assert plain.mean() == pytest.approx(math.degrees(math.atan(0.1 * k)), rel=1e-9)   # east-west read as gx * kx
    assert abs(plain.mean() - math.degrees(math.atan(0.1))) > 0.5


def test_kx_is_one_at_30_degrees_and_default_is_unchanged():
    assert GE.ground_scale_kx(30.0) == pytest.approx(1.0)
    z = _plane(30.0, 0.05, 0.02)
    np.testing.assert_allclose(GE.horn_slope_deg_np(z, 500.0), GE.horn_slope_deg_np(z, 500.0, np.full(12, 30.0)),
                               rtol=1e-12, equal_nan=True)
    # Moon and Mars call operators.slope_deg without kx: the square-cell result is unchanged
    np.testing.assert_allclose(O.slope_deg(z, 500.0), O.slope_deg(z, 500.0, np.ones(12)), rtol=1e-12, equal_nan=True)


def test_ee_expression_keeps_the_default_graph():
    import inspect
    src = inspect.getsource(GE.terrain_bands)
    assert "ground_scale: bool = False" in src and "horn_slope_deg(z500, ground_scale)" in src


def test_bias_table_in_spec():
    """The uncorrected readings quoted in SPEC section 3f (planes of 10 and 20 deg, east-west and north-south)."""
    want = {(0, 10): (11.51, 8.68), (20, 10): (10.83, 9.23), (30, 10): (10.0, 10.0), (40, 10): (8.87, 11.27),
            (50, 10): (7.46, 13.36), (60, 10): (5.81, 16.98), (0, 20): (22.80, 17.50), (60, 20): (11.87, 32.23)}
    for (lat, t), (ew, ns) in want.items():
        g = math.tan(math.radians(t))
        assert np.nanmean(GE.horn_slope_deg_np(_plane(lat, g, 0.0))) == pytest.approx(ew, abs=0.006)
        assert np.nanmean(GE.horn_slope_deg_np(_plane(lat, 0.0, g))) == pytest.approx(ns, abs=0.006)
