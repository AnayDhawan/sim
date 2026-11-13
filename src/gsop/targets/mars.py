"""Mars target profiles (S's machine). Phase 3.

Built so far: terrain from a MOLA DEM window (give the GeoTIFF path). NOT built, so they stay `unavailable`:
silica_index (TES), water_index (SWIM ice consistency), insol_annual and sun_max_elev (computed), ti_proxy (THEMIS),
dust_index (TES), air_density (exponential law, constants unsourced), t_mean and t_coldest, and the aux values for the
D6 target check (aux_elevation_m, aux_thermal_inertia_si). Arcadia has no centre in our files (D10): it is skipped as
`unscored: no target data` until the centre is taken from the SWIM ice map. Do not guess coordinates.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..grid import wrap_lon
from . import common as C

UNBUILT = ["silica_index", "water_index", "insol_annual", "sun_max_elev", "ti_proxy", "dust_index", "air_density",
           "t_mean", "t_coldest", "aux_elevation_m", "aux_thermal_inertia_si"]


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
        else:
            rows += [C.row(name, c, None, unavailable=True) for c in ("slope_med", "slope_p90", "relief", "rough_a", "rough_b")]
        rows += [C.row(name, c, None, unavailable=True) for c in UNBUILT]
    return rows
