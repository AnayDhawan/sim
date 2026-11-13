"""Mars target profiles (S's machine). Phase 3.

Built so far: terrain from a MOLA DEM window (give the GeoTIFF path). NOT built, so they stay `unavailable`:
silica_index (TES), water_index (SWIM ice consistency), insol_annual and sun_max_elev (computed), ti_proxy (THEMIS),
dust_index (TES), air_density (exponential law, constants unsourced), t_mean and t_coldest, and the aux values for the
D6 target check (aux_elevation_m, aux_thermal_inertia_si). Arcadia has no centre in our files (D10): it is skipped as
`unscored: no target data` until the centre is taken from the SWIM ice map. Do not guess coordinates.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from ..grid import wrap_lon
from . import common as C

UNBUILT = ["silica_index", "water_index", "insol_annual", "sun_max_elev", "ti_proxy", "dust_index",
           "t_mean", "t_coldest", "aux_thermal_inertia_si"]


def air_density_kg_m3(h_m: float) -> float:
    """NASA Glenn Mars atmosphere model, lower atmosphere (surface to 7,000 m), https://www.grc.nasa.gov/www/k-12/airplane/atmosmrm.html:
    T = -31 - 0.000998 h (C); p = 0.699 exp(-0.00009 h) (kPa); rho = p / (0.1921 (T + 273.1)). A curve fit, not Mars-GRAM.
    The pair 610 Pa / 11.1 km that the plan assumed is in no source we found; NASA's fact sheet gives 636 Pa / 11.0 km.
    Which source to use is a human decision (docs/UNVERIFIED.md)."""
    if h_m > 7000.0:
        raise ValueError("the lower-atmosphere fit is only valid below 7,000 m")
    t = -31.0 - 0.000998 * h_m
    p = 0.699 * math.exp(-0.00009 * h_m)
    return p / (0.1921 * (t + 273.1))


def build(cfg: dict[str, Any], dem_path: Path | str | None) -> list[dict]:
    rows: list[dict] = []
    for name, t in cfg["targets"]["mars"].items():
        if t.get("lat") is None:
            continue                                       # D10: no coordinates, no profile
        rows.append(C.row(name, "aux_lat", t["lat"], source=t["source"], grade="A"))
        if dem_path:
            dem, cell = C.read_dem_window(dem_path, t["lat"], float(wrap_lon(t["lon_e"])), 17.0)
            rows += C.terrain_rows(name, dem, cell, f"MOLA ({Path(dem_path).name})", "A",
                                   cfg["targets"]["target_window_km"], cfg["features"]["operator"])
            elev = float(np.nanmedian(dem))
            rows.append(C.row(name, "aux_elevation_m", elev, source=f"MOLA ({Path(dem_path).name}), median of the window, "
                              "metres above the areoid", grade="A", window=f"{cfg['targets']['target_window_km']:g} km"))
            rows.append(C.row(name, "air_density", air_density_kg_m3(elev), 0.0, "NASA Glenn Mars atmosphere model "
                              "(lower atmosphere) applied to the MOLA elevation", "C", "from aux_elevation_m"))
        else:
            rows += [C.row(name, c, None, unavailable=True) for c in
                     ("slope_med", "slope_p90", "relief", "rough_a", "rough_b", "aux_elevation_m", "air_density")]
        rows += [C.row(name, c, None, unavailable=True) for c in UNBUILT]
    return rows
