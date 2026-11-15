"""Mars target profiles (S's machine). Phase 3.

Built: slope_med, slope_p90, relief from a MOLA DEM window (give the GeoTIFF path; the 463 m window is resampled
bilinearly to the 500 m slope baseline), aux_elevation_m and air_density from the same window (config/targets.yaml
mars_atmosphere), insol_annual and sun_max_elev computed from latitude (config/targets.yaml mars_solar).
DERIVED from downloaded files (give the paths; status DERIVED, provenance in config/targets.yaml mars_derived):
aux_thermal_inertia_si from the Zenodo THEMIS Jezero mosaic (themis_rows, for the D6 target check), t_mean and t_coldest
from a saved Mars Climate Database surface temperature table (mcd_rows, scripts/mcd_jezero.py writes it).
NOT built, so they stay `unavailable`: rough_a and rough_b (463 m cells cannot resolve a 300 m or 1000 m plane-fit
window), silica_index (TES), water_index (SWIM ice consistency), ti_proxy (THEMIS is a thermal inertia in SI units, the
Earth column is a temperature swing in K, see TI_PROXY_REASON), dust_index (TES). Arcadia has no centre in our files (D10): it is skipped as
`unscored: no target data` until the centre is taken from the SWIM ice map. Do not guess coordinates.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..grid import wrap_lon
from . import common as C

UNBUILT = ["silica_index", "water_index", "ti_proxy", "dust_index"]
FILE_COLS = ["t_mean", "t_coldest", "aux_thermal_inertia_si"]      # built only when the THEMIS file / MCD table is given
SUN_COLS = ("insol_annual", "sun_max_elev")
TI_PROXY_REASON = ("not built: the THEMIS product is thermal inertia in J m-2 K-1 s-1/2 (kept as aux_thermal_inertia_si) "
                   "and the Earth ti_proxy column is a dry-season day-night temperature swing in K; the two are not "
                   "the same quantity and no conversion is defined (docs/UNVERIFIED.md)")


def _derived(cfg: dict[str, Any], col: str) -> dict[str, str]:
    return cfg["targets"]["mars_derived"][col]


def _derived_source(cfg: dict[str, Any], col: str, what: str) -> str:
    """The source text of a DERIVED row: what was computed, then unit, product, URL, date run and the exact command."""
    d = _derived(cfg, col)
    return (f"status DERIVED; {what}; unit {d['unit']}; product {d['product']}; url {d['url']}; "
            f"date run {d['date_run']}; command {d['command']}")


def themis_profile(path: Path | str, lat: float, lon_e: float, window_km: float, op: dict[str, Any],
                   read_margin_km: float = 1.0) -> dict[str, Any]:
    """THEMIS thermal inertia over the target window, with the repo's window and tile rule (common.tile_median_profile).
    The file's declared nodata (0 in the Zenodo product) and NaN are masked; nothing is filled or resampled.
    Returns value, spread, n_tiles, valid pixel counts, covered fraction and the file's CRS, cell size and bounds."""
    import rasterio
    a, cell = C.read_dem_window(path, lat, float(wrap_lon(lon_e)), window_km + 2 * read_margin_km)
    cov = C.window_coverage(a, cell, window_km)
    value, spread, n_tiles = C.tile_median_profile(a, cell, window_km, op["tile_m"], op["stride_m"])
    with rasterio.open(path) as ds:
        info = {"crs": ds.crs.to_string() if ds.crs else None, "cell_m": cell, "bounds": tuple(ds.bounds),
                "nodata": ds.nodata, "shape": (ds.height, ds.width)}
    crop = C.central_crop(a, cell, window_km)
    return {"value": value, "spread": spread, "n_tiles": n_tiles, "valid_pixels": int(np.isfinite(crop).sum()),
            "window_pixels": int(crop.size), "covered_frac": cov["covered_frac"], "read_window_cells": a.shape,
            "min": float(np.nanmin(crop)), "max": float(np.nanmax(crop)), **info}


