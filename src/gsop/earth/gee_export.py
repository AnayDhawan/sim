"""Google Earth Engine route: every Earth layer is computed server-side and exported as a 6 km raster, one band per feature.

Grid: EPSG:6933, 6000 m cells, origin at the grid's top-left (gsop.grid). Working grids are aligned to the same origin:
33.333 m (DEM), 500 m (slope baseline) and 6000 m (tile), so a 6 km tile is exactly 12 x 12 cells of 500 m and 180 x 180
cells of 33.333 m, and the 100 m and 1000 m roughness windows are 3 x 3 and 30 x 30 cells.

The terrain operator is gsop.operators implemented on the server: block-mean to 500 m, Horn 3x3 slope (an explicit kernel,
NOT ee.Terrain.slope, which uses 4 connected neighbours), tile percentiles 50 and 90, relief = max - min of the 500 m
cells, plane-removed RMS roughness per window (closed form from window moments) with the median per tile.

Dataset IDs were verified against the live catalog on 2026-11-13 (see docs/PROVENANCE.md). Run:
    uv run gsop s2 earth --source gee --test-box   (small region, direct download)
    uv run gsop s2 earth --source gee --export     (global, tasks to Google Drive)
"""

from __future__ import annotations

import io
import json
import math
import zipfile
from pathlib import Path
from typing import Any

import ee
import numpy as np

from pyproj import CRS as _CRS

from ..grid import Grid

PROJECT = "gsop-earthengine"
# Earth Engine cannot parse the string "EPSG:6933" nor the default WKT2 (HTTP 400, tested 2026-11-13).
# It accepts WKT1 (GDAL flavour), so the CRS is passed that way.
CRS_WKT = _CRS.from_epsg(6933).to_wkt(version="WKT1_GDAL")
YEARS = ("2015-01-01", "2025-01-01")             # MODIS and GPM climatology window, 2015 through 2024
LC_YEAR = "2023-01-01"                           # MCD12Q1 year (the collection runs to 2024)
NASADEM_LAT = (-56.0, 60.0)                      # NASADEM between 56S and 60N, Copernicus elsewhere
DEM_SCALE = 100.0 / 3.0
# Optional coarser DEM source for cost probes (docs/EE_COST.md). "COPERNICUS/DEM/GLO90" does not exist in the catalog
# (getAsset returned "not found" on 2026-11-13); CGIAR/SRTM90_V4 resolves (band elevation, about 92.8 m nominal).
DEM90_ID = "CGIAR/SRTM90_V4"

IDS = {
    "nasadem": "NASA/NASADEM_HGT/001", "cop30": "COPERNICUS/DEM/GLO30_2024_1", "lst": "MODIS/061/MOD11A2",
    "ndvi": "MODIS/061/MOD13A2", "lc": "MODIS/061/MCD12Q1", "pet": "MODIS/061/MOD16A2GF",
    "gpm": "NASA/GPM_L3/IMERG_MONTHLY_V07", "aster": "NASA/ASTER_GED/AG100_003", "merra": "NASA/GSFC/MERRA/aer/2",
}
BANDS = ["land_frac", "water_ice_frac", "ndvi_median", "built_crop_frac", "slope_med", "slope_p90", "relief", "rough_a",
         "rough_b", "elev_mean", "t_mean", "t_coldest", "ti_proxy", "ti_is_fallback", "dust_index", "water_index",
         "silica_index"]
VALID_MIN = 0.9


def init(project: str = PROJECT) -> None:
    ee.Initialize(project=project)


def proj(scale: float, g: Grid | None = None) -> ee.Projection:
    g = g or Grid()
    return ee.Projection(CRS_WKT, [scale, 0, g.x0, 0, -scale, g.y_top])


def _agg(img: ee.Image, reducer, scale: float, max_pixels: int) -> ee.Image:
    """Aggregate to the grid of cell size `scale` (aligned to the project grid origin)."""
    # maxPixels is a limit, not a size: a few percent of margin avoids "Need 401, but only 400 allowed" when a region edge
    # puts one extra source pixel into an output cell (seen 2026-11-14 on a 110 x 110 tile task at the equator).
    return img.reduceResolution(reducer=reducer, bestEffort=False, maxPixels=int(max_pixels * 1.25) + 2).reproject(proj(scale))


def _valid(img: ee.Image, scale: float, max_pixels: int, min_frac: float = VALID_MIN) -> ee.Image:
    """Share of valid input cells per output cell, as a 0/1 image: 1 where at least min_frac of the cells are valid."""
    frac = _agg(img.mask().reduce(ee.Reducer.min()).toFloat(), ee.Reducer.mean(), scale, max_pixels)
    return frac.gte(min_frac)


