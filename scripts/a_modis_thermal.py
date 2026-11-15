"""ROLE A: Earth thermal features (th_mean_K, th_max_K, th_dn_K, th_valid_frac) on the v1 6 km EPSG:6933 grid.

Design is fixed in runs/v2/PREREG_A.md. Product MODIS/061/MOD11A2, 2019 to 2023, QC bits 0-1 == 0 for day and night.
Blocks are fetched with ee.data.computePixels (NPY) and cached under data/interim/a_thermal/blocks.
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import ee
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "gsop-earthengine"
X0, Y_TOP, CELL, NCOLS, NROWS = -17367530.445161372, 7342230.136498678, 6000.0, 5790, 2448
YEARS = list(range(2019, 2024))
BANDS = ["th_mean_K", "th_max_K", "th_dn_K", "th_valid_mean", "th_valid_max", "th_valid_dn"]
CACHE = ROOT / "data" / "interim" / "a_thermal" / "blocks"


def _wkt():
    from pyproj import CRS
    return CRS.from_epsg(6933).to_wkt(version="WKT1_GDAL")


def init():
    ee.Initialize(project=PROJECT)


def pixel_image():
    """Per 1 km pixel: th_mean_K, th_max_K, th_dn_K masked by the PREREG validity counts."""
    col = ee.ImageCollection("MODIS/061/MOD11A2").filterDate("2019-01-01", "2024-01-01")
    proj = col.first().select("LST_Day_1km").projection()
    keep = ["system:time_start"]

    def prep(im):
        day = im.select("LST_Day_1km").multiply(0.02).updateMask(im.select("QC_Day").bitwiseAnd(3).eq(0)).rename("day")
        night = im.select("LST_Night_1km").multiply(0.02).updateMask(im.select("QC_Night").bitwiseAnd(3).eq(0)).rename("night")
        return day.addBands(night).copyProperties(im, keep)

    c = col.map(prep)
    months = []   # (year, month_index, day_m, night_m)
    for y in YEARS:
        for m in range(1, 13):
            sub = c.filter(ee.Filter.calendarRange(y, y, "year")).filter(ee.Filter.calendarRange(m, m, "month"))
            months.append((y, sub.select("day").mean().rename("d"), sub.select("night").mean().rename("n")))
    mean_dn = [d.add(n).divide(2).rename("v") for _, d, n in months]
    diff = [d.subtract(n).rename("v") for _, d, n in months]
    mean_c = ee.ImageCollection.fromImages(mean_dn)
    diff_c = ee.ImageCollection.fromImages(diff)
    th_mean = mean_c.mean().updateMask(mean_c.count().gte(36)).rename("th_mean_K")
    th_dn = diff_c.mean().updateMask(diff_c.count().gte(36)).rename("th_dn_K")
    yearly = []
    for y in YEARS:
        ds = ee.ImageCollection.fromImages([d for yy, d, _ in months if yy == y])
        yearly.append(ds.max().updateMask(ds.count().gte(9)).rename("m"))
    yc = ee.ImageCollection.fromImages(yearly)
    th_max = yc.mean().updateMask(yc.count().gte(3)).rename("th_max_K")
    out = th_mean.addBands(th_max).addBands(th_dn).setDefaultProjection(proj)
    return out, proj


def fetch_block(window, retries=3):
    """window = (ix0, iy0, w, h) in tiles. Returns float32 array (6, h, w) with NaN where invalid. Raises after retries."""
    ix0, iy0, w, h = window
    last = None
    for attempt in range(retries):
        try:
            arr = _fetch(window)
            return arr
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + 3 * attempt)
    raise RuntimeError(f"block {window} failed after {retries} tries: {type(last).__name__}: {str(last)[:300]}")


_IMG = None


def _images():
    global _IMG
    if _IMG is None:
        masked, proj = pixel_image()
        valid = masked.mask().rename(["th_valid_mean", "th_valid_max", "th_valid_dn"]).setDefaultProjection(proj)
        mean = ee.Reducer.mean()
        feats = masked.reduceResolution(mean, False, 1 << 16)
        val = valid.reduceResolution(mean, False, 1 << 16)
        _IMG = feats.addBands(val).toFloat()
    return _IMG


def _fetch(window):
    ix0, iy0, w, h = window
    img = _images()
    req = {
        "expression": img,
        "fileFormat": "NPY",
        "bandIds": ["th_mean_K", "th_max_K", "th_dn_K", "th_valid_mean", "th_valid_max", "th_valid_dn"],
        "grid": {
            "dimensions": {"width": w, "height": h},
            "affineTransform": {"scaleX": CELL, "shearX": 0, "translateX": X0 + ix0 * CELL,
                                "shearY": 0, "scaleY": -CELL, "translateY": Y_TOP - iy0 * CELL},
            "crsWkt": _wkt(),
        },
    }
    raw = ee.data.computePixels(req)
    a = np.load(io.BytesIO(raw), allow_pickle=False)
    out = np.stack([a[n].astype(np.float32) for n in a.dtype.names])
    return out


if __name__ == "__main__":
    init()
    t0 = time.time()
    # smoke block around Rub' al Khali (21N, 51E): v1 grid cell
    from pyproj import Transformer
    x, y = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True).transform(51.0, 21.0)
    ix, iy = int((x - X0) // CELL), int((Y_TOP - y) // CELL)
    win = (ix - 10, iy - 10, 20, 20)
    a = fetch_block(win)
    print(win, a.shape, time.time() - t0)
    for i, n in enumerate(BANDS):
        print(n, np.nanmin(a[i]), np.nanmedian(a[i]), np.nanmax(a[i]), int(np.isnan(a[i]).sum()))
