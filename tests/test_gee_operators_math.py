"""Offline checks of the maths that the Earth Engine operator relies on (the Earth Engine calls themselves need a login
and are checked by `gsop check-operators`)."""
import numpy as np
import pytest

from gsop import operators as O
from gsop.earth import gee_operators as G


def test_horn_kernels_reproduce_the_numpy_slope_with_ground_scale():
    rng = np.random.default_rng(1)
    z = rng.normal(0, 30, (40, 50)).cumsum(0).cumsum(1) * 0.05
    kx = G.kx_from_lat(np.linspace(65.0, 62.0, 40))
    a = O.slope_deg(z, 500.0, kx)
    b = G.horn_slope_mirror(z, 500.0, kx)
    assert np.allclose(a, b, equal_nan=True, atol=1e-9)
    assert np.isfinite(a[1:-1, 1:-1]).all()


def test_horn_kernels_without_scale_equal_plain_operator():
    z = np.random.default_rng(2).random((20, 20)) * 100
    assert np.allclose(O.slope_deg(z, 500.0), G.horn_slope_mirror(z, 500.0, np.ones(20)), equal_nan=True)


@pytest.mark.parametrize("k", [4, 8, 40])
def test_plane_rms_from_moments_equals_operator(k):
    z = np.random.default_rng(3).normal(0, 5, (k * 6, k * 7)) + np.add.outer(np.arange(k * 6), np.arange(k * 7)) * 0.3
    assert np.allclose(O.plane_rms(z, k), G.plane_rms_from_moments(z, k), atol=1e-8)


def test_a_pure_plane_has_zero_roughness():
    y, x = np.mgrid[0:16, 0:16]
    assert np.allclose(G.plane_rms_from_moments(2.0 * x + 3.0 * y + 7.0, 4), 0.0, atol=1e-6)


def test_tile_transform_is_tile_aligned():
    from gsop.grid import Grid
    g = Grid()
    tf = G.tile_transform(g, 100, 50, 25.0)
    assert tf[2] == g.x0 + 100 * 6000 and tf[5] == g.y_top - 50 * 6000
    assert (tf[2] - g.x0) % 25.0 == 0
