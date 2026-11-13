"""Open-data fallback for the Earth feature rasters (issue #8), used when Earth Engine is not available.

What it does: reads rasters you have already downloaded (any GDAL-readable file, in any CRS), resamples them onto the
6 km EPSG:6933 grid with area averaging, and writes ONE multiband GeoTIFF with band descriptions that
`gsop s2 earth --source local --src <file>` reads (see `local_loaders.py`).

What it does NOT do, on purpose:
  * It does no temporal aggregation. t_mean, t_coldest, ti_proxy, ndvi_median and the other climatology layers must be
    prepared upstream (for example as an AppEEARS GeoTIFF export) and are only resampled here.
  * It never invents a layer. A column with no file in the spec is left out of the raster. The missing-data gate then
    rejects every tile for a target that needs it and says why (SPEC section 7). Nothing is substituted silently.
  * It never makes terrain finer than its source. Slope and relief use the same operator as every other body
    (`operators.py`, 500 m baseline), so the DEM must have cells of at most 500 m. A ~1.8 km global relief grid
    (for example ETOPO 60 arcsec) cannot give a 500 m baseline slope, so slope_med, slope_p90 and relief are then left
    out with the reason logged. rough_a and rough_b (100 m and 1000 m baselines) need native cells of at most 33 m and
    333 m and are always left out here: they come from the Earth Engine route. Left-out columns are listed in the
    returned report and in `open_data_report.json`.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from .. import operators as O
from ..grid import Grid
from ..provenance import write_json

METERS_PER_DEG = 111_320.0
MARGIN_CELLS = 1                      # one 500 m cell of context so slope is valid up to the tile edge
TERRAIN_COLUMNS = ("slope_med", "slope_p90", "relief", "rough_a", "rough_b")


# --------------------------------------------------------------------------- tile window

def tile_window(grid: Grid, bbox_lonlat: tuple[float, float, float, float] | None) -> tuple[int, int, int, int]:
    """(ix0, iy0, ix1, iy1) tile index window (ix1, iy1 exclusive). bbox = (lon_min, lat_min, lon_max, lat_max).
    None means the whole grid. A box that touches the antimeridian is not supported: use two runs."""
    if bbox_lonlat is None:
        return 0, 0, grid.ncols, grid.nrows
    lon0, lat0, lon1, lat1 = bbox_lonlat
    if not (lon0 < lon1 and lat0 < lat1):
        raise ValueError(f"bad bbox {bbox_lonlat}: need lon_min < lon_max and lat_min < lat_max")
    # equal-area y is monotonic in latitude, x in longitude, so the corners bound the window
    ix, iy = grid.cell_of_lonlat(np.array([lon0, lon1, lon0, lon1]), np.array([lat0, lat0, lat1, lat1]))
    return (max(int(ix.min()), 0), max(int(iy.min()), 0), min(int(ix.max()) + 1, grid.ncols),
            min(int(iy.max()) + 1, grid.nrows))


def _transform(grid: Grid, ix0: int, iy0: int, cell_m: float, margin_m: float = 0.0):
    from rasterio.transform import Affine
    return Affine(cell_m, 0, grid.x0 + ix0 * grid.cell_m - margin_m, 0, -cell_m, grid.y_top - iy0 * grid.cell_m + margin_m)


# --------------------------------------------------------------------------- resampling

def resample(src_path: Path | str, window: tuple[int, int, int, int], grid: Grid, cell_m: float | None = None,
             band: int = 1, method: str = "average", margin_m: float = 0.0) -> np.ndarray:
    """Reproject one raster band onto the tile grid window at `cell_m` (default: the 6 km tile).
    Cells with no source data are NaN. `margin_m` adds context on every side (for slope)."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import reproject
    cell_m = float(cell_m or grid.cell_m)
    ix0, iy0, ix1, iy1 = window
    h = int(round(((iy1 - iy0) * grid.cell_m + 2 * margin_m) / cell_m))
    w = int(round(((ix1 - ix0) * grid.cell_m + 2 * margin_m) / cell_m))
    dst = np.full((h, w), np.nan, dtype=np.float32)
    with rasterio.open(src_path) as ds:
        reproject(rasterio.band(ds, band), dst, src_nodata=ds.nodata, dst_nodata=np.nan,
                  dst_transform=_transform(grid, ix0, iy0, cell_m, margin_m), dst_crs=grid.crs,
                  resampling=Resampling[method])
    return dst


def source_cell_m(src_path: Path | str) -> float:
    """Coarsest native cell size of a raster in metres (the north-south size for geographic rasters)."""
    import rasterio
    with rasterio.open(src_path) as ds:
        if ds.crs is not None and ds.crs.is_geographic:
            return abs(ds.transform.e) * METERS_PER_DEG
        return max(abs(ds.transform.a), abs(ds.transform.e))


# --------------------------------------------------------------------------- terrain

def ground_scale_rows(grid: Grid, iy0: int, iy1: int, cell_m: float, margin_cells: int = MARGIN_CELLS) -> np.ndarray:
    """kx = cos(lat) / cos(30 deg) for every row of the resampled grid (margin rows included), see operators.slope_deg.
    Spherical approximation of EPSG:6933; the error against the ellipsoid is well under 1 percent."""
    from pyproj import Transformer
    n = int(round((iy1 - iy0) * grid.cell_m / cell_m)) + 2 * margin_cells
    y = grid.y_top - iy0 * grid.cell_m + margin_cells * cell_m - (np.arange(n) + 0.5) * cell_m
    _, lat = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True).transform(np.zeros(n), y)
    return np.cos(np.radians(lat)) / math.cos(math.radians(30.0))


