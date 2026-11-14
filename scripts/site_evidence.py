#!/usr/bin/env python
"""Role C: site-level open-data evidence from Earth Engine.

Implements runs/v2/PREREG_C.md. Definitions live there; this file only executes them.
Run in the background:  nohup python scripts/site_evidence.py > runs/v2/logs/run.out 2>&1 &
Smoke test:             python scripts/site_evidence.py --smoke
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import logging
import math
import re
import sys
import threading
import time
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import ee
import pandas as pd
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CSV_IN = ROOT / "data" / "raw" / "GSOP_analog_sites_moon_mars.csv"
OUT_CSV = ROOT / "data" / "evidence" / "site_measurements.csv"
CACHE = ROOT / "runs" / "v2" / "cache"
LOGS = ROOT / "runs" / "v2" / "logs"
STATUS = ROOT / "runs" / "v2" / "STATUS_C.md"
CHIP_DIR = ROOT / "public" / "img" / "sites"

PROJECT = "gsop-earthengine"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
STOP_IST = dt.datetime(2026, 11, 15, 17, 0, tzinfo=IST)
RADII_M = (2000, 10000)
USE_COLS = ["Body", "Category", "Site_name", "Latitude", "Longitude", "Coordinate_note"]
SMOKE_SITES = [
    "McMurdo Dry Valleys (Taylor/Wright valleys)",
    "Atacama Desert - Yungay core",
    "Haughton crater (Devon Island)",
]
CREDIT = "Contains modified Copernicus Sentinel data (2024-2025)"
WC_CLASSES = [10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100]
CHIP_MAX_BYTES = 300 * 1024
JPEG_LADDER = [85, 75, 65, 55, 45, 35]

CAT = "https://developers.google.com/earth-engine/datasets/catalog/"
META = {
    "cop_dem": dict(product="COPERNICUS/DEM/GLO30_2024_1", version="2024_1",
                    doi=CAT + "COPERNICUS_DEM_GLO30_2024_1", dates="catalog extent 2010-12-01 to 2020-11-13"),
    "alos_dem": dict(product="JAXA/ALOS/AW3D30/V4_1", version="4.1",
                     doi=CAT + "JAXA_ALOS_AW3D30_V4_1", dates="catalog extent 2006-01-24 to 2011-05-12"),
    "dem_crosscheck": dict(product="JAXA/ALOS/AW3D30/V4_1 minus COPERNICUS/DEM/GLO30_2024_1", version="4.1 / 2024_1",
                           doi=CAT + "JAXA_ALOS_AW3D30_V4_1 ; " + CAT + "COPERNICUS_DEM_GLO30_2024_1",
                           dates="catalog extents 2006-2011 (ALOS), 2010-2020 (COP)"),
    "mod11a2": dict(product="MODIS/061/MOD11A2", version="6.1",
                    doi="https://doi.org/10.5067/MODIS/MOD11A2.061", dates="2015-01-01 to 2024-12-31"),
    "aster_ged": dict(product="NASA/ASTER_GED/AG100_003", version="V003",
                      doi="https://doi.org/10.5067/COMMUNITY/ASTER_GED/AG100.003", dates="2000-01-01 to 2008-12-31"),
    "s2": dict(product="COPERNICUS/S2_SR_HARMONIZED", version="harmonized",
               doi=CAT + "COPERNICUS_S2_SR_HARMONIZED", dates="2024-01-01 to 2025-12-31"),
    "worldcover": dict(product="ESA/WorldCover/v200", version="v200",
                       doi=CAT + "ESA_WorldCover_v200", dates="2021-01-01 to 2021-12-31"),
    "s1": dict(product="COPERNICUS/S1_GRD", version="not stated in catalog",
               doi=CAT + "COPERNICUS_S1_GRD", dates="2024-01-01 to 2025-12-31"),
    "s2_chip": dict(product="COPERNICUS/S2_SR_HARMONIZED", version="harmonized",
                    doi=CAT + "COPERNICUS_S2_SR_HARMONIZED", dates="2024-01-01 to 2025-12-31"),
}
COLUMNS = ["site_name", "body", "list", "radius_km", "coord_flag", "dataset", "variable", "stat", "value",
           "units", "n_pixels", "product_id", "version", "doi_or_url", "date_range",
           "lat", "lon", "scale_m", "page_ok", "note", "pulled_utc"]

log = logging.getLogger("site_evidence")


class StopRun(Exception):
    pass


# ---------------------------------------------------------------- helpers
def now_ist() -> dt.datetime:
    return dt.datetime.now(IST)


def utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def laea(lat: float, lon: float) -> str:
    return (
        'PROJCS["site_laea",GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
        'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],PROJECTION["Lambert_Azimuthal_Equal_Area"],'
        f'PARAMETER["latitude_of_center",{lat}],PARAMETER["longitude_of_center",{lon}],'
        'PARAMETER["false_easting",0],PARAMETER["false_northing",0],UNIT["metre",1]]'
    )


def g(d: dict | None, key: str):
    if not d:
        return None
    v = d.get(key)
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


def rec(dataset, variable, stat, value, units, n=None, scale=None, note=""):
    if value is None and not note:
        note = "no_valid_pixels"
    return dict(dataset=dataset, variable=variable, stat=stat, value=value, units=units,
                n_pixels=None if n is None else round(float(n), 1), scale_m=scale, note=note)


def run_task(label: str, fn, ladder=(None, None, None, None, None), deadline_s=1800):
    """Run fn(scale) with retries and backoff. Returns (result, scale_used). Raises on final failure."""
    t0 = time.time()
    last = None
    for attempt, scale in enumerate(ladder):
        if now_ist() >= STOP_IST:
            raise StopRun("past 17:00 IST hard stop")
        try:
            return fn(scale), scale
        except StopRun:
            raise
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {str(e)[:240]}"
            log.warning("%s attempt %d (scale=%s) failed: %s", label, attempt + 1, scale, last)
            if time.time() - t0 > deadline_s:
                break
            time.sleep(20 * 2 ** attempt)
    raise RuntimeError(f"{label} failed after retries: {last}")


# ---------------------------------------------------------------- measurements
def red_terrain():
    return (ee.Reducer.mean().combine(ee.Reducer.minMax(), sharedInputs=True)
            .combine(ee.Reducer.percentile([5, 90, 95]), sharedInputs=True)
            .combine(ee.Reducer.stdDev(), sharedInputs=True)
            .combine(ee.Reducer.count(), sharedInputs=True))


def mean_count():
    return ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True)


def terrain(lat, lon, r_m, _scale):
    P = laea(lat, lon)
    geom = ee.Geometry.Point([lon, lat]).buffer(r_m)
    tiles = geom.buffer(200)

    def prep(cid, band):
        col = ee.ImageCollection(cid).select(band)
        proj = col.first().projection()
        return (col.filterBounds(tiles).mosaic().setDefaultProjection(proj)
                .resample("bilinear").reproject(crs=P, scale=30))

    cop = prep("COPERNICUS/DEM/GLO30_2024_1", "DEM")
    alos = prep("JAXA/ALOS/AW3D30/V4_1", "DSM")
    img_c = cop.rename("e").addBands(ee.Terrain.slope(cop).rename("s"))
    img_a = alos.rename("e").addBands(ee.Terrain.slope(alos).rename("s"))
    d = alos.subtract(cop)
    img_d = d.rename("d").addBands(d.abs().rename("a")).addBands(d.pow(2).rename("q"))
    kw = dict(geometry=geom, scale=30, crs=P, maxPixels=1e9, tileScale=4)
    out = ee.Dictionary({
        "cop": img_c.reduceRegion(reducer=red_terrain(), **kw),
        "alos": img_a.reduceRegion(reducer=red_terrain(), **kw),
        "diff": img_d.reduceRegion(reducer=mean_count(), **kw),
    }).getInfo()
    rows = []
    for ds, key in (("cop_dem", "cop"), ("alos_dem", "alos")):
        d_ = out[key]
        n = g(d_, "e_count")
        for stat in ("mean", "min", "max", "p5", "p95"):
            rows.append(rec(ds, "elevation", stat, g(d_, f"e_{stat}"), "m", n, 30))
        p5, p95 = g(d_, "e_p5"), g(d_, "e_p95")
        rows.append(rec(ds, "relief", "p95_minus_p5", None if p5 is None or p95 is None else p95 - p5, "m", n, 30,
                        "derived" if p5 is not None else ""))
        rows.append(rec(ds, "slope", "mean", g(d_, "s_mean"), "deg", g(d_, "s_count"), 30))
        rows.append(rec(ds, "slope", "p90", g(d_, "s_p90"), "deg", g(d_, "s_count"), 30))
        rows.append(rec(ds, "roughness", "std_of_slope", g(d_, "s_stdDev"), "deg", g(d_, "s_count"), 30))
    dd = out["diff"]
    n = g(dd, "d_count")
    q = g(dd, "q_mean")
    rows.append(rec("dem_crosscheck", "elevation_diff_alos_minus_cop", "mean", g(dd, "d_mean"), "m", n, 30))
    rows.append(rec("dem_crosscheck", "elevation_diff_alos_minus_cop", "mean_abs", g(dd, "a_mean"), "m", n, 30))
    rows.append(rec("dem_crosscheck", "elevation_diff_alos_minus_cop", "rms", None if q is None else math.sqrt(q), "m", n, 30,
                    "derived" if q is not None else ""))
    byk = {(x["dataset"], x["variable"], x["stat"]): x["value"] for x in rows}
    for var, stat, units in (("relief", "p95_minus_p5", "m"), ("slope", "mean", "deg")):
        a, c = byk.get(("alos_dem", var, stat)), byk.get(("cop_dem", var, stat))
        rows.append(rec("dem_crosscheck", f"{var}_{stat}_diff_alos_minus_cop", "difference",
                        None if a is None or c is None else a - c, units, n, 30,
                        "derived" if a is not None and c is not None else ""))
    return rows


def modis(lat, lon, r_m, _scale):
    geom = ee.Geometry.Point([lon, lat]).buffer(r_m)
    col = ee.ImageCollection("MODIS/061/MOD11A2").filterDate("2015-01-01", "2025-01-01")
    proj = col.first().select("LST_Day_1km").projection()

    def day(i):
        q = i.select("QC_Day").bitwiseAnd(3).eq(0)
        return i.select("LST_Day_1km").multiply(0.02).updateMask(q).rename("d")

    def night(i):
        q = i.select("QC_Night").bitwiseAnd(3).eq(0)
        return i.select("LST_Night_1km").multiply(0.02).updateMask(q).rename("n")

    dc, nc = col.map(day), col.map(night)
    im = (dc.mean().rename("lst_day_mean").addBands(nc.mean().rename("lst_night_mean"))
          .addBands(dc.max().rename("lst_day_max8d")).addBands(nc.min().rename("lst_night_min8d"))
          .addBands(dc.count().rename("valid_composites_day")).addBands(nc.count().rename("valid_composites_night")))
    d = im.reduceRegion(reducer=mean_count(), geometry=geom, crs=proj, scale=1000, maxPixels=1e9).getInfo()
    rows = []
    for v in ("lst_day_mean", "lst_night_mean", "lst_day_max8d", "lst_night_min8d"):
        rows.append(rec("mod11a2", v, "mean", g(d, f"{v}_mean"), "K", g(d, f"{v}_count"), 1000))
    for v in ("valid_composites_day", "valid_composites_night"):
        rows.append(rec("mod11a2", v, "mean", g(d, f"{v}_mean"), "count", g(d, f"{v}_count"), 1000))
    a, b = g(d, "lst_day_mean_mean"), g(d, "lst_night_mean_mean")
    rows.append(rec("mod11a2", "lst_day_night_diff", "mean_day_minus_mean_night",
                    None if a is None or b is None else a - b, "K", g(d, "lst_day_mean_count"), 1000,
                    "derived; proxy, not a true diurnal range" if a is not None and b is not None else ""))
    return rows


def aster(lat, lon, r_m, _scale):
    geom = ee.Geometry.Point([lon, lat]).buffer(r_m)
    im = ee.Image("NASA/ASTER_GED/AG100_003")
    proj = im.select("emissivity_band10").projection()
    bands = [f"emissivity_band{i}" for i in range(10, 15)]
    d = im.select(bands).multiply(0.001).reduceRegion(
        reducer=mean_count(), geometry=geom, crs=proj, scale=proj.nominalScale(), maxPixels=1e9).getInfo()
    rows, means = [], {}
    for b in bands:
        means[b] = g(d, f"{b}_mean")
        rows.append(rec("aster_ged", b, "mean", means[b], "unitless", g(d, f"{b}_count"), 100,
                        "" if means[b] is not None else "no_valid_pixels (product masked or no coverage at site)"))
    e = [means[f"emissivity_band{i}"] for i in (10, 11, 12)]
    qi = None if any(x is None for x in e) else (e[1] * e[1]) / (e[0] * e[2])
    rows.append(rec("aster_ged", "qi_silica_proxy", "ratio_eps11sq_over_eps10_eps12", qi, "unitless",
                    g(d, "emissivity_band11_count"), 100,
                    "derived; proxy only" if qi is not None else "no_valid_pixels (product masked or no coverage at site)"))
    return rows


def s2_masked(geom, bands):
    col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(geom)
           .filterDate("2024-01-01", "2026-01-01"))

    def m(i):
        scl = i.select("SCL")
        ok = scl.neq(0).And(scl.neq(1)).And(scl.neq(3)).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10))
        if bands == "ndvi":
            return i.normalizedDifference(["B8", "B4"]).rename("ndvi").updateMask(ok)
        return i.select(["B4", "B3", "B2"]).updateMask(ok)

    return col, col.map(m)


def s2_ndvi(lat, lon, r_m, scale):
    P = laea(lat, lon)
    geom = ee.Geometry.Point([lon, lat]).buffer(r_m)
    col, c = s2_masked(geom, "ndvi")
    n_img = col.size().getInfo()
    if n_img == 0:
        return [rec("s2", "ndvi", "mean", None, "unitless", None, scale, "no_images"),
                rec("s2", "ndvi", "std", None, "unitless", None, scale, "no_images"),
                rec("s2", "scene_count", "count", 0, "count", None, scale, "no_images")]
    red = ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True).combine(ee.Reducer.count(), sharedInputs=True)
    d = c.median().reduceRegion(reducer=red, geometry=geom, scale=scale, crs=P, maxPixels=1e10,
                                tileScale=16).getInfo()
    n = g(d, "ndvi_count")
    return [rec("s2", "ndvi", "mean", g(d, "ndvi_mean"), "unitless", n, scale),
            rec("s2", "ndvi", "std", g(d, "ndvi_stdDev"), "unitless", n, scale),
            rec("s2", "scene_count", "count", n_img, "count", None, scale, "scenes intersecting region")]


def worldcover(lat, lon, r_m, scale):
    P = laea(lat, lon)
    geom = ee.Geometry.Point([lon, lat]).buffer(r_m)
    wc = ee.ImageCollection("ESA/WorldCover/v200").mosaic().select("Map")
    im = ee.Image.cat([wc.eq(c).rename(f"c{c}") for c in WC_CLASSES]).updateMask(wc.mask())
    d = im.reduceRegion(reducer=mean_count(), geometry=geom, scale=scale, crs=P, maxPixels=1e10, tileScale=8).getInfo()
    rows = []
    for c in WC_CLASSES:
        v = g(d, f"c{c}_mean")
        name = "bare_fraction" if c == 60 else f"class_fraction_{c}"
        rows.append(rec("worldcover", name, "fraction", v, "fraction", g(d, f"c{c}_count"), scale,
                        "" if v is not None else "no_valid_pixels (product masked or no coverage at site)"))
    return rows


def s1(lat, lon, r_m, scale):
    P = laea(lat, lon)
    geom = ee.Geometry.Point([lon, lat]).buffer(r_m)
    col = (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(geom).filterDate("2024-01-01", "2026-01-01")
           .filter(ee.Filter.eq("instrumentMode", "IW"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
           .select(["VV", "VH"]))
    n_img = col.size().getInfo()
    rows = []
    if n_img == 0:
        for v in ("vv_db", "vh_db"):
            for st in ("mean", "std"):
                rows.append(rec("s1", v, st, None, "dB", None, scale, "no_images"))
        rows.append(rec("s1", "scene_count", "count", 0, "count", None, scale, "no_images"))
        return rows
    c = col.map(lambda i: i.updateMask(i.gt(-50)))
    red = ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True).combine(ee.Reducer.count(), sharedInputs=True)
    d = c.median().reduceRegion(reducer=red, geometry=geom, scale=scale, crs=P, maxPixels=1e10, tileScale=16).getInfo()
    for band, v in (("VV", "vv_db"), ("VH", "vh_db")):
        n = g(d, f"{band}_count")
        rows.append(rec("s1", v, "mean", g(d, f"{band}_mean"), "dB", n, scale))
        rows.append(rec("s1", v, "std", g(d, f"{band}_stdDev"), "dB", n, scale))
    rows.append(rec("s1", "scene_count", "count", n_img, "count", None, scale, "scenes intersecting region"))
    return rows


def fetch_thumb(img, P, n):
    """512 x 512 render of the 20 km box, fetched as n x n tiles (same pixels as one request, less memory)."""
    px, side = 512 // n, 20000 / n
    full = Image.new("RGB", (512, 512))
    for iy in range(n):
        for ix in range(n):
            x0 = -10000 + ix * side
            y1 = 10000 - iy * side
            reg = ee.Geometry.Rectangle([x0, y1 - side, x0 + side, y1], proj=ee.Projection(P), geodesic=False)
            url = img.getThumbURL({"region": reg, "dimensions": f"{px}x{px}", "crs": P, "format": "png"})
            t = Image.open(io.BytesIO(urllib.request.urlopen(url, timeout=600).read())).convert("RGB")
            if t.size != (px, px):
                t = t.resize((px, px))
            full.paste(t, (ix * px, iy * px))
    return full


def chip(lat, lon, slug, _scale):
    """10 km radius only. Writes public/img/sites/<slug>.jpg or records 'no clear imagery'."""
    P = laea(lat, lon)
    box = ee.Geometry.Rectangle([-10000, -10000, 10000, 10000], proj=ee.Projection(P), geodesic=False)
    col, c = s2_masked(box, "rgb")
    n_img = col.size().getInfo()
    status = {"slug": slug, "scene_count": n_img, "clear_fraction": 0.0, "status": "no clear imagery",
              "bytes": None, "jpeg_quality": None}
    if n_img > 0:
        cnt = c.select("B4").count()
        d = cnt.gte(3).reduceRegion(reducer=ee.Reducer.mean(), geometry=box, scale=100, crs=P,
                                    maxPixels=1e9, tileScale=16).getInfo()
        frac = g(d, "B4") or 0.0
        status["clear_fraction"] = frac
        if frac >= 0.5:
            img = c.median().visualize(bands=["B4", "B3", "B2"], min=0, max=3000, gamma=1.4)
            im = fetch_thumb(img, P, int(_scale or 1))
            status["tiles_per_side"] = int(_scale or 1)
            import numpy as np
            status["saturated_fraction"] = float((np.asarray(im).min(axis=2) >= 250).mean())
            for q in JPEG_LADDER:
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=q, optimize=True)
                if buf.tell() <= CHIP_MAX_BYTES:
                    CHIP_DIR.mkdir(parents=True, exist_ok=True)
                    (CHIP_DIR / f"{slug}.jpg").write_bytes(buf.getvalue())
                    status.update(status="ok", bytes=buf.tell(), jpeg_quality=q)
                    break
            else:
                status["status"] = "chip over budget"
    (CACHE / "chips").mkdir(parents=True, exist_ok=True)
    (CACHE / "chips" / f"{slug}.json").write_text(json.dumps(status), encoding="utf-8")
    note = status["status"] if status["status"] != "ok" else f"chip saved q={status['jpeg_quality']} bytes={status['bytes']}"
    out = [rec("s2_chip", "chip_clear_fraction", "fraction", status["clear_fraction"], "fraction", None, 100, note)]
    if status.get("saturated_fraction") is not None:
        out.append(rec("s2_chip", "chip_saturated_fraction", "fraction", status["saturated_fraction"], "fraction", None, 512,
                       "post-hoc addition, not in PREREG_C: share of chip pixels with R,G,B all >= 250 of 255"))
    return out


# ---------------------------------------------------------------- orchestration
class Runner:
    def __init__(self, out_csv: Path, done_file: Path, workers: int):
        self.out_csv, self.done_file, self.workers = out_csv, done_file, workers
        self.lock = threading.Lock()
        self.started = now_ist()
        self.total = self.finished = 0
        self.failures: list[str] = []
        self.active: dict[str, str] = {}
        self.stopped = False

    def write_rows(self, rows: list[dict]):
        with self.lock:
            new = not self.out_csv.exists()
            self.out_csv.parent.mkdir(parents=True, exist_ok=True)
            with self.out_csv.open("a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
                if new:
                    w.writeheader()
                w.writerows(rows)

    def mark_done(self, key: str):
        with self.lock:
            with self.done_file.open("a", encoding="utf-8") as f:
                f.write(key + "\n")
            self.finished += 1

    def status_loop(self, stop_evt: threading.Event):
        while True:
            self.write_status()
            if stop_evt.wait(600):
                break
        self.write_status()

    def write_status(self, final=False):
        with self.lock:
            lines = [
                "# STATUS_C (not committed)", "",
                f"- updated: {now_ist():%Y-%m-%d %H:%M:%S} IST",
                f"- started: {self.started:%Y-%m-%d %H:%M:%S} IST",
                f"- hard stop: {STOP_IST:%H:%M} IST",
                f"- coordinates done: {self.finished} / {self.total}",
                f"- failed tasks: {len(self.failures)}",
                f"- stopped by hard stop: {self.stopped}",
                "", "## Active", *[f"- {k}: {v}" for k, v in self.active.items()],
                "", "## Failures", *[f"- {x}" for x in self.failures[-40:]],
            ]
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        STATUS.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def do_coord(self, group: list[dict]):
        lat, lon = group[0]["lat"], group[0]["lon"]
        key = f"{lat},{lon}"
        slug = slugify(group[0]["Site_name"])
        tasks = []
        for r_m in RADII_M:
            tasks += [("terrain", r_m, terrain, None), ("mod11a2", r_m, modis, None), ("aster_ged", r_m, aster, None),
                      ("s2", r_m, s2_ndvi, (10, 10, 20, 30, 60)), ("worldcover", r_m, worldcover, (10, 10, 20, 30, 60)),
                      ("s1", r_m, s1, (10, 10, 20, 30, 60))]
        tasks.append(("chip", 10000, None, None))
        results: list[tuple[int, dict]] = []
        for name, r_m, fn, ladder in tasks:
            self.active[slug] = f"{name} r={r_m}"
            label = f"{slug}:{name}:{r_m}"
            pulled = utc_iso()
            try:
                if name == "chip":
                    recs, sc = run_task(label, lambda s: chip(lat, lon, slug, s), (1, 2, 4, 8, 8)), None
                    recs = recs[0]
                else:
                    recs, sc = run_task(label, lambda s, fn=fn, r_m=r_m: fn(lat, lon, r_m, s), ladder or (None,) * 5)
            except StopRun:
                self.stopped = True
                raise
            except Exception as e:  # noqa: BLE001
                msg = f"{label}: {e}"
                with self.lock:
                    self.failures.append(msg)
                log.error("FAILED %s", msg)
                ds = {"terrain": "cop_dem", "chip": "s2_chip"}.get(name, name)
                recs = [rec(ds, "TASK", "FAILED", None, "", None, None, f"FAILED: {str(e)[:200]}")]
            for x in recs:
                x["radius_m"] = r_m
                x["pulled_utc"] = pulled
            results.extend((r_m, x) for x in recs)
        out = []
        for row in group:
            for r_m, x in results:
                meta = META[x["dataset"]]
                approx = row["coord_flag"] == "approx"
                out.append(dict(
                    site_name=row["Site_name"], body=row["Body"], list=row["Category"],
                    radius_km=r_m // 1000, coord_flag=row["coord_flag"], dataset=x["dataset"], variable=x["variable"],
                    stat=x["stat"], value="" if x["value"] is None else x["value"], units=x["units"],
                    n_pixels="" if x["n_pixels"] is None else x["n_pixels"], product_id=meta["product"],
                    version=meta["version"], doi_or_url=meta["doi"], date_range=meta["dates"], lat=lat, lon=lon,
                    scale_m="" if x["scale_m"] is None else x["scale_m"],
                    page_ok=0 if (approx and r_m == 2000) else 1, note=x["note"], pulled_utc=x["pulled_utc"]))
        self.write_rows(out)
        self.mark_done(key)
        self.active.pop(slug, None)
        log.info("done %s (%d of %d)", slug, self.finished, self.total)

    def run(self, groups: list[list[dict]]):
        done = set(self.done_file.read_text(encoding="utf-8").split("\n")) if self.done_file.exists() else set()
        todo = [g_ for g_ in groups if f"{g_[0]['lat']},{g_[0]['lon']}" not in done]
        self.total = len(groups)
        self.finished = len(groups) - len(todo)
        log.info("coordinates: %d total, %d already done, %d to run", len(groups), self.finished, len(todo))
        stop_evt = threading.Event()
        t = threading.Thread(target=self.status_loop, args=(stop_evt,), daemon=True)
        t.start()
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futs = [ex.submit(self.do_coord, g_) for g_ in todo]
            for f in futs:
                try:
                    f.result()
                except StopRun:
                    log.error("hard stop reached; remaining coordinates not run")
                except Exception:  # noqa: BLE001
                    log.exception("coordinate crashed")
                    self.failures.append("coordinate crashed: see log")
        stop_evt.set()
        t.join()
        self.write_status()
        return len(self.failures) == 0 and not self.stopped


def load_groups(only: list[str] | None) -> list[list[dict]]:
    df = pd.read_csv(CSV_IN, encoding="utf-8-sig", usecols=USE_COLS)
    df["coord_flag"] = df["Coordinate_note"].str.contains("approx", case=False).map({True: "approx", False: "ok"})
    rows = [dict(r, lat=float(r["Latitude"]), lon=float(r["Longitude"])) for r in df.to_dict("records")]
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["lat"], r["lon"]), []).append(r)
    out = list(groups.values())
    if only:
        out = [g_ for g_ in out if any(r["Site_name"] in only for r in g_)]
    slugs = {}
    for g_ in out:
        for r in g_:
            slugs.setdefault(slugify(r["Site_name"]), set()).add((r["lat"], r["lon"]))
    clash = {k: v for k, v in slugs.items() if len(v) > 1}
    if clash:
        raise SystemExit(f"slug collision across different coordinates: {clash}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    LOGS.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(threadName)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(LOGS / ("smoke.log" if a.smoke else "run.log"), encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    ee.Initialize(project=PROJECT)
    ee.data.setDeadline(900000)
    groups = load_groups(SMOKE_SITES if a.smoke else None)
    if a.smoke:
        runner = Runner(CACHE / "smoke_site_measurements.csv", CACHE / "smoke_done.txt", min(a.workers, 3))
    else:
        runner = Runner(OUT_CSV, CACHE / "done_coords.txt", a.workers)
    ok = runner.run(groups)
    log.info("finished ok=%s failures=%d", ok, len(runner.failures))
    for x in runner.failures:
        print("FAILED:", x)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
