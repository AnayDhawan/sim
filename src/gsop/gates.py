"""Hard gates. A tile failing any gate is rejected; the first failing reason (priority order) is logged per tile."""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

REASONS = ["ok", "open_water_or_ice", "vegetated", "built_or_cropland", "extra_gate", "missing_data"]
CODE = {r: i for i, r in enumerate(REASONS)}

_EXPR = re.compile(r"^\s*(\w+)\s*(<=|>=|<|>)\s*([0-9.eE+-]+)\s*$")
_OPS = {"<=": np.less_equal, ">=": np.greater_equal, "<": np.less, ">": np.greater}


def eval_extra_gate(df: pd.DataFrame, expr: str) -> np.ndarray:
    """True where the tile satisfies the expression, e.g. 'slope_med <= 8'. NaN never satisfies."""
    m = _EXPR.match(expr)
    if not m:
        raise ValueError(f"cannot parse gate expression {expr!r}")
    col, op, val = m.group(1), m.group(2), float(m.group(3))
    x = df[col].to_numpy(dtype=float)
    return _OPS[op](x, val) & np.isfinite(x)


def extra_gate_expr(purposes_cfg: dict[str, Any], profile: str, body: str) -> str | None:
    if profile == "base":
        return None
    return purposes_cfg["purposes"][profile].get("extra_gate", {}).get(body)


def apply_gates(df: pd.DataFrame, gates_cfg: dict[str, Any], used_columns: list[str],
                extra_expr: str | None = None) -> pd.DataFrame:
    """Returns DataFrame(tile_id, code, reason, passed). Missing gate layers count as missing data."""
    g = gates_cfg["tile_gates"]
    n = len(df)
    layer = lambda c: df[c].to_numpy(dtype=float) if c in df else np.full(n, np.nan)  # noqa: E731
    wi, nd, bc = layer("water_ice_frac"), layer("ndvi_median"), layer("built_crop_frac")
    miss = ~np.isfinite(wi) | ~np.isfinite(nd) | ~np.isfinite(bc)
    for c in used_columns:
        miss |= ~np.isfinite(layer(c))
    fail_water = wi > g["open_water_or_ice_frac_max"]
    fail_veg = nd > g["ndvi_median_max"]
    fail_built = bc > g["built_or_crop_frac_max"]
    fail_extra = ~eval_extra_gate(df, extra_expr) if extra_expr else np.zeros(n, bool)
    code = np.zeros(n, np.uint8)
    # assign in reverse priority so the highest priority reason wins
    for mask, name in ((miss, "missing_data"), (fail_extra, "extra_gate"), (fail_built, "built_or_cropland"),
                       (fail_veg, "vegetated"), (fail_water, "open_water_or_ice")):
        code[mask] = CODE[name]
    # a tile with missing data is reported as missing_data even if another gate fires on a present layer
    code[miss] = CODE["missing_data"]
    return pd.DataFrame({"tile_id": df["tile_id"].to_numpy(), "code": code,
                         "reason": np.array(REASONS, dtype=object)[code], "passed": code == 0})


def mars_target_check(aux: dict[str, float | None], cfg: dict[str, Any]) -> dict[str, Any]:
    """D6: target within +/-50 deg latitude, elevation below 2 km, thermal inertia >= 100. Missing value = unknown."""
    c = cfg["mars_target_check"]
    tests = {
        "latitude": (None if aux.get("lat") is None else abs(aux["lat"]) <= c["lat_abs_max_deg"]),
        "elevation": (None if aux.get("elevation_m") is None else aux["elevation_m"] < c["elevation_m_max"]),
        "thermal_inertia": (None if aux.get("thermal_inertia_si") is None
                            else aux["thermal_inertia_si"] >= c["thermal_inertia_si_min"]),
    }
    failed = [k for k, v in tests.items() if v is False]
    unknown = [k for k, v in tests.items() if v is None]
    return {"tests": tests, "failed": failed, "unknown": unknown, "fails_own_gate": bool(failed),
            "mode": c["mode"], "skip": bool(failed) and c["mode"] == "strict"}
