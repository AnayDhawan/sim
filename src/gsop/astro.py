"""Columns computed locally for Earth tiles, never exported from Earth Engine.

  sun_max_elev, sun_low_share, insol_annual   from tile latitude only, with earth/solar.py (the same code the Mars target
                                              profiles use, so the units agree: insol_annual is W/m2, S0 from config)
  air_density                                 from elev_mean with the Earth standard atmosphere in config/features.yaml
                                              `earth_atmosphere` (NASA Glenn troposphere model, the formula of
                                              gee_export_layers.air_density_band; heights below 0 m are taken as 0 m)

History: phase2-gee had its own sun code here (insol_annual dimensionless) and the ISA density formula. The integrate
branch uses solar.py and the configured atmosphere instead, so Earth and Mars columns are computed one way (DECISIONS E26).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def earth_air_density(elev_m, atm: dict[str, Any]) -> np.ndarray:
    """kg/m3. T = t0 - lapse h; p = p0 ((T + K) / t_ref) ** exponent; rho = p / (R (T + K)). h clipped to [0, valid_to_m]."""
    h = np.clip(np.asarray(elev_m, dtype=np.float64), 0.0, float(atm["valid_to_m"]))
    t = atm["t0_c"] - atm["lapse_c_per_m"] * h
    tk = t + atm["kelvin"]
    p = atm["p0_kpa"] * (tk / atm["t_ref_k"]) ** atm["exponent"]
    return p / (atm["gas_const"] * tk)


def add_earth_derived(df: pd.DataFrame, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
    """Adds sun_max_elev, sun_low_share, insol_annual (from lat) and air_density (from elev_mean, NaN where elev_mean is
    NaN). `cfg` is the `features` config. A column the table already has is never overwritten."""
    from .earth.solar import sun_features

    if cfg is None:
        from .config import load_all
        cfg = load_all()["features"]
    df = df.copy()
    for k, v in sun_features(df["lat"].to_numpy(), cfg).items():
        if k not in df.columns:
            df[k] = np.asarray(v, dtype=np.float32)
    if "elev_mean" in df.columns and "air_density" not in df.columns:
        e = df["elev_mean"].to_numpy(dtype=np.float64)
        rho = earth_air_density(np.nan_to_num(e), cfg["earth_atmosphere"])
        df["air_density"] = np.where(np.isfinite(e), rho, np.nan).astype(np.float32)
    return df
