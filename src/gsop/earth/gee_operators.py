"""Earth Engine implementation of the terrain operator in `gsop.operators` (issues #1 and #2).

STATUS: the Earth Engine calls in this file have NOT been run. Earth Engine needs a login and a Cloud project id that only
Anay has (`earthengine authenticate`); nothing here works around that. What IS tested offline is the maths: the moment
formulas used for roughness and the Horn kernels are mirrored in numpy below and checked against `gsop.operators`
(tests/test_gee_operators_math.py). `gsop check-operators` runs both implementations on one real window and prints the
difference; run it before any global export.

How each step of `operators.tile_features` is expressed in Earth Engine:

  numpy                                         Earth Engine
  --------------------------------------------  ------------------------------------------------------------------
  block-mean the DEM to 500 m                   reduceResolution(mean), then reproject to the 500 m tile-aligned grid
  Horn 3x3 slope on that grid                   convolve with the two Horn kernels below (NOT ee.Terrain.slope, which
                                                uses a different, 4-neighbour stencil)
  ground scale kx = cos(lat) / cos(30 deg)      cos of pixelLonLat latitude. EPSG:6933 is cylindrical equal-area, so a
                                                projected cell is 500*kx m east-west and 500/kx m north-south
  slope_med, slope_p90 over the 12x12 cells     reduceResolution(percentile 50 / 90) to 6 km, with maxRaw >= 144 so the
  of a tile                                     percentile is computed from the raw values, not a histogram
  relief = max - min of the 500 m cells         reduceResolution(max) minus reduceResolution(min)
  roughness: plane removal in b x b windows     block moments of z, z^2, z*xi, z*yi (xi, yi centred pixel indices);
                                                RMS = sqrt(E[z^2] - E[z]^2 - (E[z xi]^2 + E[z yi]^2) / S), S = E[xi^2]
  tile value = median window RMS                reduceResolution(median)
  tile with fewer than 90 % valid cells = NaN   reduceResolution(count) < 0.9 * cells -> masked

Known places where the two can differ (reported by `gsop check-operators`, not hidden):
  * percentile interpolation: numpy interpolates linearly, Earth Engine picks an order statistic;
  * the DEM is resampled onto the working grid (bilinear) before either side computes anything, so the 30 m NASADEM
    and a 25 m EPSG:6933 grid are not the same surface. Both sides use the SAME resampled surface in the check.
  * rough_a (100 m) needs a whole number of cells: 100 / 25 = 4 works, 100 / 30 does not, so the check grid is 25 m.
"""

from __future__ import annotations

import math

import numpy as np

# Horn 3x3 stencil. dz/dx = sum(KX * z) / (8 * dx), dz/dy = sum(KY * z) / (8 * dy), rows run north to south.
HORN_KX = [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]]
HORN_KY = [[-1, -2, -1], [0, 0, 0], [1, 2, 1]]
MIN_VALID_FRAC = 0.9


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