def themis_rows(name: str, lat: float, lon_e: float, path: Path | str, cfg: dict[str, Any]) -> list[dict]:
    """aux_thermal_inertia_si from THEMIS (used by the D6 target check, thermal inertia at least 100); ti_proxy stays
    unavailable because the Earth column has another unit (TI_PROXY_REASON)."""
    wk = cfg["targets"]["target_window_km"]
    p = themis_profile(path, lat, lon_e, wk, cfg["features"]["operator"], cfg["targets"]["read_margin_km"])
    what = (f"median over {p['n_tiles']} 6 km tiles (stride 3 km) of the tile median, spread IQR/1.349, "
            f"{p['valid_pixels']} valid pixels of {p['window_pixels']} in the {wk:g} km window "
            f"(covered fraction {p['covered_frac']:.4f}), nodata 0 and NaN masked, native {p['cell_m']:g} m cells")
    return [C.row(name, "aux_thermal_inertia_si", p["value"], p["spread"], _derived_source(cfg, "aux_thermal_inertia_si", what),
                  "A", f"{wk:g} km, {p['n_tiles']} tiles"),
            C.row(name, "ti_proxy", None, source=TI_PROXY_REASON, unavailable=True)]


# MCD tsurf table: one row per (Ls, local time) request, written by scripts/mcd_jezero.py
MCD_COLS = ["ls_deg", "local_time_h", "tsurf_k", "kind"]


def parse_mcd_tsurf(html: str) -> tuple[float, str]:
    """(surface temperature in K, the 'MCD_v.. with .. scenario' header line) from an MCD web CGI response."""
    m = re.search(r"Surface temperature \(K\) \.+\s*([-+0-9.eE]+)", html)
    if not m:
        raise ValueError("no 'Surface temperature (K)' line in the MCD response")
    h = re.search(r"MCD_v[0-9.]+ with [^\n]*", html)
    return float(m.group(1)), (h.group(0).strip() if h else "")


def mcd_stats(df: pd.DataFrame, month_sols: list[float]) -> dict[str, Any]:
    """Annual statistics from the point rows (kind == 'point') of the MCD table. Exact calculation:
      daily mean(Ls) = mean of tsurf over the 24 local times, daily minimum(Ls) = minimum over the 24 local times;
      t_mean     = mean over the 12 month-centre Ls (15, 45, ..., 345) of the daily mean, each month weighted by its
                   length in sols (month_sols); `t_mean_equal_ls` is the unweighted mean over every sampled Ls;
      t_coldest  = minimum over every sampled Ls of the daily minimum (the lowest tsurf in the whole table);
      `t_coldest_daily_mean` = minimum over every sampled Ls of the daily mean (coldest-season mean, for comparison)."""
    p = df[df["kind"] == "point"]
    g = p.groupby("ls_deg")["tsurf_k"]
    dmean, dmin = g.mean(), g.min()
    centres = [15.0 + 30.0 * k for k in range(12)]
    if len(month_sols) != 12 or any(c not in dmean.index for c in centres):
        raise ValueError("the table needs the 12 month-centre Ls (15, 45, ..., 345) and 12 month lengths")
    w = np.asarray(month_sols, dtype=float)
    t_mean = float(np.sum(w * dmean.loc[centres].to_numpy()) / w.sum())
    ls_cold = float(dmin.idxmin())
    lt_cold = float(p[(p["ls_deg"] == ls_cold) & (p["tsurf_k"] == dmin.min())]["local_time_h"].iloc[0])
    return {"t_mean": t_mean, "t_mean_equal_ls": float(dmean.mean()), "t_coldest": float(dmin.min()),
            "t_coldest_ls_deg": ls_cold, "t_coldest_local_time_h": lt_cold, "t_coldest_daily_mean": float(dmean.min()),
            "t_coldest_daily_mean_ls_deg": float(dmean.idxmin()), "n_point_rows": int(len(p)),
            "n_ls": int(dmean.size), "n_local_times": int(p["local_time_h"].nunique()),
            "daily_mean": {float(k): float(v) for k, v in dmean.items()},
            "daily_min": {float(k): float(v) for k, v in dmin.items()}}


