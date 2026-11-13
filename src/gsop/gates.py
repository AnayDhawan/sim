"""Hard gates. A tile failing any gate is rejected; the first failing reason (priority order) is logged per tile."""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

REASONS = ["ok", "open_water_or_ice", "vegetated", "built_or_cropland", "extra_gate", "missing_data"]
CODE = {r: i for i, r in enumerate(REASONS)}
# One bit per reason, so a tile that fails several gates keeps every reason. `code` is the single reporting reason
# (missing data first, then the priority order of gates.yaml).
BIT = {"open_water_or_ice": 1, "vegetated": 2, "built_or_cropland": 4, "extra_gate": 8, "missing_data": 16}
# Near-miss bits: a tile that PASSES a gate but sits within near_miss_frac of its threshold.
NEAR_BIT = {"open_water_or_ice": 1, "vegetated": 2, "built_or_cropland": 4, "extra_gate": 8}
DEFAULT_CHUNK_ROWS = 1_000_000

_EXPR = re.compile(r"^\s*(\w+)\s*(<=|>=|<|>)\s*([0-9.eE+-]+)\s*$")
_OPS = {"<=": np.less_equal, ">=": np.greater_equal, "<": np.less, ">": np.greater}


def _parse(expr: str) -> tuple[str, str, float]:
    m = _EXPR.match(expr)
    if not m:
        raise ValueError(f"cannot parse gate expression {expr!r}")
    return m.group(1), m.group(2), float(m.group(3))


def eval_extra_gate(df: pd.DataFrame, expr: str) -> np.ndarray:
    """True where the tile satisfies the expression, e.g. 'slope_med <= 8'. NaN never satisfies."""
    col, op, val = _parse(expr)
    x = df[col].to_numpy(dtype=float)
    return _OPS[op](x, val) & np.isfinite(x)


def extra_gate_expr(purposes_cfg: dict[str, Any], profile: str, body: str) -> str | None:
    if profile == "base":
        return None
    return purposes_cfg["purposes"][profile].get("extra_gate", {}).get(body)


def decode_mask(mask: int, table: dict[str, int] = BIT) -> list[str]:
    """Bitmask -> reason names, in priority order."""
    return [name for name, bit in table.items() if mask & bit]


def _gate_chunk(df: pd.DataFrame, g: dict[str, Any], near_frac: float, used_columns: list[str],
                extra_expr: str | None) -> dict[str, np.ndarray]:
    n = len(df)
    layer = lambda c: df[c].to_numpy(dtype=float) if c in df else np.full(n, np.nan)  # noqa: E731
    wi, nd, bc = layer("water_ice_frac"), layer("ndvi_median"), layer("built_crop_frac")
    miss = ~np.isfinite(wi) | ~np.isfinite(nd) | ~np.isfinite(bc)
    for c in used_columns:
        miss |= ~np.isfinite(layer(c))
    thr_w, thr_n, thr_b = g["open_water_or_ice_frac_max"], g["ndvi_median_max"], g["built_or_crop_frac_max"]
    fail_water, fail_veg, fail_built = wi > thr_w, nd > thr_n, bc > thr_b       # NaN compares False
    if extra_expr:
        ecol, eop, eval_ = _parse(extra_expr)
        ex = layer(ecol)
        fail_extra = ~(_OPS[eop](ex, eval_) & np.isfinite(ex))
    else:
        ex, eval_, fail_extra = None, None, np.zeros(n, bool)
    # reporting reason: assign in reverse priority so the highest priority reason wins, missing data always first
    code = np.zeros(n, np.uint8)
    for mask, name in ((fail_extra, "extra_gate"), (fail_built, "built_or_cropland"), (fail_veg, "vegetated"),
                       (fail_water, "open_water_or_ice")):
        code[mask] = CODE[name]
    code[miss] = CODE["missing_data"]
    rej = np.zeros(n, np.uint8)
    for mask, name in ((fail_water, "open_water_or_ice"), (fail_veg, "vegetated"), (fail_built, "built_or_cropland"),
                       (fail_extra, "extra_gate"), (miss, "missing_data")):
        rej[mask] |= BIT[name]
    near = np.zeros(n, np.uint8)

    def close(x: np.ndarray, thr: float, fail: np.ndarray) -> np.ndarray:
        with np.errstate(invalid="ignore"):
            return np.isfinite(x) & ~fail & (np.abs(x - thr) <= near_frac * abs(thr))
    for x, thr, fail, name in ((wi, thr_w, fail_water, "open_water_or_ice"), (nd, thr_n, fail_veg, "vegetated"),
                               (bc, thr_b, fail_built, "built_or_cropland")):
        near[close(x, thr, fail)] |= NEAR_BIT[name]
    if ex is not None:
        near[close(ex, eval_, fail_extra)] |= NEAR_BIT["extra_gate"]
    return {"code": code, "mask": rej, "near": near}


