"""Terrain operators. ONE definition, used for Earth, Moon and Mars (ground rule 4).

Pipeline for a DEM with square cells of `res_m` metres:
  1. slope baseline: block-mean resample to `slope_baseline_m` (default 500 m);
  2. slope: Horn 3x3 on the resampled grid, degrees;
  3. tile reduction (tile_m, stride_m): slope_med, slope_p90 (percentiles of the slope cells in the tile),
     relief = max - min of the resampled elevation cells in the tile;
  4. roughness at baseline b: split the native DEM into b x b windows, fit and remove a plane, take the RMS
     residual per window; the tile value is the median window RMS inside the tile.
A window with any NaN input gives NaN. Tile reductions ignore NaN cells but return NaN when fewer than
MIN_VALID_FRAC (0.9) of the cells are valid. Nothing is ever filled.
Earth Engine must implement the same steps; `gsop check-operators` compares the two.
"""

from __future__ import annotations

import warnings

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view


def block_mean(a: np.ndarray, f: int) -> np.ndarray:
    """Mean over non-overlapping f x f blocks; edges that do not fill a block are cropped. NaN propagates."""
    if f == 1:
        return a.astype(np.float64)
    ny, nx = (a.shape[0] // f) * f, (a.shape[1] // f) * f
    b = a[:ny, :nx].astype(np.float64).reshape(ny // f, f, nx // f, f)
    return b.mean(axis=(1, 3))


def slope_deg(z: np.ndarray, cell_m: float) -> np.ndarray:
    """Horn 3x3 slope in degrees. Border cells are NaN. NaN neighbours give NaN."""
    z = np.asarray(z, dtype=np.float64)
    out = np.full(z.shape, np.nan)
    if z.shape[0] < 3 or z.shape[1] < 3:
        return out
    a, b, c = z[:-2, :-2], z[:-2, 1:-1], z[:-2, 2:]
    d, f = z[1:-1, :-2], z[1:-1, 2:]
    g, h, i = z[2:, :-2], z[2:, 1:-1], z[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * cell_m)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8 * cell_m)
    out[1:-1, 1:-1] = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    return out


def _tile_view(a: np.ndarray, tile: int, stride: int) -> np.ndarray:
    """(ty, tx, tile, tile) view of tiles of side `tile` cells, stepping `stride` cells."""
    if a.shape[0] < tile or a.shape[1] < tile:
        return np.empty((0, 0, tile, tile))
    return sliding_window_view(a, (tile, tile))[::stride, ::stride]


def plane_rms(z: np.ndarray, k: int) -> np.ndarray:
    """RMS residual after plane removal in non-overlapping k x k windows. NaN window -> NaN."""
    ny, nx = (z.shape[0] // k) * k, (z.shape[1] // k) * k
    w = z[:ny, :nx].astype(np.float64).reshape(ny // k, k, nx // k, k).transpose(0, 2, 1, 3)  # (wy, wx, k, k)
    idx = np.arange(k, dtype=np.float64) - (k - 1) / 2.0
    xx = idx[None, :]
    yy = idx[:, None]
    mean = w.mean(axis=(2, 3), keepdims=True)
    r = w - mean
    sxx = (np.broadcast_to(xx, (k, k)) ** 2).sum()
    bx = (r * xx).sum(axis=(2, 3), keepdims=True) / sxx
    by = (r * yy).sum(axis=(2, 3), keepdims=True) / sxx
    res = r - bx * xx - by * yy
    return np.sqrt((res ** 2).mean(axis=(2, 3)))


MIN_VALID_FRAC = 0.9


def _nanstat(v: np.ndarray, fn) -> np.ndarray:
    """Apply a NaN-aware fn over the tile cells. A tile with fewer than MIN_VALID_FRAC valid cells is NaN.
    The slope grid has a NaN border ring (Horn needs 8 neighbours), which costs an edge tile under 10% of its cells."""
    flat = v.reshape(v.shape[0], v.shape[1], -1)
    valid = np.isfinite(flat).mean(axis=2) if flat.size else np.zeros(flat.shape[:2])
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        out = fn(flat)
    return np.where(valid >= MIN_VALID_FRAC, out, np.nan)


def tile_features(dem: np.ndarray, res_m: float, tile_m: float = 6000.0, stride_m: float | None = None,
                  slope_baseline_m: float = 500.0, rough_baselines_m: tuple[float, float] = (100.0, 1000.0),
                  margin_m: float = 0.0) -> dict[str, np.ndarray]:
    """Terrain features on a grid of tiles. stride_m defaults to tile_m (non-overlapping).
    margin_m: the DEM extends this far beyond the tile area on every side (a multiple of the slope baseline).
    Slope needs one neighbouring cell, so a margin of one baseline gives valid slope up to the tile edge."""
    stride_m = tile_m if stride_m is None else stride_m
    f = slope_baseline_m / res_m
    if abs(f - round(f)) > 1e-9 or f < 1:
        raise ValueError(f"slope baseline {slope_baseline_m} m is not a whole multiple of the DEM cell {res_m} m")
    z = block_mean(dem, int(round(f)))
    s = slope_deg(z, slope_baseline_m)
    mc = margin_m / slope_baseline_m
    if abs(mc - round(mc)) > 1e-9:
        raise ValueError("margin must be a whole multiple of the slope baseline")
    mc = int(round(mc))
    if mc:
        z, s = z[mc:-mc, mc:-mc], s[mc:-mc, mc:-mc]
        dem = dem[int(round(margin_m / res_m)):-int(round(margin_m / res_m)),
                  int(round(margin_m / res_m)):-int(round(margin_m / res_m))]
    t_cells = tile_m / slope_baseline_m
    st_cells = stride_m / slope_baseline_m
    if abs(t_cells - round(t_cells)) > 1e-9 or abs(st_cells - round(st_cells)) > 1e-9:
        raise ValueError("tile and stride must be whole multiples of the slope baseline")
    t_cells, st_cells = int(round(t_cells)), int(round(st_cells))
    out = {
        "slope_med": _nanstat(_tile_view(s, t_cells, st_cells), lambda a: np.nanmedian(a, axis=2)),
        "slope_p90": _nanstat(_tile_view(s, t_cells, st_cells), lambda a: np.nanpercentile(a, 90, axis=2)),
        "relief": _nanstat(_tile_view(z, t_cells, st_cells), lambda a: np.nanmax(a, axis=2) - np.nanmin(a, axis=2)),
    }
    for name, b in zip(("rough_a", "rough_b"), rough_baselines_m):
        k = b / res_m
        if abs(k - round(k)) > 1e-9 or k < 3:
            raise ValueError(f"{name} baseline {b} m needs a DEM cell of at most {b / 3:.0f} m (got {res_m} m)")
        r = plane_rms(dem, int(round(k)))
        tc, sc = tile_m / b, stride_m / b
        if abs(tc - round(tc)) > 1e-9 or abs(sc - round(sc)) > 1e-9:
            raise ValueError(f"tile and stride must be whole multiples of the {name} baseline")
        out[name] = _nanstat(_tile_view(r, int(round(tc)), int(round(sc))), lambda a: np.nanmedian(a, axis=2))
    return out


def spread_from_iqr(v: np.ndarray) -> float:
    q75, q25 = np.nanpercentile(v, [75, 25])
    return float((q75 - q25) / 1.349)


def window_profile(dem: np.ndarray, res_m: float, window_km: float = 15.0, tile_m: float = 6000.0,
                   stride_m: float = 3000.0, **kw) -> dict[str, tuple[float, float, int]]:
    """Target profile: terrain features on 6 km tiles (stride 3 km) inside the window.
    Returns {column: (median, spread = IQR/1.349, n_tiles)}."""
    margin_m = float(kw.get("slope_baseline_m", 500.0))   # one slope-baseline cell of context on every side
    n = int(round((window_km * 1000.0 + 2 * margin_m) / res_m))
    cy, cx = dem.shape[0] // 2, dem.shape[1] // 2
    if dem.shape[0] < n or dem.shape[1] < n:
        raise ValueError(f"DEM is {dem.shape}, need at least {n} x {n} cells for a {window_km} km window plus margin")
    sub = dem[cy - n // 2: cy - n // 2 + n, cx - n // 2: cx - n // 2 + n]
    feats = tile_features(sub, res_m, tile_m, stride_m, margin_m=margin_m, **kw)
    out = {}
    for k, v in feats.items():
        v = v[np.isfinite(v)]
        out[k] = (float(np.median(v)), spread_from_iqr(v), int(v.size)) if v.size else (float("nan"), float("nan"), 0)
    return out