def verify_catalog(project: str = PROJECT) -> list[dict[str, Any]]:
    """Checks that every dataset id in IDS resolves in the live catalog. One dict per id: key, id, ok, detail."""
    init(project)
    out = []
    for key, asset_id in IDS.items():
        try:
            info = ee.data.getAsset(asset_id)
            out.append({"key": key, "id": asset_id, "ok": True, "detail": str(info.get("type", "asset"))})
        except Exception as e:  # noqa: BLE001  (any Earth Engine or network error means this id is not verified)
            out.append({"key": key, "id": asset_id, "ok": False, "detail": str(e)[:300]})
    return out


# --------------------------------------------------------------------------- terrain

def dem(source: str = "auto") -> ee.Image:
    """source "auto": NASADEM between 56S and 60N, Copernicus GLO30 elsewhere (default). source "srtm90": CGIAR SRTM 90 m.
    source "glo30": Copernicus GLO30 mosaic everywhere (EGM2008 vertical datum; SRTM and NASADEM use EGM96, which does not
    matter here because only slope, relief and roughness are used, never absolute heights)."""
    if source == "srtm90":
        s90 = ee.Image(DEM90_ID).select("elevation").rename("z")
        return s90.setDefaultProjection(s90.projection())
    if source == "glo30":
        # The mosaic is read on a 3 arc second lattice (about 92.8 m, the SRTM90 resolution), not on the 1 arc second
        # lattice of the first tile: the source footprint of a chunk is limited to about 2^26 pixels (see FOOTPRINT_PX_LIMIT)
        # and a 1 arc second lattice would allow only about 400 tiles per task at 65N. Earth Engine reads a coarser
        # pyramid level (mean) for it, so this is close to a 3 x 3 block mean before the average to 100 m.
        coll = ee.ImageCollection(IDS["cop30"]).select("DEM")
        return coll.mosaic().rename("z").setDefaultProjection(ee.Projection("EPSG:4326", [3 / 3600, 0, -180, 0, -3 / 3600, 90]))
    if source != "auto":
        raise ValueError(f"unknown DEM source {source!r}")
    cop = ee.ImageCollection(IDS["cop30"]).select("DEM").mosaic().rename("z")
    cop = cop.setDefaultProjection(ee.ImageCollection(IDS["cop30"]).first().select("DEM").projection())
    nas = ee.Image(IDS["nasadem"]).select("elevation").rename("z")
    lat = ee.Image.pixelLonLat().select("latitude")
    sel = lat.gte(NASADEM_LAT[0]).And(lat.lt(NASADEM_LAT[1]))
    return cop.blend(nas.updateMask(sel)).setDefaultProjection(cop.projection())


HORN_X = [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]]
HORN_Y = [[-1, -2, -1], [0, 0, 0], [1, 2, 1]]
COS30 = math.cos(math.radians(30.0))


def ground_scale_kx(lat_deg):
    """kx = cos(lat) / cos(30 deg): ground metres per projected metre east-west on EPSG:6933 (north-south is 1/kx).
    Same formula as operators.slope_deg and gee_operators.kx_from_lat (DECISIONS E12)."""
    return np.cos(np.radians(np.asarray(lat_deg, dtype=np.float64))) / COS30


def horn_slope_deg(z500: ee.Image, ground_scale: bool = False) -> ee.Image:
    """Horn 3x3 slope on the 500 m grid. ground_scale=True applies kx per pixel (latitude from pixelLonLat on the 500 m
    grid): dz/dx is divided by kx and dz/dy multiplied by kx, so the slope is the slope on the ground (E12). Default False:
    the gate and terrain90/GLO30 exports already running were built without it (E25), and one global layer must come from
    one graph. `horn_slope_deg_np` is the numpy mirror of this expression."""
    kx = ee.Kernel.fixed(3, 3, HORN_X, normalize=False)
    ky = ee.Kernel.fixed(3, 3, HORN_Y, normalize=False)
    dzdx = z500.convolve(kx).divide(8 * 500.0)
    dzdy = z500.convolve(ky).divide(8 * 500.0)
    if ground_scale:
        lat = ee.Image.pixelLonLat().select("latitude").reproject(proj(500.0))
        k = lat.multiply(math.pi / 180.0).cos().divide(COS30)
        dzdx = dzdx.divide(k)
        dzdy = dzdy.multiply(k)
    return dzdx.hypot(dzdy).atan().multiply(180.0 / math.pi)


