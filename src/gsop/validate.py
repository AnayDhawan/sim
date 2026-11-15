"""Validation against known sites (s7). Pass criteria are pre-registered: written into validation.json,
with a sha256 of the criteria block, BEFORE anything is computed (pattern recycled from the IRIS seal manifest).
Weights are never tuned to pass. Site coordinates are unconfirmed (config/known_sites.yaml) so results are provisional.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from .grid import haversine_km
from .provenance import SLOPE_LABEL, canonical_json, read_json, write_json


def unconfirmed_sites(ks: dict[str, Any]) -> list[str]:
    out = []
    for grp in ("primary", "secondary", "gate_tests", "negative_controls"):
        for name, s in ks[grp].items():
            if not s.get("confirmed", False):
                out.append(f"{grp}/{name}")
    return out


AMENDMENT = ("E28 (2026-11-14, decided before any real run): a primary site whose every tile within the radius fails a "
             "land-cover gate is reported gated_out and left out of the primary median; with fewer than "
             "primary_min_scorable_sites scorable primary sites the primary criterion is not_testable. A gated-out negative "
             "control is reported gated_out and does not count as below the maximum. Reason: Lonar fails the gates by "
             "design (built_crop_frac 1.0, NDVI 0.40), so the primary median could not reach 90 for a structural reason.")
GATED_OUT_RULE = ("gated_out: at least one land tile lies within the radius, none passes the gates, and every one fails at "
                  "least one land-cover gate (open water or ice, vegetated, built or cropland) on its own gate layers. "
                  "A site with no gated tile for any other reason (missing data, no land tile) keeps rank 0 as a primary "
                  "site and is not counted as a scorable negative control.")
CONTROL_RULE = ("E30 (2026-11-14, before any real run): a negative control applies to the bodies in its `bodies` list (all "
                "bodies when absent). The sand-sea controls rub_al_khali and namib_sand_sea are Moon only. The controls "
                "criterion is the maximum rank over scorable controls (a gated tile within the radius); gated_out controls "
                "are reported and not counted (E28).")
UNGATED_RULE = ("ungated_terrain_only, outside the pre-registered test, informational: base-profile score of the best "
                "tile within the radius computed WITHOUT the vegetation (NDVI) and built or cropland gates; the open water "
                "or ice gate and the missing-data rule still apply; rank percentile among the gated tiles' scores of that "
                "target, with the target's own sigma.")


def preregister(path: Path | str, ks: dict[str, Any], body: str) -> dict[str, Any]:
    block = {"criteria": ks["criteria"], "radius_km_source": "run.yaml site_match_radius_km", "body": body,
             "site_score_rule": "mean over the body's scored targets of the base-profile rank percentile of the "
                                "best tile within the match radius (percentile among all gated tiles of that target); "
                                "the primary median is over scorable (not gated_out) primary sites",
             "gated_out_rule": GATED_OUT_RULE, "amendment": AMENDMENT, "control_rule": CONTROL_RULE,
             "unconfirmed_sites": unconfirmed_sites(ks)}
    doc = {"preregistered": block,
           "preregistered_sha256": hashlib.sha256(canonical_json(block).encode()).hexdigest(),
           "registered_at": time.strftime("%Y-%m-%d %H:%M:%S%z"), "status": "pending", "provisional": True}
    write_json(path, doc)
    return doc


def rank_pct(scores: np.ndarray, value: float) -> float:
    return float(100.0 * np.mean(scores < value))


NO_TILE_KM = 6.0     # a tile centre farther than this from a point means the point is not on a land tile (cell is 6 km)
LANDCOVER = (("open_water_or_ice", "water_ice_frac", "open_water_or_ice_frac_max"),
             ("vegetated", "ndvi_median", "ndvi_median_max"),
             ("built_or_cropland", "built_crop_frac", "built_or_crop_frac_max"))


def _col(earth: pd.DataFrame, c: str, rows: np.ndarray) -> np.ndarray:
    return earth[c].to_numpy(dtype=float)[rows] if c in earth else np.full(rows.size, np.nan)


def _landcover_fail(earth: pd.DataFrame, rows: np.ndarray, gates_cfg: dict[str, Any]) -> tuple[np.ndarray, list[str]]:
    """Per row: does it fail any land-cover gate on its own layers (NaN never fails), and the first failing reason."""
    g = gates_cfg["tile_gates"]
    fail = np.zeros(rows.size, bool)
    first = [""] * rows.size
    for reason, col, key in LANDCOVER:
        f = _col(earth, col, rows) > g[key]
        for i in np.flatnonzero(f & ~fail):
            first[i] = reason
        fail |= f
    return fail, first


def validate_body(body: str, ks: dict[str, Any], radius_km: float, earth: pd.DataFrame,
                  gate_by_target: dict[str, pd.DataFrame], scores_by_target: dict[str, pd.Series],
                  out_path: Path | str, gates_cfg: dict[str, Any] | None = None, used_columns: list[str] | None = None,
                  ungated_scorer: Callable[[str, np.ndarray], np.ndarray] | None = None) -> dict[str, Any]:
    """earth: all tiles (tile_id, lat, lon). gate_by_target: per scored target, the base-profile gate table.
    scores_by_target: per scored target, base score indexed by tile_id (gated tiles only).
    gates_cfg / used_columns: needed to detect gated_out sites (E28); without them no site is gated_out.
    ungated_scorer(target, earth_rows) -> base scores of those rows with the target's gated sigma (informational block)."""
    doc = read_json(out_path) if Path(out_path).exists() else preregister(out_path, ks, body)
    crit = doc["preregistered"]["criteria"]
    tid = earth["tile_id"].to_numpy()
    lat, lon = earth["lat"].to_numpy(), earth["lon"].to_numpy()
    targets = list(scores_by_target)

    def ungated(rows: np.ndarray) -> dict[str, Any]:
        g = gates_cfg["tile_gates"]
        wi = _col(earth, "water_ice_frac", rows)
        need = [_col(earth, c, rows) for c in ["water_ice_frac", "ndvi_median", "built_crop_frac"] + list(used_columns or [])]
        dry = np.isfinite(wi) & (wi <= g["open_water_or_ice_frac_max"])
        complete = np.all([np.isfinite(x) for x in need], axis=0)
        ok = dry & complete
        out: dict[str, Any] = {"label": "outside the pre-registered test, informational", "rule": UNGATED_RULE}
        if not ok.any():
            out["status"] = "no_terrain_yet" if (dry & ~complete).any() else "all tiles fail the open water or ice gate"
            return out
        if ungated_scorer is None:
            out["status"] = "not computed (no scorer)"
            return out
        out["status"] = "computed"
        per = {}
        for t in targets:
            sc = np.asarray(ungated_scorer(t, rows[ok]), dtype=float)
            j = int(np.nanargmax(sc))
            per[t] = {"best_tile": int(tid[rows[ok][j]]), "best_score": float(sc[j]),
                      "rank_pct_among_gated": rank_pct(scores_by_target[t].to_numpy(), float(sc[j]))}
        out["per_target"] = per
        out["rank_pct"] = float(np.mean([v["rank_pct_among_gated"] for v in per.values()]))
        return out

    def site_pcts(s: dict[str, Any]) -> dict[str, Any]:
        d = haversine_km(s["lat"], s["lon"], lat, lon)
        rad = float(s.get("radius_km", radius_km))
        rows = np.flatnonzero(d <= rad)
        near = tid[rows]
        per = {}
        for t in targets:
            sc = scores_by_target[t]
            cand = sc.reindex(near).dropna()
            if cand.empty:
                per[t] = {"rank_pct": 0.0, "best_tile": None, "note": "no gated tile within the radius"}
            else:
                per[t] = {"rank_pct": rank_pct(sc.to_numpy(), float(cand.max())), "best_tile": int(cand.idxmax()),
                          "best_score": float(cand.max())}
        if per and all(v["best_tile"] is None for v in per.values()) and rows.size and gates_cfg is not None:
            fail, first = _landcover_fail(earth, rows, gates_cfg)
            if fail.all():
                reasons = pd.Series(first).value_counts()
                return {"status": "gated_out", "rank_pct": None, "n_tiles_within_radius": int(rows.size),
                        "gate_reasons": {str(k): int(v) for k, v in reasons.items()},
                        "first_gate_reason": str(reasons.index[0]), "ungated_terrain_only": ungated(rows)}
        pct = float(np.mean([v["rank_pct"] for v in per.values()])) if per else float("nan")
        status = "scored" if any(v["best_tile"] is not None for v in per.values()) else "no_gated_tile"
        return {"status": status, "rank_pct": pct, "per_target": per}

    primary = {n: {**site_pcts(s), "lat": s["lat"], "lon": s["lon"], "confirmed": s.get("confirmed", False)}
               for n, s in ks["primary"].items() if body in s["bodies"]}
    controls = {n: {**site_pcts(s), "lat": s["lat"], "lon": s["lon"], "confirmed": s.get("confirmed", False)}
                for n, s in ks["negative_controls"].items() if body in s.get("bodies", [body])}
    secondary = {n: {**site_pcts(s), "lat": s["lat"], "lon": s["lon"]}
                 for n, s in ks["secondary"].items() if body in s["bodies"]}
    gate_tests = {}
    gate = next(iter(gate_by_target.values()))
    for n, s in ks["gate_tests"].items():
        d = haversine_km(s["lat"], s["lon"], lat, lon)
        i = int(np.argmin(d))
        if d[i] > NO_TILE_KM:                                   # point is not on any land tile of the grid
            gate_tests[n] = {"rejected": True, "reason": "no land tile at the point", "distance_km": float(d[i])}
            continue
        g = gate.iloc[i]
        gate_tests[n] = {"rejected": not bool(g["passed"]), "reason": str(g["reason"]), "tile_id": int(tid[i]),
                         "distance_km": float(d[i])}
    min_n = int(crit.get("primary_min_scorable_sites", 2))
    scorable = {k: v for k, v in primary.items() if v["status"] != "gated_out"}
    gated_p = sorted(k for k, v in primary.items() if v["status"] == "gated_out")
    ctl_ok = {k: v for k, v in controls.items() if v["status"] == "scored"}
    prim_med = float(np.median([v["rank_pct"] for v in scorable.values()])) if scorable else float("nan")
    ctl_max = float(max(v["rank_pct"] for v in ctl_ok.values())) if ctl_ok else float("nan")
    status: dict[str, dict[str, Any]] = {}
    if len(scorable) < min_n:
        status["primary_median_ge_min"] = {"status": "not_testable", "reason": (
            f"{len(scorable)} scorable primary site(s) for {body}, fewer than {min_n}; gated_out: {gated_p}")}
    else:
        status["primary_median_ge_min"] = {"status": "pass" if prim_med >= crit["primary_median_rank_pct_min"] else "fail",
                                           "reason": f"median over {sorted(scorable)}; gated_out excluded: {gated_p}"}
    if not ctl_ok:
        status["controls_below_max"] = {"status": "not_testable", "reason": (
            "no negative control has a gated tile within its radius: "
            + ", ".join(f"{k} {v['status']}" for k, v in controls.items()))}
    else:
        status["controls_below_max"] = {"status": "pass" if ctl_max < crit["negative_control_rank_pct_max"] else "fail",
                                        "reason": f"max over {sorted(ctl_ok)}"}
    status["gate_tests_all_rejected"] = {"status": "pass" if all(v["rejected"] for v in gate_tests.values()) else "fail",
                                         "reason": ""}
    passed: dict[str, Any] = {k: (None if v["status"] == "not_testable" else v["status"] == "pass")
                              for k, v in status.items()}
    vals = list(passed.values())
    passed["all"] = False if False in vals else (True if all(v is True for v in vals) else None)
    results = {
        "primary": primary, "negative_controls": controls, "secondary": secondary, "gate_tests": gate_tests,
        "primary_median_rank_pct": prim_med, "negative_control_max_rank_pct": ctl_max,
        "criteria_status": status, "pass": passed,
        "n_primary_sites": len(primary), "n_scorable_primary_sites": len(scorable), "gated_out_primary_sites": gated_p,
    }
    doc.update({"status": "computed", "results": results, "computed_at": time.strftime("%Y-%m-%d %H:%M:%S%z"),
                "provisional": True, "note": "Site coordinates are unconfirmed; do not publish before confirmation."})
    doc.update(SLOPE_LABEL)
    write_json(out_path, doc)
    return doc


def verify_preregistration(path: Path | str) -> bool:
    doc = read_json(path)
    return hashlib.sha256(canonical_json(doc["preregistered"]).encode()).hexdigest() == doc["preregistered_sha256"]