def mcd_rows(name: str, path: Path | str, cfg: dict[str, Any]) -> list[dict]:
    """t_mean and t_coldest from the saved MCD table (no network). A point value from a GCM cell about 3.75 by 5.6 deg wide
    (no variation inside the 15 km window), so spread is 0 by construction, not measured. Grade C: a climate model, while
    the Earth column is MODIS LST, so the comparison is only partly like for like."""
    s = mcd_stats(pd.read_csv(path), cfg["targets"]["mars_climate"]["month_sols"])
    tbl = f"{s['n_ls']} Ls x {s['n_local_times']} local times, table {Path(path).name}"
    rows = []
    for col, what in (("t_mean", f"annual mean of the daily mean, 12 month-centre Ls weighted by month length in sols "
                                 f"(equal-Ls mean {s['t_mean_equal_ls']:.3f} K); {tbl}; MCD is a model, Earth t_mean is MODIS LST"),
                      ("t_coldest", f"lowest daily-minimum surface temperature over all Ls (at Ls {s['t_coldest_ls_deg']:g}, "
                                    f"local time {s['t_coldest_local_time_h']:g} h; lowest coldest-season daily mean "
                                    f"{s['t_coldest_daily_mean']:.3f} K); {tbl}; MCD is a model, Earth t_coldest is MODIS LST")):
        rows.append(C.row(name, col, s[col], 0.0, _derived_source(cfg, col, what), "C", "point, MCD GCM cell"))
    return rows


def sun_rows(name: str, lat: float, cfg: dict[str, Any]) -> list[dict]:
    """insol_annual and sun_max_elev at the target latitude, with the SAME latitude-and-obliquity code as the Earth tiles
    (earth/solar.py: flat horizon, circular orbit) and the Mars constants in config/targets.yaml mars_solar (NASA Mars
    fact sheet). Grade C: computed, not measured. Without a `mars_solar` block both stay unavailable."""
    ms = cfg["targets"].get("mars_solar")
    if not ms:
        return [C.row(name, c, None, unavailable=True) for c in SUN_COLS]
    from ..earth.solar import sun_features
    f = cfg["features"]
    sol = {**f["solar"], "obliquity_deg": ms["obliquity_deg"], "s0_w_m2": ms["s0_w_m2"]}
    v = sun_features(lat, {"solar": sol, "sun_low_threshold_deg": f["sun_low_threshold_deg"]})
    src = (f"computed from latitude, obliquity {ms['obliquity_deg']} deg and solar irradiance {ms['s0_w_m2']} W/m2 "
           f"({ms['source']}); earth/solar.py: flat horizon, circular orbit, no atmosphere")
    return [C.row(name, c, float(np.ravel(v[c])[0]), 0.0, src, "C", "target latitude") for c in SUN_COLS]


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


def build(cfg: dict[str, Any], dem_path: Path | str | None, themis_path: Path | str | None = None,
          mcd_path: Path | str | None = None) -> list[dict]:
    rows: list[dict] = []
    for name, t in cfg["targets"]["mars"].items():
        if t.get("lat") is None:
            continue                                       # D10: no coordinates, no profile
        rows.append(C.row(name, "aux_lat", t["lat"], source=t["source"], grade="A"))
        rows += sun_rows(name, t["lat"], cfg)
        if dem_path:
            dem, cell = C.read_dem_window(dem_path, t["lat"], float(wrap_lon(t["lon_e"])),
                                         cfg["targets"]["target_window_km"] + 2 * cfg["targets"]["read_margin_km"])
            op = cfg["features"]["operator"]
            src = f"MOLA ({Path(dem_path).name})"
            tdem, tcell = dem, cell
            base = float(op["slope_baseline_m"])
            if abs(base / cell - round(base / cell)) > 1e-9:
                # MOLA 463 m does not divide the 500 m slope baseline: resample the window bilinearly onto 500 m cells
                tdem, tcell = C.resample_bilinear(dem, cell, base)
                src = f"{src}, window resampled bilinearly from {cell:.2f} m to {base:g} m cells"
            # roughness is taken on the NATIVE cells, never on a resampled surface (interpolation is not relief)
            rows += C.terrain_rows(name, tdem, tcell, src, "A", cfg["targets"]["target_window_km"], op,
                                   rough_reason=C.rough_unavailable_reason(cell, op))
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
        rows += [C.row(name, c, None, unavailable=True) for c in UNBUILT if not (themis_path and c == "ti_proxy")]
        if themis_path:
            rows += themis_rows(name, t["lat"], t["lon_e"], themis_path, cfg)
        else:
            rows.append(C.row(name, "aux_thermal_inertia_si", None, unavailable=True))
        if mcd_path:
            rows += mcd_rows(name, mcd_path, cfg)
        else:
            rows += [C.row(name, c, None, unavailable=True) for c in ("t_mean", "t_coldest")]
    return rows