def horn_slope_deg_np(z: np.ndarray, cell_m: float = 500.0, lat_rows: np.ndarray | None = None) -> np.ndarray:
    """numpy mirror of horn_slope_deg on a 2-D grid (rows north to south). lat_rows: latitude of each row for the kx
    correction, or None for no correction. Edge cells are NaN."""
    z = np.asarray(z, dtype=np.float64)
    out = np.full(z.shape, np.nan)
    gx = np.zeros((z.shape[0] - 2, z.shape[1] - 2))
    gy = np.zeros_like(gx)
    for di in range(3):
        for dj in range(3):
            win = z[di:di + z.shape[0] - 2, dj:dj + z.shape[1] - 2]
            gx += HORN_X[di][dj] * win
            gy += HORN_Y[di][dj] * win
    dzdx, dzdy = gx / (8 * cell_m), gy / (8 * cell_m)
    if lat_rows is not None:
        k = ground_scale_kx(np.asarray(lat_rows)[1:-1]).reshape(-1, 1)
        dzdx, dzdy = dzdx / k, dzdy * k
    out[1:-1, 1:-1] = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    return out


def plane_rms(z33: ee.Image, k: int, dem_scale: float = DEM_SCALE) -> ee.Image:
    """RMS residual after plane removal in k x k windows (closed form from the window moments).
    Each window is centred on its own mean before squaring: mean(z^2) - mean(z)^2 on raw elevations (about 500 m)
    cancels to exactly 0 in float32 and gave rough_a = rough_b = 0 on the first Lonar test."""
    pc = ee.Image.pixelCoordinates(proj(dem_scale))
    cx = pc.select("x").mod(k).subtract((k - 1) / 2.0)
    cy = pc.select("y").mod(k).subtract((k - 1) / 2.0)
    scale = dem_scale * k
    mean = ee.Reducer.mean()
    z = z33.toDouble()
    mz = _agg(z, mean, scale, k * k)
    d = z.subtract(mz)                       # mz is constant per window, so d has zero mean in every window
    md2 = _agg(d.pow(2), mean, scale, k * k)
    mxd = _agg(d.multiply(cx), mean, scale, k * k)
    myd = _agg(d.multiply(cy), mean, scale, k * k)
    vx = (k * k - 1) / 12.0
    mse = md2.subtract(mxd.pow(2).add(myd.pow(2)).divide(vx))
    return mse.max(0).sqrt()


def gate_pass_mask() -> ee.Image:
    """6 km image, 1 where a tile passes the three gates (ndvi_median <= 0.2, water_ice_frac <= 0.5, built_crop_frac <= 0.2),
    0 where it fails, masked where a gate band is missing. Built from landcover_bands()."""
    lc = landcover_bands()
    return (lc.select("ndvi_median").lte(0.2).And(lc.select("water_ice_frac").lte(0.5))
            .And(lc.select("built_crop_frac").lte(0.2)).rename("gate_pass"))


def terrain_bands(dem_scale: float = DEM_SCALE, dem_source: str = "auto",
                  rough_cells: tuple[int, int] = (3, 30), tile_mask: ee.Image | None = None,
                  ground_scale: bool = False) -> ee.Image:
    """Terrain bands. Defaults reproduce the 33.333 m route. For a coarser working grid pass dem_scale (for example 100.0),
    dem_source "srtm90" and rough_cells (3, 10); the slope baseline stays 500 m and the tile stays 6000 m. dem_scale must
    divide 500 and 6000 m, and the roughness windows (dem_scale * k) must divide 6000 m.
    tile_mask: optional 6 km image (for example gate_pass_mask()); the DEM is masked with it right after the first
    aggregation, before every reduction. Masked tiles come out masked in all six bands. Default None, output unchanged.
    ground_scale: apply the kx slope correction (horn_slope_deg). Default False, the graph of the running exports (E25)."""
    default = dem_scale == DEM_SCALE
    # 100 m cell against the 3 arc second lattice: at most about 10 source pixels per cell up to 83 degrees
    z33 = _agg(dem(dem_source), ee.Reducer.mean(), dem_scale, 64 if default else (64 if dem_source == "glo30" else 16))
    if tile_mask is not None:
        z33 = z33.updateMask(tile_mask)
    z500 = _agg(z33, ee.Reducer.mean(), 500.0, 300)
    s500 = horn_slope_deg(z500, ground_scale).rename("slope")
    pct = _agg(s500, ee.Reducer.percentile([50, 90]), 6000.0, 144)
    ok_s = _valid(s500, 6000.0, 144)
    zmin = _agg(z500, ee.Reducer.min(), 6000.0, 144)
    zmax = _agg(z500, ee.Reducer.max(), 6000.0, 144)
    zmean = _agg(z500, ee.Reducer.mean(), 6000.0, 144)
    ok_z = _valid(z500, 6000.0, 144)
    out = [pct.select("slope_p50").rename("slope_med").updateMask(ok_s),
           pct.select("slope_p90").updateMask(ok_s),
           zmax.subtract(zmin).rename("relief").updateMask(ok_z),
           zmean.rename("elev_mean").updateMask(ok_z)]
    for name, k in (("rough_a", rough_cells[0]), ("rough_b", rough_cells[1])):
        r = plane_rms(z33, k, dem_scale)
        tile_cells = int(round(6000 / (dem_scale * k))) ** 2
        med = _agg(r, ee.Reducer.median(), 6000.0, tile_cells)
        out.append(med.updateMask(_valid(r, 6000.0, tile_cells)).rename(name))
    return ee.Image.cat(out)


