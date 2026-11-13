"""Validation against known sites (s7). Pass criteria are pre-registered: written into validation.json,
with a sha256 of the criteria block, BEFORE anything is computed (pattern recycled from the IRIS seal manifest).
Weights are never tuned to pass. Site coordinates are unconfirmed (config/known_sites.yaml) so results are provisional.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .grid import haversine_km
from .provenance import canonical_json, read_json, write_json


def unconfirmed_sites(ks: dict[str, Any]) -> list[str]:
    out = []
    for grp in ("primary", "secondary", "gate_tests", "negative_controls"):
        for name, s in ks[grp].items():
            if not s.get("confirmed", False):
                out.append(f"{grp}/{name}")
    return out


def preregister(path: Path | str, ks: dict[str, Any], body: str) -> dict[str, Any]:
    block = {"criteria": ks["criteria"], "radius_km_source": "run.yaml site_match_radius_km", "body": body,
             "site_score_rule": "mean over the body's scored targets of the base-profile rank percentile of the "
                                "best tile within the match radius (percentile among all gated tiles of that target)",
             "unconfirmed_sites": unconfirmed_sites(ks)}
    doc = {"preregistered": block,
           "preregistered_sha256": hashlib.sha256(canonical_json(block).encode()).hexdigest(),
           "registered_at": time.strftime("%Y-%m-%d %H:%M:%S%z"), "status": "pending", "provisional": True}
    write_json(path, doc)
    return doc


def rank_pct(scores: np.ndarray, value: float) -> float:
    return float(100.0 * np.mean(scores < value))


NO_TILE_KM = 6.0     # a tile centre farther than this from a point means the point is not on a land tile (cell is 6 km)


MC_COLS = ("mc_p05", "mc_median", "mc_p95", "rank_pct_p05", "rank_pct_p50", "rank_pct_p95", "freq_top5", "robust")


def validate_body(body: str, ks: dict[str, Any], radius_km: float, earth: pd.DataFrame,
                  gate_by_target: dict[str, pd.DataFrame], scores_by_target: dict[str, pd.Series],
                  out_path: Path | str, mc_by_target: dict[str, pd.DataFrame] | None = None,
                  profile_scores: dict[str, dict[str, pd.Series]] | None = None) -> dict[str, Any]:
    """earth: all tiles (tile_id, lat, lon). gate_by_target: per scored target, the base-profile gate table (row i of
    the table is row i of earth). scores_by_target: per scored target, base score indexed by tile_id (gated tiles only).
    mc_by_target: optional per target, the Monte Carlo candidate table indexed by tile_id (the best tile's MC range is
    reported when it is a candidate). profile_scores: optional {target: {profile: scores}}, for the rank percentile
    of each site under every purpose profile (reported, never part of the pass criteria)."""
    mc_by_target = mc_by_target or {}
    profile_scores = profile_scores or {}
    doc = read_json(out_path) if Path(out_path).exists() else preregister(out_path, ks, body)
    crit = doc["preregistered"]["criteria"]
    tid = earth["tile_id"].to_numpy()
    lat, lon = earth["lat"].to_numpy(), earth["lon"].to_numpy()
    targets = list(scores_by_target)

    def site_pcts(s: dict[str, Any]) -> dict[str, Any]:
        d = haversine_km(s["lat"], s["lon"], lat, lon)
        rad = float(s.get("radius_km", radius_km))
        within = d <= rad
        near = tid[within]
        per = {}
        for t in targets:
            sc = scores_by_target[t]
            cand = sc.reindex(near).dropna()
            if cand.empty:
                reasons = gate_by_target[t]["reason"].to_numpy()[within]
                why = pd.Series(reasons).value_counts().to_dict() if len(reasons) else {"no land tile in the radius": 0}
                per[t] = {"rank_pct": 0.0, "best_tile": None, "status": "rejected", "gates_passed": False,
                          "rejected_reasons": {str(k): int(v) for k, v in why.items()},
                          "note": "no gated tile within the radius: every tile there was rejected by the gates"}
            else:
                best = int(cand.idxmax())
                row = {"rank_pct": rank_pct(sc.to_numpy(), float(cand.max())), "best_tile": best,
                       "best_score": float(cand.max()), "status": "scored", "gates_passed": True,
                       "n_gated_tiles_in_radius": int(cand.size), "n_tiles_in_radius": int(within.sum())}
                mc = mc_by_target.get(t)
                if mc is not None and best in mc.index:
                    row["mc"] = {c: (bool(mc.at[best, c]) if c == "robust" else float(mc.at[best, c]))
                                 for c in MC_COLS if c in mc.columns}
                else:
                    row["mc"] = None
                by_prof = {}
                for prof, ps in profile_scores.get(t, {}).items():
                    pc = ps.reindex(near).dropna()
                    by_prof[prof] = rank_pct(ps.to_numpy(), float(pc.max())) if not pc.empty else 0.0
                if by_prof:
                    row["rank_pct_by_profile"] = by_prof
                per[t] = row
        pct = float(np.mean([v["rank_pct"] for v in per.values()])) if per else float("nan")
        return {"rank_pct": pct, "per_target": per,
                "status": "rejected" if per and all(v["status"] == "rejected" for v in per.values()) else "scored"}

    primary = {n: {**site_pcts(s), "lat": s["lat"], "lon": s["lon"], "confirmed": s.get("confirmed", False)}
               for n, s in ks["primary"].items() if body in s["bodies"]}
    controls = {n: {**site_pcts(s), "lat": s["lat"], "lon": s["lon"], "confirmed": s.get("confirmed", False)}
                for n, s in ks["negative_controls"].items()}
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
    table = [{"group": grp, "site": n, "target": t, **{k: v.get(k) for k in (
                 "best_tile", "best_score", "rank_pct", "status", "gates_passed", "rejected_reasons", "mc")}}
             for grp, sites in (("primary", primary), ("negative_control", controls), ("secondary", secondary))
             for n, site in sites.items() for t, v in site["per_target"].items()]
    prim_med = float(np.median([v["rank_pct"] for v in primary.values()])) if primary else float("nan")
    ctl_max = float(max(v["rank_pct"] for v in controls.values())) if controls else float("nan")
    results = {
        "primary": primary, "negative_controls": controls, "secondary": secondary, "gate_tests": gate_tests,
        "site_table": table,
        "primary_median_rank_pct": prim_med, "negative_control_max_rank_pct": ctl_max,
        "pass": {
            "primary_median_ge_min": bool(prim_med >= crit["primary_median_rank_pct_min"]),
            "controls_below_max": bool(ctl_max < crit["negative_control_rank_pct_max"]),
            "gate_tests_all_rejected": bool(all(v["rejected"] for v in gate_tests.values())),
        },
        "n_primary_sites": len(primary),
    }
    results["pass"]["all"] = all(results["pass"].values())
    doc.update({"status": "computed", "results": results, "computed_at": time.strftime("%Y-%m-%d %H:%M:%S%z"),
                "provisional": True, "note": "Site coordinates are unconfirmed; do not publish before confirmation."})
    write_json(out_path, doc)
    return doc


def verify_preregistration(path: Path | str) -> bool:
    doc = read_json(path)
    return hashlib.sha256(canonical_json(doc["preregistered"]).encode()).hexdigest() == doc["preregistered_sha256"]


# --------------------------------------------------------------------------- baselines (D07)

COMPARABILITY = {
    "equal": "apples-to-apples: our families and data, only the weights differ (all families equal)",
    "no_illumination": "apples-to-apples: our families and data, illumination weight set to 0 (decision D4)",
    "single_variable": "apples-to-apples: our data and target, one family alone with weight 1",
    "liu2025": "NOT apples-to-apples: Liu 2025's weights on OUR features and Earth data, and for the five families it "
               "names only (no temperature, relief or thermal inertia); the paper's own features and data differ",
    "mashal2025": "NOT apples-to-apples: Mashal 2025's weights on OUR features and Earth data, and for the three families "
                  "it names only; the paper's own features and data differ",
}


def baseline_kind(name: str) -> str:
    return "single_variable" if name.startswith("only_") else name


def single_variable_sets(family_names: list[str]) -> dict[str, dict[str, float]]:
    return {f"only_{f}": {g: (1.0 if g == f else 0.0) for g in family_names} for f in family_names}


def site_rank_pcts(score: np.ndarray, lat: np.ndarray, lon: np.ndarray, sites: dict[str, dict[str, Any]],
                   radius_km: float) -> dict[str, float]:
    """Rank percentile of the best tile within each site's radius, among the tiles of `score` (gated tiles).
    A site with no tile in the radius gets 0 (rejected, not dropped)."""
    out = {}
    for n, s in sites.items():
        near = haversine_km(s["lat"], s["lon"], lat, lon) <= float(s.get("radius_km", radius_km))
        out[n] = float(100.0 * np.mean(score < score[near].max())) if near.any() else 0.0
    return out


def compute_baselines(body: str, target: str, fam: dict[str, np.ndarray], primary_weights: dict[str, float],
                      weight_sets: dict[str, dict[str, float]], lat: np.ndarray, lon: np.ndarray, ks: dict[str, Any],
                      radius_km: float) -> dict[str, Any]:
    """Score every baseline once (no Monte Carlo) and compare it with the primary index on the same gated tiles:
    top-1% Jaccard overlap, Spearman rank correlation, and the site-rank metrics of the validation (median rank percentile
    over the body's primary sites, maximum over the negative controls). `fam`: per-family similarity of the gated tiles."""
    from scipy.stats import spearmanr

    from .pipeline import top_overlap
    from .similarity import tile_score
    prim_sites = {n: s for n, s in ks["primary"].items() if body in s["bodies"]}
    controls = ks["negative_controls"]

    def metrics(w: dict[str, float]) -> dict[str, Any]:
        w = {f: v for f, v in w.items() if f in fam}
        tot = sum(w.values())
        if tot <= 0:
            return {"error": "no active family has weight"}
        w = {f: v / tot for f, v in w.items()}
        s = tile_score(fam, w)
        ps = site_rank_pcts(s, lat, lon, prim_sites, radius_km)
        cs = site_rank_pcts(s, lat, lon, controls, radius_km)
        return {"weights": w, "score": s, "primary_site_rank_pct": ps,
                "primary_median_rank_pct": float(np.median(list(ps.values()))) if ps else float("nan"),
                "negative_control_max_rank_pct": float(max(cs.values())) if cs else float("nan")}

    prim = metrics(primary_weights)
    ref = prim.pop("score")
    out: dict[str, Any] = {"body": body, "target": target, "primary": prim, "baselines": {}, "beats_primary": []}
    for name, w in weight_sets.items():
        m = metrics(w)
        if "error" in m:
            out["baselines"][name] = m
            continue
        s = m.pop("score")
        m["top1pct_overlap_jaccard"] = float(top_overlap(ref, s))
        m["spearman_vs_primary"] = float(spearmanr(ref, s).statistic) if np.ptp(s) > 0 else float("nan")
        m["comparability"] = COMPARABILITY.get(baseline_kind(name), "custom baseline: not classified")
        m["delta_median_rank_pct_vs_primary"] = m["primary_median_rank_pct"] - prim["primary_median_rank_pct"]
        m["beats_primary_on_site_ranks"] = bool(m["delta_median_rank_pct_vs_primary"] > 0)
        m["worse_on_negative_controls"] = bool(m["negative_control_max_rank_pct"] > prim["negative_control_max_rank_pct"])
        if m["beats_primary_on_site_ranks"]:
            out["beats_primary"].append(name)
        out["baselines"][name] = m
    out["verdict"] = (
        "No baseline has a higher median primary-site rank percentile than the primary index." if not out["beats_primary"]
        else "BASELINES THAT BEAT THE PRIMARY INDEX on the median primary-site rank percentile: "
             + ", ".join(out["beats_primary"]) + ". The weighted index is not doing better than a simpler rule there.")
    return out


def baselines_markdown(rep: dict[str, Any]) -> str:
    p = rep["primary"]
    lines = [f"# Baselines: {rep['body']} / {rep['target']}", "",
             "Each baseline is scored once (no Monte Carlo) on the same gated tiles and compared with the primary index.",
             "Site metrics use the best tile within the match radius of each primary site; 6 primary-site positives at most "
             "(see docs/SPEC.md): treat differences of a few percentile points as noise.", "",
             f"**{rep['verdict']}**", "",
             "| baseline | top-1% overlap | Spearman | median site rank % | vs primary | max control rank % | comparable |",
             "|---|---|---|---|---|---|---|",
             f"| primary index | 1.000 | 1.000 | {p['primary_median_rank_pct']:.1f} | 0.0 | "
             f"{p['negative_control_max_rank_pct']:.1f} | reference |"]
    for name, m in rep["baselines"].items():
        if "error" in m:
            lines.append(f"| {name} | - | - | - | - | - | {m['error']} |")
            continue
        flag = " **(beats primary)**" if m["beats_primary_on_site_ranks"] else ""
        kind = "yes" if m["comparability"].startswith("apples") else "no"
        lines.append(f"| {name}{flag} | {m['top1pct_overlap_jaccard']:.3f} | {m['spearman_vs_primary']:.3f} | "
                     f"{m['primary_median_rank_pct']:.1f} | {m['delta_median_rank_pct_vs_primary']:+.1f} | "
                     f"{m['negative_control_max_rank_pct']:.1f} | {kind} |")
    lines += ["", "Comparability: " + "; ".join(f"{k}: {v}" for k, v in COMPARABILITY.items())]
    return "\n".join(lines) + "\n"
