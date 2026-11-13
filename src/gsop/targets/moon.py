"""Moon target profiles (Anay's machine). Phase 3.

Built so far: terrain from a LOLA south-polar DEM window (give the GeoTIFF path), water_index as the PSR share of the tile
(give a PSR raster path with --psr), and the illumination columns from the
plan's pole rule (Sun within about 1.5 deg of the horizon all year), graded C because it is a rule, not a measurement.
NOT built, so they stay `unavailable` until a verified source is wired in: t_mean / t_coldest / ti_proxy (Diviner polar
products, see the note below) and silica_index (no source reaches the pole). Their absence stops a scoring run unless a
human lists them in config/run.yaml drop_columns. Malapert has no data and is left out.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..grid import wrap_lon
from . import common as C

UNBUILT = ["t_mean", "t_coldest", "silica_index", "ti_proxy"]
# Sources checked on 2026-11-13 (docs/PROVENANCE.md), none of them wired yet:
#   t_mean, t_coldest, ti_proxy: Diviner polar products (PCP 80-90 deg, PRP to 80 deg); data files not opened.
#   silica_index: the Diviner Christiansen-feature grid stops at +-60 deg latitude, so it CANNOT be built at either lunar
#   pole. A human must decide to drop it (config/run.yaml drop_columns) or to find another source.
PSR_NOTE = ("PSR raster (for example NASA PGDA LPSR_80S_20MPP_ADJ, https://pgda.gsfc.nasa.gov/products/90): any non-zero, "
            "finite cell is treated as permanently shadowed. CONFIRM the encoding from the file's own metadata before use.")


def build(cfg: dict[str, Any], dem_path: Path | str | None, psr_path: Path | str | None = None) -> list[dict]:
    rows: list[dict] = []
    ill = cfg["targets"]["moon_pole_illumination"]
    for name, t in cfg["targets"]["moon"].items():
        rows.append(C.row(name, "aux_lat", t["lat"], source=t["source"], grade="A"))
        for col in ("sun_max_elev", "sun_low_share"):
            rows.append(C.row(name, col, ill[col], 0.0, "pole illumination rule (config/targets.yaml)",
                              ill["evidence_grade"], "n/a"))
        if dem_path:
            dem, cell = C.read_dem_window(dem_path, t["lat"], float(wrap_lon(t["lon_e"])),
                                         cfg["targets"]["target_window_km"] + 2 * cfg["targets"]["read_margin_km"])
            rows += C.terrain_rows(name, dem, cell, f"LOLA ({Path(dem_path).name})", "A",
                                   cfg["targets"]["target_window_km"], cfg["features"]["operator"])
        else:
            rows += [C.row(name, c, None, unavailable=True) for c in ("slope_med", "slope_p90", "relief", "rough_a", "rough_b")]
        if psr_path:
            mask, cell = C.read_dem_window(psr_path, t["lat"], float(wrap_lon(t["lon_e"])),
                                         cfg["targets"]["target_window_km"] + 2 * cfg["targets"]["read_margin_km"])
            rows += C.mask_share_rows(name, "water_index", mask, cell, f"PSR share of the tile ({Path(psr_path).name})", "A",
                                      cfg["targets"]["target_window_km"])
        else:
            rows.append(C.row(name, "water_index", None, unavailable=True))
        rows += [C.row(name, c, None, unavailable=True) for c in UNBUILT]
    return rows