# --------------------------------------------------------------------------- land cover, vegetation

def landcover_bands() -> ee.Image:
    lc = ee.ImageCollection(IDS["lc"]).filterDate(LC_YEAR, "2024-01-01").first().select("LC_Type1")
    mean = ee.Reducer.mean()

    def frac(mask: ee.Image, name: str) -> ee.Image:
        return _agg(mask.toFloat().updateMask(lc.mask()), mean, 6000.0, 144 * 4).rename(name)

    # IGBP classes: 17 water bodies, 15 permanent snow and ice, 13 urban and built-up, 12 croplands.
    land = frac(lc.neq(17), "land_frac")
    wi = frac(lc.eq(17).Or(lc.eq(15)), "water_ice_frac")
    bc = frac(lc.eq(13).Or(lc.eq(12)), "built_crop_frac")
    nd_ic = ee.ImageCollection(IDS["ndvi"])
    ndvi = (nd_ic.filterDate(*YEARS).select("NDVI").median().multiply(0.0001)
            .setDefaultProjection(nd_ic.first().select("NDVI").projection()))
    nd = _agg(ndvi, ee.Reducer.median(), 6000.0, 144 * 4).rename("ndvi_median")
    return ee.Image.cat([land, wi, nd, bc])


# --------------------------------------------------------------------------- climate

def _monthly(ic: ee.ImageCollection, fn) -> list[ee.Image]:
    return [fn(ic.filter(ee.Filter.calendarRange(m, m, "month"))) for m in range(1, 13)]


def _water_index() -> ee.Image:
    """water_index at 6 km: 1 - min(AI, 1) with AI = P / PET (UNEP); 1 is arid."""
    gpm = ee.ImageCollection(IDS["gpm"]).filterDate(*YEARS).select("precipitation")
    # IMERG monthly 'precipitation' is a rate in mm/hr; MOD16A2GF PET is kg/m2 per 8 days with scale 0.1.
    p_year = gpm.mean().multiply(24 * 365.25)
    pet = ee.ImageCollection(IDS["pet"]).filterDate(*YEARS).select("PET")
    pet_year = pet.mean().multiply(0.1).multiply(365.25 / 8.0)
    pp = ee.ImageCollection(IDS["pet"]).first().select("PET").projection()
    arid = (ee.Image(1).subtract(p_year.divide(pet_year).min(1)).rename("water_index")
            .setDefaultProjection(pp))
    return _agg(arid, ee.Reducer.mean(), 6000.0, 400)


def water_index_band() -> ee.Image:
    """The aridity-only band water_index on its own (same values as the water_index band of climate_bands())."""
    return _water_index()


def climate_bands() -> ee.Image:
    lst = ee.ImageCollection(IDS["lst"]).filterDate(*YEARS)
    day, night = lst.select("LST_Day_1km"), lst.select("LST_Night_1km")
    mean_k = lst.map(lambda i: i.select("LST_Day_1km").add(i.select("LST_Night_1km")).multiply(0.01).rename("t")
                     .copyProperties(i, ["system:time_start"]))
    mean_months = _monthly(mean_k, lambda c: c.mean())
    t_mean = mean_k.mean().rename("t_mean")
    t_cold = ee.ImageCollection(mean_months).min().rename("t_coldest")
    swing = lst.map(lambda i: i.select("LST_Day_1km").subtract(i.select("LST_Night_1km")).multiply(0.02).rename("d")
                      .copyProperties(i, ["system:time_start"]))
    swing_months = _monthly(swing, lambda c: c.mean())
    gpm = ee.ImageCollection(IDS["gpm"]).filterDate(*YEARS).select("precipitation")
    pr_months = _monthly(gpm, lambda c: c.mean())

    def window(s: int) -> ee.Image:
        idx = [(s + j) % 12 for j in range(3)]
        p3 = ee.ImageCollection([pr_months[i] for i in idx]).sum().rename("p3")
        d3 = ee.ImageCollection([swing_months[i] for i in idx]).mean().rename("d3")
        return p3.multiply(-1).rename("q").addBands([p3, d3])

    dry = ee.ImageCollection([window(s) for s in range(12)]).qualityMosaic("q")
    annual_swing = swing.median().rename("d3")
    dry_d = dry.select("d3")
    ti = dry_d.unmask(annual_swing).rename("ti_proxy")
    fallback = dry_d.mask().Not().rename("ti_is_fallback").toFloat()
    mean = ee.Reducer.mean()
    lp = ee.ImageCollection(IDS["lst"]).first().select("LST_Day_1km").projection()
    t_bands = ee.Image.cat([_agg(t_mean.setDefaultProjection(lp), mean, 6000.0, 400),
                            _agg(t_cold.setDefaultProjection(lp), mean, 6000.0, 400),
                            _agg(ti.setDefaultProjection(lp), mean, 6000.0, 400),
                            _agg(fallback.setDefaultProjection(lp), mean, 6000.0, 400)])
    water = _water_index()
    mr = ee.ImageCollection(IDS["merra"])
    dust = _agg(mr.filterDate(*YEARS).select("DUEXTTAU").mean()
                .setDefaultProjection(mr.first().select("DUEXTTAU").projection()), mean, 6000.0, 400)
    aster = ee.Image(IDS["aster"])
    e10, e11, e12 = (aster.select(f"emissivity_band{b}").multiply(0.001) for b in (10, 11, 12))
    qi = e11.pow(2).divide(e10.multiply(e12)).rename("silica_index")
    silica = _agg(qi, mean, 6000.0, 4000)   # ASTER GED is 100 m: about 3600 cells per tile
    return ee.Image.cat([t_bands.select(["t_mean", "t_coldest", "ti_proxy", "ti_is_fallback"]),
                         dust.rename("dust_index"), water, silica])