def terrain_plan(dem_cell_m: float, op_cfg: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    """Which terrain columns a DEM with this cell size can honestly give, and why the others cannot."""
    base = float(op_cfg["slope_baseline_m"])
    have: list[str] = []
    left_out: dict[str, str] = {}
    if dem_cell_m <= base:
        have += ["slope_med", "slope_p90", "relief"]
    else:
        why = (f"DEM cell is about {dem_cell_m:.0f} m, coarser than the {base:.0f} m slope baseline; "
               "slope would be finer than the data")
        for c in ("slope_med", "slope_p90", "relief"):
            left_out[c] = why
    for col, key in (("rough_a", "rough_a_baseline_m"), ("rough_b", "rough_b_baseline_m")):
        b = float(op_cfg[key])
        left_out[col] = (f"roughness at {b:.0f} m needs native cells of at most {b / 3:.0f} m and is built from the "
                         f"native DEM; this fallback works on a 500 m grid (source cell about {dem_cell_m:.0f} m). "
                         "Use the Earth Engine route for roughness")
    return have, left_out


def terrain_features(dem_path: Path | str, window: tuple[int, int, int, int], grid: Grid, op_cfg: dict[str, Any],
                     rows_per_chunk: int = 100) -> tuple[dict[str, np.ndarray], dict[str, str]]:
    """slope_med, slope_p90 and relief on 6 km tiles from a DEM that is at most one slope baseline coarse.
    Uses `operators.tile_features` on a 500 m EPSG:6933 grid made by area averaging, in chunks of tile rows."""
    cell = source_cell_m(dem_path)
    have, left_out = terrain_plan(cell, op_cfg)
    ix0, iy0, ix1, iy1 = window
    out = {c: np.full((iy1 - iy0, ix1 - ix0), np.nan, dtype=np.float32) for c in have}
    if not have:
        return {}, left_out
    base = float(op_cfg["slope_baseline_m"])
    for r0 in range(iy0, iy1, rows_per_chunk):
        r1 = min(r0 + rows_per_chunk, iy1)
        z = resample(dem_path, (ix0, r0, ix1, r1), grid, cell_m=base, margin_m=MARGIN_CELLS * base)
        feats = O.tile_features(z, base, grid.cell_m, grid.cell_m, slope_baseline_m=base, rough_baselines_m=None,
                                margin_m=MARGIN_CELLS * base, kx_rows=ground_scale_rows(grid, r0, r1, base))
        for c in have:
            out[c][r0 - iy0:r1 - iy0] = feats[c]
    return out, left_out


# --------------------------------------------------------------------------- build

def build_rasters(spec: dict[str, Any], op_cfg: dict[str, Any], out_tif: Path | str,
                  bbox_lonlat: tuple[float, float, float, float] | None = None, grid: Grid | None = None) -> dict[str, Any]:
    """spec = {"dem": path or None, "layers": {column: {"file": path, "band": 1, "method": "average"}}}.
    Writes a multiband GeoTIFF (EPSG:6933, 6000 m) and returns a report: bands written, columns left out and why."""
    import rasterio
    grid = grid or Grid()
    win = tile_window(grid, bbox_lonlat)
    ix0, iy0, ix1, iy1 = win
    bands: dict[str, np.ndarray] = {}
    left_out: dict[str, str] = {}
    sources: dict[str, str] = {}
    if spec.get("dem"):
        feats, lo = terrain_features(spec["dem"], win, grid, op_cfg)
        bands.update(feats)
        left_out.update(lo)
        for c in feats:
            sources[c] = f"{Path(spec['dem']).name} (500 m operator, {source_cell_m(spec['dem']):.0f} m source)"
    else:
        for c in TERRAIN_COLUMNS:
            left_out[c] = "no DEM file given"
    for col, lay in (spec.get("layers") or {}).items():
        if col in TERRAIN_COLUMNS:
            raise ValueError(f"{col} is a terrain column: give a `dem`, not a layer, so the one operator is used")
        if not lay or not lay.get("file"):
            left_out[col] = "no file given"
            continue
        bands[col] = resample(lay["file"], win, grid, None, int(lay.get("band", 1)), lay.get("method", "average"))
        sources[col] = Path(lay["file"]).name
    if "land_frac" not in bands:
        raise ValueError("a land_frac layer is required (share of each 6 km cell that is land); "
                         "for example area-average a 0/1 land mask")
    out_tif = Path(out_tif)
    out_tif.parent.mkdir(parents=True, exist_ok=True)
    h, w = iy1 - iy0, ix1 - ix0
    order = ["land_frac"] + [c for c in bands if c != "land_frac"]
    with rasterio.open(out_tif, "w", driver="GTiff", height=h, width=w, count=len(order), dtype="float32",
                       crs=grid.crs, transform=_transform(grid, ix0, iy0, grid.cell_m), nodata=float("nan"),
                       compress="deflate") as ds:
        for i, name in enumerate(order, 1):
            ds.write(bands[name].astype(np.float32), i)
            ds.set_band_description(i, name)
    report = {"raster": str(out_tif), "window_tiles": {"ix0": ix0, "iy0": iy0, "ix1": ix1, "iy1": iy1},
              "bbox_lonlat": bbox_lonlat, "bands": order, "sources": sources, "left_out": left_out,
              "note": "left-out columns are absent from the raster; the missing-data gate rejects tiles that need them"}
    write_json(out_tif.with_name("open_data_report.json"), report)
    return report


def estimate_tiles(bbox_lonlat, grid: Grid | None = None) -> int:
    ix0, iy0, ix1, iy1 = tile_window(grid or Grid(), bbox_lonlat)
    return int(math.prod((ix1 - ix0, iy1 - iy0)))
