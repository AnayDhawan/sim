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
