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
#   silica_index: the Diviner Christiansen-feature map stops at +-70 deg latitude (Zenodo 4558235), so it CANNOT be built at either lunar
#   pole. A human must decide to drop it (config/run.yaml drop_columns) or to find another source.
PSR_NOTE = ("PSR raster (for example NASA PGDA LPSR_80S_20MPP_ADJ, https://pgda.gsfc.nasa.gov/products/90): any non-zero, "
            "finite cell is treated as permanently shadowed. CONFIRM the encoding from the file's own metadata before use.")
# The one PSR product whose encoding was checked by opening the file (docs/PROVENANCE.md, 2026-11-13): float32, values 0 and
# 1 only, declared nodata NaN, 1 = permanently shadowed (1 on the Shackleton crater floor, 0 on the sunlit rim and ridge).
# A clip of it keeps the prefix. Grade A needs this product AND a window whose finite values are only 0 and 1.
VERIFIED_PSR = "LPSR_80S_20MPP_ADJ"
PSR_VERIFIED_NOTE = ("PSR share of the tile, NASA PGDA LPSR_80S_20MPP_ADJ (Barker et al. 2023, "
                     "https://pgda.gsfc.nasa.gov/products/90): values 0/1, 1 = permanently shadowed, nodata NaN "
                     "(encoding checked on the file, docs/PROVENANCE.md)")


def psr_grade(psr_path: Path | str, mask) -> tuple[str, str]:
    """(grade, source text) for a PSR window: A only for the verified product with a strictly 0/1 window, else B."""
    import numpy as np
    vals = np.unique(mask[np.isfinite(mask)])
    if Path(psr_path).name.upper().startswith(VERIFIED_PSR) and set(vals.tolist()) <= {0.0, 1.0}:
        return "A", f"{PSR_VERIFIED_NOTE} ({Path(psr_path).name})"
    return "B", f"PSR share of the tile ({Path(psr_path).name}). {PSR_NOTE}"


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
            # a declared nodata of 0 is read as 0 (not NaN), so a mask that declares nodata = 0 keeps its non-PSR cells;
            # any other declared nodata (-9999, 255) is missing data, not 'not shadowed', and stays NaN
            mask, cell = C.read_window(psr_path, t["lat"], float(wrap_lon(t["lon_e"])),
                                       cfg["targets"]["target_window_km"] + 2 * cfg["targets"]["read_margin_km"], "zero")
            # grade A only for the product whose encoding was checked (psr_grade); any other raster stays B with the warning
            grade, src = psr_grade(psr_path, mask)
            rows += C.mask_share_rows(name, "water_index", mask, cell, src, grade, cfg["targets"]["target_window_km"])
        else:
            rows.append(C.row(name, "water_index", None, unavailable=True))
        rows += [C.row(name, c, None, unavailable=True) for c in UNBUILT]
    return rows
