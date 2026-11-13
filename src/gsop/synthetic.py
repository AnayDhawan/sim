"""Synthetic Earth tiles and targets for tests and the golden slice. Not real data. Never used by `gsop run`."""

from __future__ import annotations

import numpy as np
import pandas as pd

ALL_COLUMNS = ["slope_med", "slope_p90", "relief", "rough_a", "rough_b", "sun_max_elev", "sun_low_share",
               "insol_annual", "t_mean", "t_coldest", "ti_proxy", "dust_index", "water_index", "silica_index",
               "air_density"]


def make_earth(n: int, seed: int = 7, columns: list[str] | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    cols = columns or ALL_COLUMNS
    base = {
        "slope_med": rng.gamma(2.0, 2.0, n), "relief": rng.gamma(2.0, 120.0, n),
        "rough_a": rng.gamma(2.0, 0.3, n), "rough_b": rng.gamma(2.0, 3.0, n),
        "sun_max_elev": rng.uniform(20, 90, n), "sun_low_share": rng.uniform(0.0, 0.5, n),
        "insol_annual": rng.uniform(100, 350, n), "t_mean": rng.normal(285, 12, n),
        "t_coldest": rng.normal(265, 15, n), "ti_proxy": rng.gamma(4.0, 5.0, n),
        "dust_index": rng.uniform(0, 1, n), "water_index": rng.uniform(0, 1, n),
        "silica_index": rng.normal(1.0, 0.1, n), "air_density": rng.uniform(0.7, 1.3, n),
    }
    base["slope_p90"] = base["slope_med"] * rng.uniform(1.6, 2.4, n)
    df = pd.DataFrame({c: base[c].astype(np.float64) for c in cols if c in base})
    df.insert(0, "tile_id", np.arange(n, dtype=np.int64))
    df.insert(1, "ix", (np.arange(n) % 100).astype(np.int64))
    df.insert(2, "iy", (np.arange(n) // 100).astype(np.int64))
    df.insert(3, "lon", rng.uniform(-179, 179, n))
    df.insert(4, "lat", rng.uniform(-60, 70, n))
    df["water_ice_frac"] = np.where(rng.random(n) < 0.08, rng.uniform(0.5, 1.0, n), rng.uniform(0, 0.2, n))
    df["ndvi_median"] = np.where(rng.random(n) < 0.3, rng.uniform(0.2, 0.8, n), rng.uniform(-0.05, 0.2, n))
    df["built_crop_frac"] = np.where(rng.random(n) < 0.1, rng.uniform(0.2, 1.0, n), rng.uniform(0, 0.15, n))
    return df


def plant(df: pd.DataFrame, row: int, values: dict[str, float]) -> pd.DataFrame:
    """Make tile `row` exactly equal to `values` and a clean land tile."""
    df = df.copy()
    for c, v in values.items():
        df.loc[row, c] = v
    df.loc[row, ["water_ice_frac", "ndvi_median", "built_crop_frac"]] = [0.0, 0.05, 0.0]
    return df


def target_profile(values: dict[str, float], spread: float = 0.0, aux: dict | None = None) -> dict:
    return {"cols": {c: {"value": float(v), "spread": spread, "source": "synthetic", "evidence_grade": "C",
                         "window": "synthetic"} for c, v in values.items()},
            "aux": aux or {}, "unavailable": []}
