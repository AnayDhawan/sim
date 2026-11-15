"""Terrain-on-survivors plan generation (offline, no Earth Engine)."""

import numpy as np
import pytest

from gsop.earth import terrain_plan as TP
from gsop.grid import Grid


def _write_gate_tif(path, ix0, iy0, land, ndvi, wi, bc):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    g = Grid()
    h, w = ndvi.shape
    tf = from_origin(g.x0 + ix0 * g.cell_m, g.y_top - iy0 * g.cell_m, g.cell_m, g.cell_m)
    with rasterio.open(path, "w", driver="GTiff", height=h, width=w, count=4, dtype="float32", transform=tf,
                       nodata=float("nan")) as ds:
        for i, a in enumerate((land, wi, ndvi, bc), 1):
            ds.write(a.astype("float32"), i)


def test_survivor_cells_and_plan_from_tifs(tmp_path):
    ones, zeros = np.ones((20, 20)), np.zeros((20, 20))
    # box A passes everywhere (Atacama-like), box B fails everywhere (Lonar-like: cropland, ndvi 0.4)
    _write_gate_tif(tmp_path / "a.tif", 1787, 1699, ones, zeros + 0.075, zeros, zeros)
    _write_gate_tif(tmp_path / "b.tif", 4114, 797, ones, zeros + 0.4, zeros, zeros + 1.0)
    cells = TP.survivor_cells(tmp_path)
    assert len(cells) == 400
    assert cells[:, 0].min() == 1787 and cells[:, 1].min() == 1699
    plan = TP.plan_regions(cells)
    assert plan["regions"] == [[1787, 1699, 20, 20]]
    assert plan["stats"]["waste_factor"] == 1.0 and plan["stats"]["all_survivors_covered"]


def test_no_survivors(tmp_path):
    zeros = np.zeros((20, 20))
    _write_gate_tif(tmp_path / "b.tif", 4114, 797, zeros + 1, zeros + 0.4, zeros, zeros + 1.0)
    plan = TP.plan_regions(TP.survivor_cells(tmp_path))
    assert plan["regions"] == [] and plan["stats"]["survivors"] == 0


def test_merge_limits_regions_and_covers_everything():
    rng = np.random.default_rng(0)
    centres = rng.integers(0, 5000, size=(400, 2))
    cells = np.unique(np.concatenate([c + rng.integers(0, 25, size=(60, 2)) for c in centres]), axis=0)
    plan = TP.plan_regions(cells, max_regions=150)
    assert 0 < plan["stats"]["regions"] <= 150
    assert plan["stats"]["all_survivors_covered"]


def test_merge_prefers_small_regions_when_possible():
    rng = np.random.default_rng(1)
    centres = rng.integers(0, 300, size=(40, 2))
    cells = np.unique(np.concatenate([c + rng.integers(0, 12, size=(30, 2)) for c in centres]), axis=0)
    plan = TP.plan_regions(cells, max_regions=150)
    assert plan["stats"]["all_survivors_covered"]
    assert all(max(w, h) <= TP.MAX_SIDE for _, _, w, h in plan["regions"])