def apply_gates(df: pd.DataFrame, gates_cfg: dict[str, Any], used_columns: list[str],
                extra_expr: str | None = None, chunk_rows: int = DEFAULT_CHUNK_ROWS) -> pd.DataFrame:
    """Returns DataFrame(tile_id, code, reason, passed, mask, near). Missing gate layers count as missing data.
    `code`/`reason`: the one reporting reason. `mask`: bitmask of every reason (BIT). `near`: bitmask of the gates
    the tile passes within `near_miss_frac` of the threshold (NEAR_BIT), for the discovery card. Evaluated in chunks
    of `chunk_rows` rows, so the temporaries stay small on 4 million tiles."""
    near_frac = float(gates_cfg.get("near_miss_frac", 0.10))
    parts = [_gate_chunk(df.iloc[a:a + chunk_rows], gates_cfg["tile_gates"], near_frac, used_columns, extra_expr)
             for a in range(0, max(len(df), 1), chunk_rows)]
    out = {k: np.concatenate([p[k] for p in parts]) for k in ("code", "mask", "near")}
    code = out["code"]
    return pd.DataFrame({"tile_id": df["tile_id"].to_numpy(), "code": code,
                         "reason": np.array(REASONS, dtype=object)[code], "passed": code == 0,
                         "mask": out["mask"], "near": out["near"]})


def passed_rejected(g: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(passed, rejected) tables. Rejected rows carry the reporting reason and the full reason mask."""
    return g[g["passed"]].drop(columns=["code", "reason", "mask"]), g[~g["passed"]].drop(columns=["passed", "near"])


def reason_counts(g: pd.DataFrame) -> dict[str, Any]:
    """Counts for the s3 report. `primary`: tiles per reporting reason (sums to the number rejected). `any`: tiles per
    reason counting every reason a tile fails (a tile can appear in several). `near_miss`: passing tiles within
    near_miss_frac of each threshold."""
    mask, near = g["mask"].to_numpy(), g["near"].to_numpy()
    return {"n_tiles": int(len(g)), "n_passed": int(g["passed"].sum()), "n_rejected": int((~g["passed"]).sum()),
            "primary": {k: int(v) for k, v in g["reason"].value_counts().items() if k != "ok"},
            "any": {k: int(((mask & b) != 0).sum()) for k, b in BIT.items()},
            "near_miss": {k: int(((near & b) != 0).sum()) for k, b in NEAR_BIT.items()}}


def format_counts(c: dict[str, Any], label: str = "") -> str:
    prim = ", ".join(f"{k} {v:,}" for k, v in sorted(c["primary"].items(), key=lambda kv: -kv[1])) or "none"
    anyr = ", ".join(f"{k} {v:,}" for k, v in c["any"].items() if v)
    near = ", ".join(f"{k} {v:,}" for k, v in c["near_miss"].items() if v) or "none"
    return (f"gates{' ' + label if label else ''}: {c['n_passed']:,} of {c['n_tiles']:,} tiles pass; rejected by "
            f"reporting reason: {prim}; by any reason: {anyr or 'none'}; passing but within the near-miss band: {near}")


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
