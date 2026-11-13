"""Earth Engine implementation of the terrain operator in `gsop.operators` (issues #1 and #2).

STATUS: the Earth Engine calls here were written without a login and have been corrected against the failures Anay hit on a
real Lonar box (PR 13 review, 2026-11-13). They have NOT been re-run since. What is tested offline is the maths: the Horn
kernels and the roughness moment formulas are mirrored in numpy below and checked against `gsop.operators`
(tests/test_gee_operators_math.py). `gsop check-operators` runs both implementations on one real window and prints the
difference; run it before any global export.

How each step of `operators.tile_features` is expressed in Earth Engine:

  numpy                                         Earth Engine
  --------------------------------------------  ------------------------------------------------------------------
  block-mean the DEM to the slope baseline      reduceResolution(mean), then reproject to the tile-aligned baseline grid
  Horn 3x3 slope on that grid                   convolve with the two Horn kernels below (NOT ee.Terrain.slope, which
                                                uses a different, 4-neighbour stencil)
  ground scale kx = cos(lat) / cos(30 deg)      cos of pixelLonLat latitude. EPSG:6933 is cylindrical equal-area, so a
                                                projected cell is base*kx m east-west and base/kx m north-south
  slope_med, slope_p90 over the cells of a      reduceResolution(percentile 50 / 90) to 6 km, maxRaw large enough that the
  tile                                          percentile comes from raw values, not a histogram
  relief = max - min of the baseline cells      reduceResolution(max) minus reduceResolution(min)
  roughness: plane removal in b x b windows     block moments of d = z - window mean: E[d^2], E[d xi], E[d yi]; xi, yi are
                                                centred pixel indices; RMS = sqrt(E[d^2] - (E[d xi]^2 + E[d yi]^2) / S)
  tile value = median window RMS                reduceResolution(median)
  tile with < 90 % valid cells = NaN            reduceResolution(count) < MIN_VALID_FRAC * cells -> masked

Earth Engine facts that this file depends on (reported by Anay after a real run):
  * the CRS must be a WKT1_GDAL string; "EPSG:6933" and the default WKT2 both fail ("CRS of a map projection could not be
    parsed"). `ee_crs()` builds it.
  * reduceResolution needs a default projection on any image made by a collection reducer (mean, median, mosaic, blend):
    call `setDefaultProjection` first.
  * images made with `.map(...)` lose `system:time_start`: copyProperties before calendarRange.
  * reduceResolution(maxPixels) must cover the cell ratio (100 m into a 6 km tile needs 3,600).
  * mean(z^2) - mean(z)^2 on raw elevations cancels to exactly 0 in float32. Each window's own mean is subtracted first.

Known places where the two sides can differ (reported by `gsop check-operators`, not hidden):
  * percentile interpolation: numpy interpolates linearly, Earth Engine picks an order statistic;
  * the DEM is resampled bilinearly onto the working grid before either side computes anything; both sides use the SAME
    resampled surface in the check;
  * rough_a (100 m) needs a whole number of cells: 100 / 25 = 4 works, 100 / 30 does not, so the check grid is 25 m.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from ..operators import MIN_VALID_FRAC

# Horn 3x3 stencil. dz/dx = sum(KX * z) / (8 * dx), dz/dy = sum(KY * z) / (8 * dy), rows run north to south.
HORN_KX = [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]]
HORN_KY = [[-1, -2, -1], [0, 0, 0], [1, 2, 1]]
MAX_PIXELS = 1 << 16                 # generous: covers every cell ratio used here (the largest is 240 x 240 = 57,600)


@lru_cache(maxsize=None)
def ee_crs(epsg: int = 6933) -> str:
    """The WKT1_GDAL string Earth Engine accepts for a projection. "EPSG:6933" and WKT2 are rejected by Earth Engine."""
    from pyproj import CRS
    return CRS.from_epsg(epsg).to_wkt(version="WKT1_GDAL")


# --------------------------------------------------------------------------- numpy mirrors (tested offline)

def horn_slope_mirror(z: np.ndarray, cell_m: float, kx_rows: np.ndarray) -> np.ndarray:
    """The slope the Earth Engine expression computes, written in numpy with scipy correlation and the same kernels.
    Must equal operators.slope_deg(z, cell_m, kx_rows) on interior cells."""
    from scipy.ndimage import correlate
    z = np.asarray(z, dtype=np.float64)
    gx = correlate(z, np.array(HORN_KX, dtype=float), mode="constant", cval=np.nan)
    gy = correlate(z, np.array(HORN_KY, dtype=float), mode="constant", cval=np.nan)
    k = np.asarray(kx_rows, dtype=np.float64).reshape(-1, 1)
    dzdx = gx / (8.0 * cell_m * k)
    dzdy = gy / (8.0 * cell_m / k)
    out = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    out[0, :] = out[-1, :] = np.nan
    out[:, 0] = out[:, -1] = np.nan
    return out


def plane_rms_from_moments(z: np.ndarray, k: int, dtype=np.float64) -> np.ndarray:
    """RMS residual after plane removal in non-overlapping k x k windows, from block moments only (the form
    reduceResolution can compute). Each window's own mean is subtracted first, which is what keeps float32 exact enough:
    the raw form E[z^2] - E[z]^2 cancels to 0 on elevations of a few hundred metres. Must equal operators.plane_rms."""
    ny, nx = (z.shape[0] // k) * k, (z.shape[1] // k) * k
    w = z[:ny, :nx].astype(dtype).reshape(ny // k, k, nx // k, k).transpose(0, 2, 1, 3)
    idx = (np.arange(k) - (k - 1) / 2.0).astype(dtype)
    xi, yi = np.broadcast_to(idx[None, :], (k, k)), np.broadcast_to(idx[:, None], (k, k))
    s = dtype((xi.astype(np.float64) ** 2).mean())                         # E[xi^2] = (k^2 - 1) / 12, equal for yi
    d = w - w.mean(axis=(2, 3), keepdims=True)
    edd = (d * d).mean(axis=(2, 3))
    edx = (d * xi).mean(axis=(2, 3))
    edy = (d * yi).mean(axis=(2, 3))
    var = edd - (edx ** 2 + edy ** 2) / s
    return np.sqrt(np.maximum(var, 0)).astype(np.float64)


def kx_from_lat(lat_deg):
    return np.cos(np.radians(lat_deg)) / math.cos(math.radians(30.0))


# --------------------------------------------------------------------------- Earth Engine (not re-run since the review)

def tile_transform(grid, ix0: int, iy0: int, cell_m: float) -> list[float]:
    """crsTransform [xScale, 0, xTranslate, 0, -yScale, yTranslate] of a grid aligned to tile (ix0, iy0)."""
    return [cell_m, 0, grid.x0 + ix0 * grid.cell_m, 0, -cell_m, grid.y_top - iy0 * grid.cell_m]


def reduce_to(img, reducer, grid, ix0: int, iy0: int, cell_m: float | None = None, ref_proj=None):
    """Reduce an image to a coarser tile-aligned grid. `ref_proj` sets the default projection first, which Earth Engine
    requires for images made by collection reducers."""
    if ref_proj is not None:
        img = img.setDefaultProjection(ref_proj)
    return img.reduceResolution(reducer=reducer, bestEffort=False, maxPixels=MAX_PIXELS).reproject(
        crs=ee_crs(), crsTransform=tile_transform(grid, ix0, iy0, cell_m or grid.cell_m))


def ee_work_dem(dem, grid, window, ee, work_cell_m: float):
    """The DEM resampled bilinearly onto the working EPSG:6933 grid aligned to the window's first tile. The numpy side
    of `check-operators` downloads exactly this surface, so both sides start from the same numbers."""
    ix0, iy0, _, _ = window
    return dem.resample("bilinear").reproject(crs=ee_crs(), crsTransform=tile_transform(grid, ix0, iy0, work_cell_m))


def ee_horn_slope(z_base, ee, base_m: float):
    """Slope image (degrees) from an elevation image on the EPSG:6933 tile-aligned grid with cells of `base_m` metres
    (the slope baseline from config/features.yaml)."""
    kxk = ee.Kernel.fixed(3, 3, HORN_KX, normalize=False)
    kyk = ee.Kernel.fixed(3, 3, HORN_KY, normalize=False)
    lat = ee.Image.pixelLonLat().select("latitude")
    kx = lat.multiply(math.pi / 180).cos().divide(math.cos(math.radians(30.0)))
    dzdx = z_base.convolve(kxk).divide(kx.multiply(8 * base_m))
    dzdy = z_base.convolve(kyk).multiply(kx).divide(8 * base_m)
    return dzdx.hypot(dzdy).atan().multiply(180 / math.pi).rename("slope")


def ee_roughness(zw, grid, window, ee, b_m: float, work_cell_m: float):
    """RMS height after plane removal in b x b windows, median per 6 km tile (see the table in the module docstring)."""
    ix0, iy0, _, _ = window
    k = int(round(b_m / work_cell_m))
    if abs(b_m / work_cell_m - k) > 1e-9 or k < 3:
        raise ValueError(f"baseline {b_m} m is not a whole number (>= 3) of {work_cell_m} m cells")
    proj = zw.projection()
    px = ee.Image.pixelCoordinates(proj)
    xi = px.select("x").mod(k).subtract((k - 1) / 2.0)
    yi = px.select("y").mod(k).subtract((k - 1) / 2.0)
    s = (k * k - 1) / 12.0
    mean = ee.Reducer.mean()
    wmean = reduce_to(zw, mean, grid, ix0, iy0, b_m)                      # window mean on the b grid
    d = zw.subtract(wmean)                                               # each window's own mean removed first
    blk = lambda im: reduce_to(im, mean, grid, ix0, iy0, b_m)            # noqa: E731
    edd, edx, edy = blk(d.multiply(d)), blk(d.multiply(xi)), blk(d.multiply(yi))
    var = edd.subtract(edx.pow(2).add(edy.pow(2)).divide(s)).max(0)
    return reduce_to(var.sqrt(), ee.Reducer.median(), grid, ix0, iy0).rename("rough")


def ee_tile_terrain(dem, grid, window, ee, work_cell_m: float, slope_baseline_m: float, rough_baselines_m):
    """Image with bands slope_med, slope_p90, relief, rough_a, rough_b on the 6 km tile grid of `window`
    (ix0, iy0, ix1, iy1). `dem` is an ee.Image in metres. All sizes come from config/features.yaml `operator`."""
    ix0, iy0, _, _ = window
    zw = ee_work_dem(dem, grid, window, ee, work_cell_m)
    base = float(slope_baseline_m)
    cells = int(round(grid.cell_m / base))
    z_base = reduce_to(zw, ee.Reducer.mean(), grid, ix0, iy0, base)
    slope = ee_horn_slope(z_base, ee, base)
    valid_min = MIN_VALID_FRAC * cells * cells
    p = ee.Reducer.percentile([50, 90], maxBuckets=256, minBucketWidth=1e-9, maxRaw=cells * cells + 1)
    sp = reduce_to(slope, p, grid, ix0, iy0)
    out = [sp.select("slope_p50").rename("slope_med"), sp.select("slope_p90").rename("slope_p90"),
           reduce_to(z_base, ee.Reducer.max(), grid, ix0, iy0).subtract(
               reduce_to(z_base, ee.Reducer.min(), grid, ix0, iy0)).rename("relief")]
    for name, b in zip(("rough_a", "rough_b"), rough_baselines_m):
        out.append(ee_roughness(zw, grid, window, ee, float(b), work_cell_m).rename(name))
    ok = (reduce_to(slope, ee.Reducer.count(), grid, ix0, iy0).gte(valid_min)
          .And(reduce_to(z_base, ee.Reducer.count(), grid, ix0, iy0).gte(valid_min)))
    return ee.Image.cat(out).updateMask(ok)
