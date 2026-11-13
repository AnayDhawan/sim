"""Synthetic Earth grid with a known answer (issue A21). Not real data. Built on gsop.synthetic.make_earth.

    from synth import make_synth
    s = make_synth()                       # 20,000 tiles, seed 2026
    s.earth                                # DataFrame: tile_id, ix, iy, lon, lat, 15 feature columns, 3 gate layers
    s.targets["moon"], s.targets["mars"]   # profiles in the format pipeline.load_target_profiles returns
    s.truth                                # {role: [tile_id, ...]}

`n` can be raised to 4,000,000; the planted tiles keep the same ids, tile_id equals the row number.
Every random tile comes from `make_earth(n, seed)`; the planted rows below overwrite rows of it, so the generator is
deterministic for a seed (same call, same bytes).

Planted tiles (needs n >= 1000). T = the target value of a column, S = its spread (10% of |T|).

  role                  ids              what the tile is, and what the engine must do with it
  --------------------  ---------------  -------------------------------------------------------------------------
  exact                 100              every column equals T. Clean land (no water, low NDVI, no built-up).
                                         Must pass the gates and rank first by base score (100.0).
  near_miss             150              every column at T + 0.5 S. Must pass and rank second.
  single_family_<f>     200 + i          columns of family f (any body) equal T, every other column at T + 20 S.
                                         Must pass the gates; must score far below `exact` (one family only).
                                         i is the index of f in SINGLE_FAMILY_ORDER.
  gated_water           300              exactly T everywhere but water_ice_frac = 0.9.  Must be rejected: open_water_or_ice.
  gated_ndvi            301              exactly T everywhere but ndvi_median = 0.6.      Must be rejected: vegetated.
  gated_built           302              exactly T everywhere but built_crop_frac = 0.5.  Must be rejected: built_or_cropland.
  missing_feature       400              exactly T everywhere but slope_med = NaN.        Must be rejected: missing_data.
  missing_water_index   401              exactly T everywhere but water_index = NaN.      Must be rejected: missing_data
                                         (a feature the Moon's cold_dry and Mars's water family use).
  missing_gate_layer    402              exactly T everywhere but ndvi_median = NaN.      Must be rejected: missing_data.

The synthetic target is the same for both bodies (all 15 columns, spread 10%); the Mars profile also carries the aux
values that pass the Mars target check (latitude 18, elevation -2500 m, thermal inertia 300).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from gsop.synthetic import ALL_COLUMNS, make_earth, target_profile

TARGET_VALUES = {"slope_med": 4.0, "slope_p90": 8.0, "relief": 250.0, "rough_a": 0.5, "rough_b": 5.0,
                 "sun_max_elev": 45.0, "sun_low_share": 0.25, "insol_annual": 220.0, "t_mean": 285.0,
                 "t_coldest": 265.0, "ti_proxy": 20.0, "dust_index": 0.5, "water_index": 0.5, "silica_index": 1.0,
                 "air_density": 1.0}
SPREAD_FRAC = 0.10
MARS_AUX = {"lat": 18.0, "elevation_m": -2500.0, "thermal_inertia_si": 300.0}

IDS = {"exact": 100, "near_miss": 150, "gated_water": 300, "gated_ndvi": 301, "gated_built": 302,
       "missing_feature": 400, "missing_water_index": 401, "missing_gate_layer": 402}
SINGLE_FAMILY_BASE = 200
# union of the Moon and Mars family names, in a fixed order
SINGLE_FAMILY_ORDER = ["slope", "illumination", "cold_dry", "roughness", "relief", "temperature", "composition",
                       "thermal_inertia", "water", "sunlight", "elevation_density"]
CLEAN_GATE = {"water_ice_frac": 0.0, "ndvi_median": 0.05, "built_crop_frac": 0.0}


def spread(col: str) -> float:
    return SPREAD_FRAC * abs(TARGET_VALUES[col])


@dataclass
class Synth:
    earth: pd.DataFrame
    targets: dict[str, dict]
    truth: dict[str, list[int]]
    family_columns: dict[str, list[str]]


def _family_columns() -> dict[str, list[str]]:
    from gsop.config import load_all
    w = load_all()["weights"]
    out: dict[str, list[str]] = {}
    for body in ("moon", "mars"):
        for fam, spec in w[body].items():
            out.setdefault(fam, [])
            out[fam] = sorted(set(out[fam]) | set(spec["columns"]))
    return out


def make_synth(n: int = 20_000, seed: int = 2026) -> Synth:
    if n < 1000:
        raise ValueError("n must be at least 1000 so the planted ids exist")
    df = make_earth(n, seed)
    fams = _family_columns()
    assert set(SINGLE_FAMILY_ORDER) == set(fams), "SINGLE_FAMILY_ORDER is out of date with config/weights.yaml"

    def put(row: int, values: dict[str, float], gate: dict[str, float] | None = None) -> None:
        for c in ALL_COLUMNS:
            df.loc[row, c] = values[c]
        for c, v in {**CLEAN_GATE, **(gate or {})}.items():
            df.loc[row, c] = v

    T = dict(TARGET_VALUES)
    truth: dict[str, list[int]] = {}
    put(IDS["exact"], T)
    truth["exact"] = [IDS["exact"]]
    put(IDS["near_miss"], {c: T[c] + 0.5 * spread(c) for c in T})
    truth["near_miss"] = [IDS["near_miss"]]
    for i, fam in enumerate(SINGLE_FAMILY_ORDER):
        row = SINGLE_FAMILY_BASE + i
        put(row, {c: (T[c] if c in fams[fam] else T[c] + 20 * spread(c)) for c in T})
        truth[f"single_family_{fam}"] = [row]
    put(IDS["gated_water"], T, {"water_ice_frac": 0.9})
    put(IDS["gated_ndvi"], T, {"ndvi_median": 0.6})
    put(IDS["gated_built"], T, {"built_crop_frac": 0.5})
    put(IDS["missing_feature"], {**T, "slope_med": np.nan})
    put(IDS["missing_water_index"], {**T, "water_index": np.nan})
    put(IDS["missing_gate_layer"], T, {"ndvi_median": np.nan})
    for k in ("gated_water", "gated_ndvi", "gated_built", "missing_feature", "missing_water_index",
              "missing_gate_layer"):
        truth[k] = [IDS[k]]
    targets = {
        "moon": target_profile(T, spread=0.0),
        "mars": target_profile(T, spread=0.0, aux=dict(MARS_AUX)),
    }
    for t in targets.values():                      # per-column spread of 10%
        for c, v in t["cols"].items():
            v["spread"] = spread(c)
    return Synth(df, targets, truth, fams)