def full_stack() -> ee.Image:
    img = ee.Image.cat([landcover_bands(), terrain_bands(), climate_bands()]).select(BANDS).toFloat()
    return img


# --------------------------------------------------------------------------- regions and export

def chunk_region(ix0: int, iy0: int, w: int, h: int, g: Grid | None = None) -> tuple[ee.Geometry, list[float]]:
    g = g or Grid()
    xl, yt = g.x0 + ix0 * g.cell_m, g.y_top - iy0 * g.cell_m
    geom = ee.Geometry.Rectangle([xl, yt - h * g.cell_m, xl + w * g.cell_m, yt], proj=CRS_WKT, geodesic=False)
    return geom, [g.cell_m, 0, xl, 0, -g.cell_m, yt]


def lonlat_box_to_cells(lon: float, lat: float, half_km: float, g: Grid | None = None) -> tuple[int, int, int, int]:
    g = g or Grid()
    ix, iy = (int(v) for v in g.cell_of_lonlat(lon, lat))
    n = int(round(half_km / (g.cell_m / 1000.0)))
    return ix - n, iy - n, 2 * n, 2 * n


def download_test_box(lon: float, lat: float, half_km: float, out_dir: Path, name: str = "box") -> Path:
    """Direct download of a small region as per-band GeoTIFFs. For testing before any global export."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ix0, iy0, w, h = lonlat_box_to_cells(lon, lat, half_km)
    geom, tf = chunk_region(ix0, iy0, w, h)
    url = full_stack().getDownloadURL({"region": geom, "crs": CRS_WKT, "crs_transform": tf,
                                       "format": "ZIPPED_GEO_TIFF", "filePerBand": True})
    import requests
    r = requests.get(url, timeout=1800)
    if not r.ok:
        raise RuntimeError(f"Earth Engine download failed {r.status_code}: {r.text[:1500]}")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        z.extractall(out_dir)
    (out_dir / "bands.json").write_text(json.dumps({"bands": BANDS, "region": [ix0, iy0, w, h], "name": name}))
    return out_dir


GATE_FOLDER = "gsop_gate"


def global_chunks(ncol: int = 10, nrow: int = 4, g: Grid | None = None) -> list[dict[str, Any]]:
    """The ncol x nrow chunking of the whole grid used by every global export: name, row, col and cells [ix0, iy0, w, h]."""
    g = g or Grid()
    cw, ch = -(-g.ncols // ncol), -(-g.nrows // nrow)
    out = []
    for r in range(nrow):
        for c in range(ncol):
            ix0, iy0 = c * cw, r * ch
            w, h = min(cw, g.ncols - ix0), min(ch, g.nrows - iy0)
            out.append({"name": f"gate_6km_r{r:02d}_c{c:02d}", "row": r, "col": c, "cells": [ix0, iy0, w, h]})
    return out


POLE_TRIM_ROWS = 2
# The whole north chunk r00_c03 (30N to 90N) failed in batch with "Reprojection output too large (9818x8284 pixels)"
# although each third of it ran fine interactively (measured 2026-11-13), so the top row of chunks is exported in
# ROW0_SPLIT horizontal pieces named <chunk>_p0 .. _pN.
ROW0_SPLIT = 3


def pole_trimmed(cells: list[int], g: Grid | None = None, trim: int = POLE_TRIM_ROWS) -> list[int]:
    """Cells [ix0, iy0, w, h] with `trim` rows removed at a pole edge. The grid has 2448 rows of 6000 m, which is 3.5 km
    more than the pole-to-pole extent (2 x Y_MAX), so row 2447 reaches past the south pole, and the export needs one
    more cell of border: with the full region the task fails with "(3474.0,2448.0) transformed to NaN" (measured
    2026-11-13, chunk r03_c05, EECU 91.9). The same trim is applied at the north edge (row 0 starts exactly at the north
    pole) so no export reaches past a pole. The trimmed rows are the last 12 km around each pole."""
    g = g or Grid()
    ix0, iy0, w, h = cells
    if iy0 == 0:
        iy0, h = iy0 + trim, h - trim
    if iy0 + h >= g.nrows:
        h -= trim
    return [ix0, iy0, w, h]


def plan_gate_pieces(ncol: int = 10, nrow: int = 4, only: list[str] | None = None) -> list[dict[str, Any]]:
    """Export tasks for the gate export: one per chunk, except the top chunk row (ROW0_SPLIT pieces named <chunk>_p0 ...).
    Poles are trimmed (pole_trimmed). Each piece: name, chunk, cells (the full chunk), exported_cells [ix0, iy0, w, h]."""
    g = Grid()
    pieces = []
    for ch in global_chunks(ncol, nrow, g):
        if only is not None and ch["name"] not in only:
            continue
        ix0, iy0, w, h = pole_trimmed(ch["cells"], g)
        k = ROW0_SPLIT if ch["row"] == 0 else 1
        edges = [iy0 + round(h * i / k) for i in range(k + 1)]
        for i in range(k):
            name = ch["name"] if k == 1 else f"{ch['name']}_p{i}"
            pieces.append({"name": name, "chunk": ch["name"], "cells": ch["cells"],
                           "exported_cells": [ix0, edges[i], w, edges[i + 1] - edges[i]]})
    return pieces


def split_piece(piece: dict[str, Any], k: int = 2) -> list[dict[str, Any]]:
    """Split a piece into k horizontal sub-pieces named <piece>_s0 ... (used to retry a piece that failed as too large)."""
    ix0, iy0, w, h = piece["exported_cells"]
    edges = [iy0 + round(h * i / k) for i in range(k + 1)]
    return [{"name": f"{piece['name']}_s{i}", "chunk": piece["chunk"], "cells": piece["cells"],
             "exported_cells": [ix0, edges[i], w, edges[i + 1] - edges[i]]} for i in range(k)]


def start_gate_piece(piece: dict[str, Any], folder: str = GATE_FOLDER, img: ee.Image | None = None) -> dict[str, Any]:
    """Start one gate export task (landcover_bands, GeoTIFF to Drive) for a piece. Sets and returns piece["id"]."""
    img = img if img is not None else landcover_bands().toFloat()
    geom, tf = chunk_region(*piece["exported_cells"])
    t = ee.batch.Export.image.toDrive(image=img, description=piece["name"], folder=folder, fileNamePrefix=piece["name"],
                                      region=geom, crs=CRS_WKT, crsTransform=tf, maxPixels=int(1e10),
                                      fileFormat="GeoTIFF")
    t.start()
    piece["id"] = t.id
    return piece


def start_gate_export(folder: str = GATE_FOLDER, ncol: int = 10, nrow: int = 4, only: list[str] | None = None,
                      start: bool = True) -> list[dict[str, Any]]:
    """Gate-only global export: landcover_bands() only (land_frac, water_ice_frac, ndvi_median, built_crop_frac), same
    10 x 4 chunking, grid, region and CRS handling as start_global_export, one GeoTIFF per chunk (top row: per piece) in the
    Drive folder. `only` restricts the chunks to the given names (for example gate_6km_r01_c05). start=False builds the
    plan and starts nothing."""
    pieces = plan_gate_pieces(ncol, nrow, only)
    if start:
        img = landcover_bands().toFloat()
        for pc in pieces:
            start_gate_piece(pc, folder, img)
    return pieces


TERRAIN_FOLDER = "gsop_terrain"


def start_terrain_export(regions: list[list[int]], folder: str = TERRAIN_FOLDER, start: bool = False) -> list[dict[str, Any]]:
    """Terrain only (terrain_bands(), 6 bands, 33.333 m) for task regions [ix0, iy0, w, h] in 6 km cells, as produced by
    gsop.earth.terrain_plan.plan_regions from the gate output. One GeoTIFF per region in the Drive folder. Regions that
    touch a pole are trimmed with pole_trimmed. start=False (the default) only builds the plan and starts nothing."""
    g = Grid()
    plan = []
    for i, cells in enumerate(regions):
        ix0, iy0, w, h = pole_trimmed(list(cells), g)
        plan.append({"name": f"terrain_6km_reg{i:03d}", "cells": list(cells), "exported_cells": [ix0, iy0, w, h]})
    if not start:
        return plan
    img = terrain_bands().toFloat()
    for pc in plan:
        geom, tf = chunk_region(*pc["exported_cells"], g)
        t = ee.batch.Export.image.toDrive(image=img, description=pc["name"], folder=folder, fileNamePrefix=pc["name"],
                                          region=geom, crs=CRS_WKT, crsTransform=tf, maxPixels=int(1e10),
                                          fileFormat="GeoTIFF")
        t.start()
        pc["id"] = t.id
    return plan


TERRAIN90_FOLDER = "gsop_terrain90"
TERRAIN90_LAT = (-56.0, 60.0)       # CGIAR/SRTM90_V4 covers about 56S to 60N; nothing exists outside
TERRAIN90_NODATA = -9999.0           # masked pixels are written as this value (the image is unmasked before export)


def terrain90_row_range(lat: tuple[float, float] = TERRAIN90_LAT, margin: int = 1, g: Grid | None = None) -> tuple[int, int]:
    """Grid rows [row_start, row_end) of the 6 km grid that cover the latitude band, plus `margin` rows on both sides."""
    from pyproj import Transformer
    g = g or Grid()
    tr = Transformer.from_crs("EPSG:4326", g.crs, always_xy=True)
    y_n = tr.transform(0.0, lat[1])[1]
    y_s = tr.transform(0.0, lat[0])[1]
    r0 = int((g.y_top - y_n) // g.cell_m) - margin
    r1 = int(-(-(g.y_top - y_s) // g.cell_m)) + margin
    return max(0, r0), min(g.nrows, r1)


# Measured 2026-11-14 (interactive reproject probes and batch failures): a task fails with "Reprojection output too large
# (WxH pixels)" when the SOURCE footprint of its region in the 3 arc second DEM lattice is more than about 2^26 = 67.1M
# pixels. Failures seen: 7551x9065 = 68.5M, 10536x7986 = 84M, 14939x10791 = 161M. For a region of w x h grid cells the
# footprint is 74.7 w x 56 h / cos(lat) pixels, so it is TILE_PX / cos(lat) per 6 km tile, independent of the shape.
FOOTPRINT_PX_LIMIT = 2 ** 26
FOOTPRINT_FRAC = 0.6                 # production margin below the limit
TILE_PX = (6000.0 / 92.77) ** 2      # 3 arc second source pixels per 6 km tile at the equator (4,183)


def _lat_of_row(row: float, g: Grid) -> float:
    from pyproj import Transformer
    return float(Transformer.from_crs(g.crs, "EPSG:4326", always_xy=True).transform(0.0, g.y_top - row * g.cell_m)[1])


def max_tiles_at(lat_abs: float, frac: float = FOOTPRINT_FRAC) -> int:
    """Largest number of 6 km tiles in one task whose source footprint stays under frac x the limit at latitude lat_abs."""
    import math
    return max(1, int(frac * FOOTPRINT_PX_LIMIT * math.cos(math.radians(min(lat_abs, 88.0))) / TILE_PX))


def adaptive_chunks(x0: int, y0: int, w_total: int, h_total: int, prefix: str, frac: float = FOOTPRINT_FRAC,
                    max_side: int = 200, g: Grid | None = None) -> list[dict[str, Any]]:
    """Cut the rectangle [x0, y0, w_total, h_total] (grid cells) into chunks whose tile count shrinks with 1/cos(lat):
    row bands of near-square chunks, each at most max_tiles_at(poleward latitude of the band) tiles. Names
    <prefix>_r<band>_c<col>. Pure Python, no Earth Engine call."""
    import math
    g = g or Grid()
    out, band, r = [], 0, y0
    end = y0 + h_total
    while r < end:
        h = min(max_side, end - r)
        while True:
            lat = max(abs(_lat_of_row(r, g)), abs(_lat_of_row(r + h, g)))
            hh = max(1, min(h, int(math.sqrt(max_tiles_at(lat, frac)))))
            if hh >= h:
                break
            h = hh
        w = max(1, min(w_total, max_tiles_at(lat, frac) // h))
        nc = -(-w_total // w)
        cw = -(-w_total // nc)
        for c in range(nc):
            ix0 = x0 + c * cw
            out.append({"name": f"{prefix}_r{band:02d}_c{c:02d}", "row": band, "col": c,
                        "cells": [ix0, r, min(cw, x0 + w_total - ix0), h]})
        band += 1
        r += h
    return out


def terrain90_chunks(lat: tuple[float, float] = TERRAIN90_LAT, frac: float = FOOTPRINT_FRAC,
                     g: Grid | None = None) -> list[dict[str, Any]]:
    """Chunking of the SRTM90 latitude band with the adaptive footprint rule (about 9,600 x cos(lat) tiles per task at
    frac 0.6). Names terrain90_r<band>_c<col>; cells [ix0, iy0, w, h] in grid cells. Pure Python."""
    g = g or Grid()
    r0, r1 = terrain90_row_range(lat, g=g)
    return adaptive_chunks(0, r0, g.ncols, r1 - r0, "terrain90", frac, g=g)


def terrain90_image() -> ee.Image:
    """The Probe C configuration at global scale: SRTM90, 100 m working grid, slope baseline 500 m, roughness windows 300 m
    and 1000 m. Six float32 bands (slope_med, slope_p90, relief, elev_mean, rough_a, rough_b); masked tiles are
    TERRAIN90_NODATA."""
    return terrain_bands(100.0, "srtm90", (3, 10)).toFloat().unmask(TERRAIN90_NODATA)


TERRAIN90_HI_FOLDER = "gsop_terrain90_hi"
HI_LAT_MAX = 83.0                    # stage 2 upper latitude limit
STAGE1_SITES = {                     # lat, lon from config/known_sites.yaml (targets-moon-mars branch, 2026-11-13)
    "haughton": (75.37, -89.68), "samoylov": (72.37, 126.48),
    "mcmurdo_dry_valleys": (-77.5, 162.0), "askja": (65.03, -16.75),
}
STAGE1_HALF_KM = 300.0               # 100 x 100 grid cells = 10,000 tiles per box


def terrain_glo30_image() -> ee.Image:
    """Terrain operator on Copernicus GLO30 averaged to the 100 m working grid: the same six bands and the same operator as
    terrain90_image() (500 m slope baseline, roughness windows of 3 and 10 cells = 300 m and 1000 m, 6 km tile)."""
    return terrain_bands(100.0, "glo30", (3, 10)).toFloat().unmask(TERRAIN90_NODATA)


def stage1_boxes(half_km: float = STAGE1_HALF_KM, frac: float = FOOTPRINT_FRAC) -> list[dict[str, Any]]:
    """Four validation boxes of 100 x 100 cells (10,000 tiles), each cut into adaptive chunks: names
    terrain90_stage1_<site>_r<band>_c<col>, field site. A box that reaches past a pole edge is shifted, not shrunk."""
    g = Grid()
    out = []
    for site, (lat, lon) in STAGE1_SITES.items():
        ix0, iy0, w, h = lonlat_box_to_cells(lon, lat, half_km, g)
        # keep boxes equatorward of about 83 degrees: the footprint rule makes chunks tiny near the poles
        r83 = max(POLE_TRIM_ROWS, int((g.y_top - 7_310_000.0) // g.cell_m))
        iy0 = min(max(iy0, r83), g.nrows - r83 - h)
        ix0 = min(max(ix0, 0), g.ncols - w)
        for c in adaptive_chunks(ix0, iy0, w, h, f"terrain90_stage1_{site}", frac, g=g):
            c["site"] = site
            out.append(c)
    return out


def stage2_chunks(lat_max: float = HI_LAT_MAX, frac: float = FOOTPRINT_FRAC) -> list[dict[str, Any]]:
    """Land above the SRTM90 band: grid rows from lat_max down to the first row of the SRTM90 band, in adaptive chunks,
    names terrain90_stage2_r<band>_c<col>. Pure Python. Ocean and Greenland are removed later by the script."""
    from pyproj import Transformer
    g = Grid()
    y_n = Transformer.from_crs("EPSG:4326", g.crs, always_xy=True).transform(0.0, lat_max)[1]
    r0 = max(0, int((g.y_top - y_n) // g.cell_m))
    r1 = terrain90_row_range(g=g)[0]
    return adaptive_chunks(0, r0, g.ncols, r1 - r0, "terrain90_stage2", frac, g=g)


def start_terrain90_task(img: ee.Image, name: str, cells: list[int], folder: str = TERRAIN90_FOLDER,
                         g: Grid | None = None) -> str:
    geom, tf = chunk_region(*cells, g or Grid())
    t = ee.batch.Export.image.toDrive(image=img, description=name, folder=folder, fileNamePrefix=name, region=geom,
                                      crs=CRS_WKT, crsTransform=tf, maxPixels=int(1e10), fileFormat="GeoTIFF")
    t.start()
    return t.id


def start_global_export(folder: str = "gsop_earth", ncol: int = 10, nrow: int = 4) -> list[dict[str, Any]]:
    g = Grid()
    img = full_stack()
    cw, ch = -(-g.ncols // ncol), -(-g.nrows // nrow)
    tasks = []
    for r in range(nrow):
        for c in range(ncol):
            ix0, iy0 = c * cw, r * ch
            w, h = min(cw, g.ncols - ix0), min(ch, g.nrows - iy0)
            geom, tf = chunk_region(ix0, iy0, w, h, g)
            name = f"earth_6km_r{r:02d}_c{c:02d}"
            t = ee.batch.Export.image.toDrive(image=img, description=name, folder=folder, fileNamePrefix=name,
                                              region=geom, crs=CRS_WKT, crsTransform=tf, maxPixels=int(1e10),
                                              fileFormat="GeoTIFF")
            t.start()
            tasks.append({"name": name, "id": t.id, "cells": [ix0, iy0, w, h]})
    return tasks