def plane_rms_from_moments(z: np.ndarray, k: int) -> np.ndarray:
    """RMS residual after plane removal in non-overlapping k x k windows, from block moments only (the form that
    reduceResolution can compute). Must equal operators.plane_rms."""
    ny, nx = (z.shape[0] // k) * k, (z.shape[1] // k) * k
    w = z[:ny, :nx].astype(np.float64).reshape(ny // k, k, nx // k, k).transpose(0, 2, 1, 3)
    idx = np.arange(k, dtype=np.float64) - (k - 1) / 2.0
    xi, yi = np.broadcast_to(idx[None, :], (k, k)), np.broadcast_to(idx[:, None], (k, k))
    s = float((xi ** 2).mean())                              # E[xi^2] = (k^2 - 1) / 12, equal for yi
    m = w.mean(axis=(2, 3))
    ezz = (w * w).mean(axis=(2, 3))
    ezx = (w * xi).mean(axis=(2, 3))
    ezy = (w * yi).mean(axis=(2, 3))
    var = ezz - m * m - (ezx ** 2 + ezy ** 2) / s
    return np.sqrt(np.maximum(var, 0.0))


def kx_from_lat(lat_deg):
    return np.cos(np.radians(lat_deg)) / math.cos(math.radians(30.0))


# --------------------------------------------------------------------------- Earth Engine (not run in this repo yet)

def tile_transform(grid, ix0: int, iy0: int, cell_m: float) -> list[float]:
    """crsTransform [xScale, 0, xTranslate, 0, -yScale, yTranslate] of a grid aligned to tile (ix0, iy0)."""
    return [cell_m, 0, grid.x0 + ix0 * grid.cell_m, 0, -cell_m, grid.y_top - iy0 * grid.cell_m]


def ee_work_dem(dem, grid, window, ee, work_cell_m: float = 25.0):
    """The DEM resampled bilinearly onto the working EPSG:6933 grid aligned to the window's first tile. The numpy side
    of `check-operators` downloads exactly this surface, so both sides start from the same numbers."""
    ix0, iy0, _, _ = window
    return dem.resample("bilinear").reproject(crs=grid.crs, crsTransform=tile_transform(grid, ix0, iy0, work_cell_m))


def ee_horn_slope(z500, ee):
    """Slope image (degrees) from a 500 m elevation image on the EPSG:6933 tile-aligned grid."""
    kxk = ee.Kernel.fixed(3, 3, HORN_KX, normalize=False)
    kyk = ee.Kernel.fixed(3, 3, HORN_KY, normalize=False)
    lat = ee.Image.pixelLonLat().select("latitude")
    kx = lat.multiply(math.pi / 180).cos().divide(math.cos(math.radians(30.0)))
    base = 500.0
    dzdx = z500.convolve(kxk).divide(kx.multiply(8 * base))
    dzdy = z500.convolve(kyk).multiply(kx).divide(8 * base)
    return dzdx.hypot(dzdy).atan().multiply(180 / math.pi).rename("slope")


def _to_tiles(img, reducer, grid, ix0, iy0, nx, ny, ee, max_pixels=4096):
    """Reduce an image on a fine grid to the 6 km tile grid of the window."""
    return (img.reduceResolution(reducer=reducer, bestEffort=False, maxPixels=max_pixels)
            .reproject(crs=grid.crs, crsTransform=tile_transform(grid, ix0, iy0, grid.cell_m)))


def ee_tile_terrain(dem, grid, window, ee, work_cell_m: float = 25.0, slope_baseline_m: float = 500.0,
                    rough_baselines_m=(100.0, 1000.0)):
    """Image with bands slope_med, slope_p90, relief, rough_a, rough_b on the 6 km tile grid of `window`
    (ix0, iy0, ix1, iy1). `dem` is an ee.Image in metres. The DEM is first resampled bilinearly onto a `work_cell_m`
    EPSG:6933 grid aligned to the tiles; both the Earth Engine and the numpy side must use that same surface."""
    ix0, iy0, ix1, iy1 = window
    nx, ny = ix1 - ix0, iy1 - iy0
    cells500 = int(round(grid.cell_m / slope_baseline_m))                      # 12
    zw = ee_work_dem(dem, grid, window, ee, work_cell_m)
    p = ee.Reducer.percentile([50, 90], maxBuckets=256, minBucketWidth=1e-9, maxRaw=256)
    z500 = zw.reduceResolution(ee.Reducer.mean(), bestEffort=False, maxPixels=4096).reproject(
        crs=grid.crs, crsTransform=tile_transform(grid, ix0, iy0, slope_baseline_m))
    slope = ee_horn_slope(z500, ee)
    valid_min = MIN_VALID_FRAC * cells500 * cells500

    def tiles(img, reducer):
        return _to_tiles(img, reducer, grid, ix0, iy0, nx, ny, ee)

    cnt_s = tiles(slope, ee.Reducer.count())
    sp = tiles(slope, p)
    out = [sp.select("slope_p50").rename("slope_med"), sp.select("slope_p90").rename("slope_p90"),
           tiles(z500, ee.Reducer.max()).subtract(tiles(z500, ee.Reducer.min())).rename("relief")]
    cnt_z = tiles(z500, ee.Reducer.count())
    for name, b in zip(("rough_a", "rough_b"), rough_baselines_m):
        k = int(round(b / work_cell_m))
        if abs(b / work_cell_m - k) > 1e-9 or k < 3:
            raise ValueError(f"{name}: baseline {b} m is not a whole number (>= 3) of {work_cell_m} m cells")
        px = ee.Image.pixelCoordinates(zw.projection())
        xi = px.select("x").mod(k).subtract((k - 1) / 2.0)
        yi = px.select("y").mod(k).subtract((k - 1) / 2.0)
        s = (k * k - 1) / 12.0
        mean = ee.Reducer.mean()
        blk = lambda im: im.reduceResolution(mean, bestEffort=False, maxPixels=4096 * 4).reproject(  # noqa: E731
            crs=grid.crs, crsTransform=tile_transform(grid, ix0, iy0, b))
        m, ezz = blk(zw), blk(zw.multiply(zw))
        ezx, ezy = blk(zw.multiply(xi)), blk(zw.multiply(yi))
        var = ezz.subtract(m.multiply(m)).subtract(ezx.pow(2).add(ezy.pow(2)).divide(s)).max(0)
        rms = var.sqrt()
        out.append(rms.reduceResolution(ee.Reducer.median(), bestEffort=False, maxPixels=4096).reproject(
            crs=grid.crs, crsTransform=tile_transform(grid, ix0, iy0, grid.cell_m)).rename(name))
    img = ee.Image.cat(out)
    ok = cnt_s.select(0).gte(valid_min).And(cnt_z.select(0).gte(valid_min))
    return img.updateMask(ok)
