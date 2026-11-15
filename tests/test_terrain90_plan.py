"""Global 90 m terrain export: offline plan generation and the stats script (no Earth Engine)."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from gsop.earth import gee_export as GE
from gsop.grid import Grid

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_row_range_matches_srtm_latitudes():
    g = Grid()
    r0, r1 = GE.terrain90_row_range()
    lat_top = float(g.centre_lonlat(0, r0)[1])
    lat_bot = float(g.centre_lonlat(0, r1 - 1)[1])
    assert 60.0 <= lat_top < 62.0          # one margin row beyond 60N
    assert -58.0 < lat_bot <= -56.0
    assert float(g.centre_lonlat(0, r0 + 1)[1]) < 60.5   # not more than the margin


def _px(c):
    import math
    g = Grid()
    x0, y0, w, h = c["cells"]
    lat = max(abs(float(g.centre_lonlat(0, y0)[1])), abs(float(g.centre_lonlat(0, y0 + h)[1])))
    return w * h * GE.TILE_PX / math.cos(math.radians(lat))


def test_chunks_cover_band_without_overlap_and_stay_under_the_footprint_limit():
    g = Grid()
    ch = GE.terrain90_chunks()
    assert 0 < len(ch) < 1700
    assert all(_px(c) < 0.8 * GE.FOOTPRINT_PX_LIMIT for c in ch)
    r0, r1 = GE.terrain90_row_range()
    cover = np.zeros((r1 - r0, g.ncols), np.uint8)
    for c in ch:
        x0, y0, w, h = c["cells"]
        assert r0 <= y0 and y0 + h <= r1 and x0 + w <= g.ncols
        cover[y0 - r0:y0 + h - r0, x0:x0 + w] += 1
    assert (cover == 1).all()
    assert len({c["name"] for c in ch}) == len(ch)
    # tiles per chunk shrink toward high latitude
    sizes = {round(abs(float(g.centre_lonlat(0, c["cells"][1])[1])) // 20): c["cells"][2] * c["cells"][3] for c in ch}
    assert sizes[0] > sizes[2]


def test_split_halves_the_longer_side():
    mod = _load("ee_terrain90_export")
    a, b = mod.split([10, 20, 200, 100])
    assert a == [10, 20, 100, 100] and b == [110, 20, 100, 100]
    a, b = mod.split([10, 20, 100, 200])
    assert a == [10, 20, 100, 100] and b == [10, 120, 100, 100]


def test_stats_nan_share_and_ref_compare(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    g = Grid()
    mod = _load("ee_terrain90_stats")

    def write(path, ix0, iy0, arr):
        tf = from_origin(g.x0 + ix0 * g.cell_m, g.y_top - iy0 * g.cell_m, g.cell_m, g.cell_m)
        with rasterio.open(path, "w", driver="GTiff", height=arr.shape[1], width=arr.shape[2], count=6,
                           dtype="float32", transform=tf) as ds:
            ds.write(arr.astype("float32"))

    arr = np.full((6, 4, 5), 3.0)
    arr[:, 0, :] = -9999.0                    # one masked row (20 percent)
    write(tmp_path / "e.tif", 100, 200, arr)
    ref = np.full((6, 2, 2), 2.0)
    write(tmp_path / "ref.tif", 101, 201, ref)
    s = mod.file_stats(tmp_path / "e.tif")
    assert s["cells"] == 20 and abs(s["nan_share"]["slope_med"] - 0.25) < 1e-9
    cmp = mod.compare_ref([tmp_path / "e.tif"], [tmp_path / "ref.tif"])
    assert cmp["compared"] == 4 and cmp["median_abs_diff_slope_med_deg"] == 1.0


def test_stage1_boxes_inside_grid_and_contain_sites():
    g = Grid()
    boxes = GE.stage1_boxes()
    assert {b["site"] for b in boxes} == {"haughton", "samoylov", "mcmurdo_dry_valleys", "askja"}
    assert all(_px(b) < 0.8 * GE.FOOTPRINT_PX_LIMIT for b in boxes)
    for site, (lat, lon) in GE.STAGE1_SITES.items():
        mine = [b["cells"] for b in boxes if b["site"] == site]
        assert sum(w * h for _, _, w, h in mine) == 10_000
        for x0, y0, w, h in mine:
            assert 0 <= x0 and x0 + w <= g.ncols and GE.POLE_TRIM_ROWS <= y0 and y0 + h <= g.nrows - GE.POLE_TRIM_ROWS
        ix, iy = (int(v) for v in g.cell_of_lonlat(lon, lat))
        assert any(x0 <= ix < x0 + w and y0 <= iy < y0 + h for x0, y0, w, h in mine)


def test_stage2_chunks_cover_60_to_83_north_without_overlap():
    g = Grid()
    ch = GE.stage2_chunks()
    assert 0 < len(ch) < 700 and all(_px(c) < 0.8 * GE.FOOTPRINT_PX_LIMIT for c in ch)
    r0 = min(c["cells"][1] for c in ch)
    r1 = max(c["cells"][1] + c["cells"][3] for c in ch)
    assert r1 == GE.terrain90_row_range()[0]                  # abuts the SRTM90 band
    assert 75 < float(g.centre_lonlat(0, r0)[1]) < 84         # starts near 83N
    cover = np.zeros((r1 - r0, g.ncols), np.uint8)
    for c in ch:
        x0, y0, w, h = c["cells"]
        cover[y0 - r0:y0 + h - r0, x0:x0 + w] += 1
    assert (cover == 1).all()
