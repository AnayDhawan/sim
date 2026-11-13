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


def read_dem_window(path: Path | str, lat: float, lon: float, size_km: float):
    """Windowed read of a projected DEM GeoTIFF centred on (lat, lon). Never reads the full planet.
    Returns (array, cell_m). The raster's own CRS is used, so polar stereographic lunar DEMs work."""
    import rasterio
    from pyproj import CRS, Transformer
    from rasterio.windows import Window
    with rasterio.open(path) as ds:
        geog = CRS.from_user_input(ds.crs).geodetic_crs
        x, y = Transformer.from_crs(geog, ds.crs, always_xy=True).transform(lon, lat)
        r, c = ds.index(x, y)
        cell = abs(ds.transform.a)
        n = int(round(size_km * 1000.0 / cell))
        a = ds.read(1, window=Window(c - n // 2, r - n // 2, n, n), boundless=True, fill_value=np.nan).astype(float)
        if ds.nodata is not None:
            a[a == ds.nodata] = np.nan
    return a, cell


def mask_share_rows(target: str, col: str, mask: np.ndarray, res_m: float, source: str, grade: str, window_km: float,
                    tile_m: float = 6000.0, stride_m: float = 3000.0, margin_km: float = 1.0) -> list[dict]:
    """Share of each 6 km tile (stride 3 km) inside the target window whose mask cells are non-zero.
    Value = median over the tiles, spread = IQR / 1.349 (same rule as the terrain columns). NaN cells count as 'not set'
    for the share but a tile with fewer than 90 percent valid cells is dropped."""
    n = int(round((window_km * 1000.0) / res_m))
    cy, cx = mask.shape[0] // 2, mask.shape[1] // 2
    sub = mask[cy - n // 2: cy - n // 2 + n, cx - n // 2: cx - n // 2 + n]
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
