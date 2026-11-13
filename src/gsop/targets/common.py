"""Target profiles (s2 targets): value, spread, source, evidence grade and window for every column.

Evidence grades: A measured at the target, B nearby or same class, C inference.
Output schema (long parquet, data/processed/targets_<body>.parquet):
  target, col, value, spread, source, evidence_grade, window, unavailable
Rows whose col starts with 'aux_' carry auxiliary values (aux_lat, aux_elevation_m, aux_thermal_inertia_si).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .. import operators as O

SCHEMA = ["target", "col", "value", "spread", "source", "evidence_grade", "window", "unavailable"]


def row(target: str, col: str, value, spread=None, source="", grade="", window="", unavailable=False) -> dict:
    return {"target": target, "col": col, "value": np.nan if value is None else float(value),
            "spread": np.nan if spread is None else float(spread), "source": source, "evidence_grade": grade,
            "window": window, "unavailable": bool(unavailable) or value is None or not np.isfinite(float(value))}


def read_window(path: Path | str, lat: float, lon: float, size_km: float, nodata_as: str = "nan"):
    """Windowed read of a projected raster GeoTIFF centred on (lat, lon). Never reads the full planet.
    Returns (array, cell_m). The raster's own CRS is used, so polar stereographic lunar rasters work.
    Cells outside the raster are always NaN. Cells equal to the file's declared nodata value become NaN for a DEM
    (`nodata_as="nan"`). For a 0/1 mask (`nodata_as="zero"`) a declared nodata of 0 is read as 0: a mask whose nodata is
    0 (a common way to store a mask) must not turn every non-set cell into NaN. Any other declared nodata in a mask
    (-9999, 255, ...) cannot mean 'not set', so those cells stay NaN (missing) and the 90 percent valid rule applies."""
    import rasterio
    from pyproj import CRS, Transformer
    from rasterio.windows import Window
    if nodata_as not in ("nan", "zero"):
        raise ValueError("nodata_as must be 'nan' or 'zero'")
    with rasterio.open(path) as ds:
        geog = CRS.from_user_input(ds.crs).geodetic_crs
        x, y = Transformer.from_crs(geog, ds.crs, always_xy=True).transform(lon, lat)
        r, c = ds.index(x, y)
        cell = abs(ds.transform.a)
        n = int(round(size_km * 1000.0 / cell))
        # Read only the part inside the raster and leave the rest NaN. A boundless read with fill_value=NaN casts the
        # fill to the file's dtype, so on an integer raster (uint8 mask, int16 DEM) off-raster cells came back as 0.
        r_off, c_off = r - n // 2, c - n // 2
        a = np.full((n, n), np.nan)
        r0, c0 = max(r_off, 0), max(c_off, 0)
        r1, c1 = min(r_off + n, ds.height), min(c_off + n, ds.width)
        if r1 > r0 and c1 > c0:
            part = ds.read(1, window=Window(c0, r0, c1 - c0, r1 - r0)).astype(float)
            if ds.nodata is not None:
                part[part == ds.nodata] = 0.0 if (nodata_as == "zero" and ds.nodata == 0) else np.nan
            a[r0 - r_off: r1 - r_off, c0 - c_off: c1 - c_off] = part
    return a, cell


def read_dem_window(path: Path | str, lat: float, lon: float, size_km: float):
    """A DEM window: declared nodata cells are NaN (see `read_window`)."""
    return read_window(path, lat, lon, size_km, "nan")


def central_crop(a: np.ndarray, res_m: float, window_km: float) -> np.ndarray:
    """The central window_km x window_km part of a window that was read with a margin around it."""
    n = int(round(window_km * 1000.0 / res_m))
    if a.shape[0] < n or a.shape[1] < n:
        raise ValueError(f"window {a.shape} is smaller than {window_km:g} km at {res_m:g} m cells")
    cy, cx = a.shape[0] // 2, a.shape[1] // 2
    return a[cy - n // 2: cy - n // 2 + n, cx - n // 2: cx - n // 2 + n]


def mask_share_rows(target: str, col: str, mask: np.ndarray, res_m: float, source: str, grade: str, window_km: float,
                    tile_m: float = 6000.0, stride_m: float = 3000.0, margin_km: float = 1.0) -> list[dict]:
    """Share of each 6 km tile (stride 3 km) inside the target window whose mask cells are non-zero.
    Value = median over the tiles, spread = IQR / 1.349 (same rule as the terrain columns). NaN cells count as 'not set'
    for the share but a tile with fewer than 90 percent valid cells is dropped."""
    sub = central_crop(mask, res_m, window_km)
    t, st = int(round(tile_m / res_m)), int(round(stride_m / res_m))
    if sub.shape[0] < t or sub.shape[1] < t:
        raise ValueError(f"mask window {sub.shape} is smaller than one {tile_m:g} m tile at {res_m:g} m cells")
    v = O._tile_view(sub, t, st)
    flat = v.reshape(v.shape[0], v.shape[1], -1)
    valid = np.isfinite(flat).mean(axis=2)
    share = np.where(valid >= O.MIN_VALID_FRAC, (np.nan_to_num(flat, nan=0.0) > 0).mean(axis=2), np.nan)
    share = share[np.isfinite(share)]
    if share.size == 0:
        return [row(target, col, None, unavailable=True)]
    return [row(target, col, float(np.median(share)), O.spread_from_iqr(share), source, grade,
                f"{window_km:g} km, {share.size} tiles")]


def terrain_rows(target: str, dem: np.ndarray, res_m: float, source: str, grade: str, window_km: float,
                 op_cfg: dict[str, Any]) -> list[dict]:
    prof = O.window_profile(dem, res_m, window_km, op_cfg["tile_m"], op_cfg["stride_m"],
                            slope_baseline_m=op_cfg["slope_baseline_m"],
                            rough_baselines_m=(op_cfg["rough_a_baseline_m"], op_cfg["rough_b_baseline_m"]))
    return [row(target, k, v[0], v[1], source, grade, f"{window_km:g} km, {v[2]} tiles") for k, v in prof.items()]


def write_profile(rows: list[dict], path: Path | str) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=SCHEMA)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df
