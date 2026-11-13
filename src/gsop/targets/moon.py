"""Moon target profiles (Anay's machine). Phase 3.

Built so far: terrain from a LOLA south-polar DEM window (give the GeoTIFF path), and the illumination columns from the
plan's pole rule (Sun within about 1.5 deg of the horizon all year), graded C because it is a rule, not a measurement.
NOT built, so they stay `unavailable` until a verified source is wired in: water_index (PSR share of the tile),
t_mean / t_coldest (Diviner does not reach the pole), silica_index, ti_proxy. Their absence stops a scoring run unless a
human lists them in config/run.yaml drop_columns. Malapert has no data and is left out.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..grid import wrap_lon
from . import common as C

UNBUILT = ["water_index", "t_mean", "t_coldest", "silica_index", "ti_proxy"]


def build(cfg: dict[str, Any], dem_path: Path | str | None) -> list[dict]:
    rows: list[dict] = []
    ill = cfg["targets"]["moon_pole_illumination"]
    for name, t in cfg["targets"]["moon"].items():
        rows.append(C.row(name, "aux_lat", t["lat"], source=t["source"], grade="A"))
        for col in ("sun_max_elev", "sun_low_share"):
            rows.append(C.row(name, col, ill[col], 0.0, "pole illumination rule (config/targets.yaml)",
                              ill["evidence_grade"], "n/a"))
        if dem_path:
            dem, cell = C.read_dem_window(dem_path, t["lat"], float(wrap_lon(t["lon_e"])), 17.0)
            rows += C.terrain_rows(name, dem, cell, f"LOLA ({Path(dem_path).name})", "A",
                                   cfg["targets"]["target_window_km"], cfg["features"]["operator"])
        else:
            rows += [C.row(name, c, None, unavailable=True) for c in ("slope_med", "slope_p90", "relief", "rough_a", "rough_b")]
        rows += [C.row(name, c, None, unavailable=True) for c in UNBUILT]
    return rows
