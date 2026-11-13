"""C01: the equal-area grid is exact and reversible."""

import numpy as np
import pytest
from pyproj import Geod

from gsop import grid as GR

G = GR.Grid()


def test_round_trip_of_10000_random_points():
    rng = np.random.default_rng(0)
    lon, lat = rng.uniform(-179.99, 179.99, 10_000), rng.uniform(-89.9, 89.9, 10_000)
    ix, iy = G.cell_of_lonlat(lon, lat)
    tid = G.tile_id(ix, iy)
    ix2, iy2 = G.split_id(tid)
    assert (ix2 == ix).all() and (iy2 == iy).all()
    clon, clat = G.centre_of_tile(tid)
    # the centre of the cell a point falls in is within half a diagonal of the point (about 4.3 km; more near the
    # poles where an equal-area cell is stretched in longitude), and maps back to the same tile
    assert (G.tile_of_lonlat(clon, clat) == tid).all()
    d = GR.haversine_km(lat, lon, clat, GR.wrap_lon(clon))
    near_equator = np.abs(lat) < 60
    assert d[near_equator].max() < 6.0


def test_tile_ids_are_unique_and_int64():
    ix, iy = np.meshgrid(np.arange(0, G.ncols, 97), np.arange(0, G.nrows, 31))
    tid = G.tile_id(ix, iy)
    assert tid.dtype == np.int64 and np.unique(tid).size == tid.size
    assert tid.max() < G.ncols * G.nrows < 2**31


def test_all_cells_have_the_same_area():
    ix = np.array([0, 100, 2000, 5788])
    iy = np.array([0, 700, 1200, 2446])
    areas = [G.polygon(G.tile_id(a, b)).area for a, b in zip(ix, iy)]
    assert np.allclose(areas, 6000.0 ** 2, rtol=1e-12)
    # and on the sphere: ellipsoidal area of two cells at very different latitudes agrees within the projection's
    # own accuracy (EPSG:6933 is an authalic-sphere equal-area projection; the WGS84 ellipsoid differs by < 0.5%)
    from pyproj import Transformer
    from shapely.ops import transform
    tr = Transformer.from_crs(G.crs, "EPSG:4326", always_xy=True)
    geod = Geod(ellps="WGS84")
    equal = []
    for a, b in ((100, 1200), (100, 400), (3000, 200)):
        poly = transform(tr.transform, G.polygon(G.tile_id(a, b)))
        equal.append(abs(geod.geometry_area_perimeter(poly)[0]))
    assert max(equal) / min(equal) - 1 < 0.01
    assert np.mean(equal) == pytest.approx(36e6, rel=0.01)


def test_last_column_and_row_are_partial_slivers_inside_the_domain():
    last_col, last_row = G.tile_id(G.ncols - 1, 10), G.tile_id(10, G.nrows - 1)
    assert 0 < G.polygon(last_col).area < 6000.0 ** 2 and 0 < G.polygon(last_row).area < 6000.0 ** 2
    clon, clat = G.centre_of_tile(np.array([last_col, last_row]))
    assert np.isfinite(clon).all() and np.isfinite(clat).all()
    assert clon[0] > 179.9 and clat[1] < -88.5          # an equal-area strip at the pole spans a wide latitude band


def test_poles_and_antimeridian_are_handled():
    lon = np.array([-180.0, 180.0, 0.0, 0.0, 179.999, -179.999])
    lat = np.array([0.0, 0.0, 90.0, -90.0, 89.99, -89.99])
    ix, iy = G.cell_of_lonlat(lon, lat)
    assert ((ix >= 0) & (ix < G.ncols)).all() and ((iy >= 0) & (iy < G.nrows)).all()
    assert ix[0] == 0 and ix[1] == G.ncols - 1          # the two ends of the antimeridian
    assert iy[2] == 0 and iy[3] == G.nrows - 1          # north and south poles
    tid = G.tile_id(ix, iy)
    clon, clat = G.centre_of_tile(tid)
    assert np.isfinite(clon).all() and np.isfinite(clat).all()
    assert clat[2] > 88 and clat[3] < -88


def test_haversine_matches_known_distances_within_0_1_percent():
    quarter = np.pi / 2 * 6371.0088                      # pole to equator on the mean-radius sphere
    assert GR.haversine_km(90, 0, 0, 0) == pytest.approx(quarter, rel=1e-3)
    assert GR.haversine_km(0, 0, 0, 180) == pytest.approx(2 * quarter, rel=1e-3)
    assert GR.haversine_km(48.8566, 2.3522, 51.5074, -0.1278) == pytest.approx(343.5, rel=1e-3)   # Paris-London
    d = GR.haversine_km(np.array([0.0, 10.0]), np.array([0.0, 20.0]), np.array([0.0, 10.0]), np.array([1.0, 20.0]))
    assert d[1] == 0 and d[0] == pytest.approx(111.195, rel=1e-3)         # vectorised, zero distance is zero


def test_describe_documents_origin_extent_and_count():
    d = G.describe()
    assert d["ncols"] == 5790 and d["nrows"] == 2448 and d["n_cells"] == 5790 * 2448
    assert d["cell_m"] == 6000.0 and d["crs"] == "EPSG:6933"
    assert d["x0"] == -GR.X_MAX and d["y_top"] == GR.Y_MAX
    assert "tile_id" in d and "origin" in d


def test_polygon_contains_its_centre():
    tid = G.tile_of_lonlat(77.5031, 18.4386)
    clon, clat = G.centre_of_tile(tid)
    from pyproj import Transformer
    from shapely.geometry import Point
    x, y = Transformer.from_crs("EPSG:4326", G.crs, always_xy=True).transform(clon, clat)
    assert G.polygon(tid).contains(Point(x, y))
