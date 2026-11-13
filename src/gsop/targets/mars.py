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


def air_density_kg_m3(h_m: float, atm: dict[str, Any]) -> float:
    """Mars air density from elevation. `atm` is `mars_atmosphere` in config/targets.yaml; `use` picks the model.
    Only the `glenn` model (NASA Glenn, lower atmosphere) can give a density. The choice of source is a pending decision
    (docs/DECISIONS.md E7): the plan's 610 Pa / 11.1 km pair is in no source we found, and NASA's fact sheet (636 Pa, 11.0 km)
    disagrees with Glenn (699 Pa)."""
    use = atm["use"]
    if use != "glenn":
        raise ValueError(f"mars_atmosphere.use = {use!r}: only 'glenn' has a temperature model and can give a density")
    g = atm["glenn"]
    if h_m > g["valid_to_m"]:
        raise ValueError(f"the lower-atmosphere fit is only valid below {g['valid_to_m']} m")
    t = g["t0_c"] - g["t_slope_c_per_m"] * h_m
    p = g["p0_kpa"] * math.exp(-g["scale_per_m"] * h_m)
    return p / (g["gas_const"] * (t + g["kelvin"]))


def build(cfg: dict[str, Any], dem_path: Path | str | None) -> list[dict]:
    rows: list[dict] = []
    for name, t in cfg["targets"]["mars"].items():
        if t.get("lat") is None:
            continue                                       # D10: no coordinates, no profile
        rows.append(C.row(name, "aux_lat", t["lat"], source=t["source"], grade="A"))
        if dem_path:
            dem, cell = C.read_dem_window(dem_path, t["lat"], float(wrap_lon(t["lon_e"])),
                                         cfg["targets"]["target_window_km"] + 2 * cfg["targets"]["read_margin_km"])
            rows += C.terrain_rows(name, dem, cell, f"MOLA ({Path(dem_path).name})", "A",
                                   cfg["targets"]["target_window_km"], cfg["features"]["operator"])
            elev = float(np.nanmedian(C.central_crop(dem, cell, cfg["targets"]["target_window_km"])))   # the 15 km window, not the 17 km read
            rows.append(C.row(name, "aux_elevation_m", elev, source=f"MOLA ({Path(dem_path).name}), median of the window, "
                              "metres above the areoid", grade="A", window=f"{cfg['targets']['target_window_km']:g} km"))
            atm = cfg["targets"]["mars_atmosphere"]
            rows.append(C.row(name, "air_density", air_density_kg_m3(elev, atm), 0.0,
                              f"Mars atmosphere model '{atm['use']}' (config/targets.yaml mars_atmosphere; source choice pending, "
                              "docs/DECISIONS.md E7) applied to the MOLA elevation", "C", "from aux_elevation_m"))
        else:
            rows += [C.row(name, c, None, unavailable=True) for c in
                     ("slope_med", "slope_p90", "relief", "rough_a", "rough_b", "aux_elevation_m", "air_density")]
        rows += [C.row(name, c, None, unavailable=True) for c in UNBUILT]
    return rows
