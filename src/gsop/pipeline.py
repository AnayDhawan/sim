"""Glue: build a scoring job for one (body, target, profile) and run the score, Monte Carlo and checks on it."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from . import gates as G
from . import montecarlo as MC
from . import similarity as S
from . import weights as W
from .provenance import atomic_savez, atomic_to_parquet, write_json

ILLUM_FAMILIES = ("illumination", "sunlight")


# --------------------------------------------------------------------------- targets

def load_target_profiles(path: Path | str) -> dict[str, dict[str, Any]]:
    """Long parquet [target, col, value, spread, source, evidence_grade, window, unavailable]
    -> {target: {"cols": {col: {value, spread, ...}}, "aux": {name: value}, "unavailable": [col]}}.
    Rows whose col starts with 'aux_' are auxiliary values (aux_lat, aux_elevation_m, aux_thermal_inertia_si)."""
    df = pd.read_parquet(path)
    out: dict[str, dict[str, Any]] = {}
    for tgt, g in df.groupby("target", sort=False):
        d: dict[str, Any] = {"cols": {}, "aux": {}, "unavailable": []}
        for r in g.itertuples(index=False):
            if r.col.startswith("aux_"):
                d["aux"][r.col[4:]] = None if pd.isna(r.value) else float(r.value)
                continue
            if bool(r.unavailable) or pd.isna(r.value):
                d["unavailable"].append(r.col)
                continue
            d["cols"][r.col] = {"value": float(r.value), "spread": None if pd.isna(r.spread) else float(r.spread),
                                "source": r.source, "evidence_grade": r.evidence_grade, "window": r.window}
        out[str(tgt)] = d
    return out


# --------------------------------------------------------------------------- job

def active_body_cfg(body_cfg: dict[str, Any], drop: list[str]) -> dict[str, Any]:
    out = {}
    for fam, f in body_cfg.items():
        cols = [c for c in f["columns"] if c not in drop]
        if cols:
            out[fam] = {**f, "columns": cols}
    return out


class UnavailableColumns(RuntimeError):
    pass


@dataclass
class Job:
    body: str
    target: str
    profile: str
    confidence: str
    body_cfg: dict[str, Any]
    fam_cols: dict[str, list[str]]
    columns: list[str]
    earth: pd.DataFrame                 # all tiles
    gate_df: pd.DataFrame
    gated_rows: np.ndarray              # row positions in `earth` of tiles that passed
    X: np.ndarray                       # (n_cols, n_gated) float32
    target_vals: dict[str, float]
    sigma: dict[str, float]
    spec: MC.MCSpec
    profile_weights: dict[str, float]
    target_aux: dict[str, Any] = field(default_factory=dict)
    mars_check: dict[str, Any] | None = None
    dropped_columns: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{self.target}__{self.profile}"


def prepare_job(body: str, target: str, profile: str, cfg: dict[str, Any], earth: pd.DataFrame,
                tprof: dict[str, Any], gate_df: pd.DataFrame | None = None) -> Job:
    drop = list(cfg["run"].get("drop_columns") or [])
    body_cfg = active_body_cfg(cfg["weights"][body], drop)
    fam_cols = {f: v["columns"] for f, v in body_cfg.items()}
    columns = list(dict.fromkeys(c for cols in fam_cols.values() for c in cols))   # first-appearance order
    bad = [c for c in columns if c in tprof["unavailable"] or c not in tprof["cols"]]
    bad += [c for c in columns if c not in earth.columns or earth[c].isna().all()]
    bad = sorted(set(bad))
    if bad:
        raise UnavailableColumns(
            f"{body}/{target}: cannot score, unavailable columns {bad}. A column that cannot be built rejects every "
            "tile. To drop one on purpose, list it in config/run.yaml drop_columns (logged, weights renormalised).")
    mars_check = None
    if body == "mars":
        mars_check = G.mars_target_check({**tprof["aux"]}, cfg["gates"])
        if mars_check["skip"]:
            raise UnavailableColumns(f"{body}/{target}: fails Mars target check in strict mode: {mars_check['failed']}")
    expr = G.extra_gate_expr(cfg["purposes"], profile, body)
    if gate_df is None:
        gate_df = G.apply_gates(earth, cfg["gates"], columns, expr)
    rows = np.flatnonzero(gate_df["passed"].to_numpy())
    if rows.size == 0:
        raise UnavailableColumns(f"{body}/{target}/{profile}: no tile passes the gates")
    X = np.stack([earth[c].to_numpy(dtype=np.float32)[rows] for c in columns])
    tv = {c: tprof["cols"][c]["value"] for c in columns}
    unc = cfg["features"].get("measurement_uncertainty", {}).get(body, {}) or {}
    eunc = cfg["features"].get("earth_uncertainty", {}) or {}
    sigma = {c: S.sigma_rule(tprof["cols"][c]["spread"], unc.get(c), S.iqr(X[i])) for i, c in enumerate(columns)}
    mult = W.profile_multipliers(cfg["purposes"], profile, body)
    ranges = {f: tuple(v["range"]) for f, v in body_cfg.items()}
    run = cfg["run"]
    spec = MC.MCSpec(columns=columns, families=fam_cols, ranges=ranges, multipliers=mult, target=tv,
                     meas_unc={c: float(unc.get(c) or 0.0) for c in columns},
                     earth_unc={c: float(eunc.get(c) or 0.0) for c in columns},
                     sigma=sigma, master_seed=int(run["master_seed"]), batch_runs=int(run["batch_runs"]),
                     top_fracs=tuple(run["top_fracs"]))
    conf = cfg["purposes"].get("confidence_overrides", {}).get(body, {}).get(profile, "standard")
    return Job(body=body, target=target, profile=profile, confidence=conf, body_cfg=body_cfg, fam_cols=fam_cols,
               columns=columns, earth=earth, gate_df=gate_df, gated_rows=rows, X=X, target_vals=tv, sigma=sigma,
               spec=spec, profile_weights=W.profile_weights(body_cfg, cfg["purposes"], profile, body),
               target_aux=tprof["aux"], mars_check=mars_check, dropped_columns=drop)


# --------------------------------------------------------------------------- base score and checks

def fam_arrays(job: Job) -> dict[str, np.ndarray]:
    idx = {c: i for i, c in enumerate(job.columns)}
    Xd = {c: job.X[idx[c]] for c in job.columns}
    return S.family_scores(Xd, job.target_vals, job.sigma, job.fam_cols)


def base_score(job: Job) -> tuple[np.ndarray, np.ndarray | None, dict[str, np.ndarray]]:
    fam = fam_arrays(job)
    score = S.tile_score(fam, job.profile_weights)
    illum = next((fam[f] for f in ILLUM_FAMILIES if f in fam), None)
    return score, illum, fam


def top_overlap(a: np.ndarray, b: np.ndarray, frac: float = 0.01) -> float:
    k = max(1, int(np.ceil(frac * a.size)))
    sa = set(np.argpartition(-a, k - 1)[:k].tolist())
    sb = set(np.argpartition(-b, k - 1)[:k].tolist())
    return len(sa & sb) / len(sa | sb)


def alt_weight_checks(job: Job, weights_cfg: dict[str, Any], base: np.ndarray, fam: dict[str, np.ndarray]
                      ) -> dict[str, Any]:
    out = {}
    for name, w in W.alt_weight_sets(job.body, weights_cfg).items():
        w = {f: v for f, v in w.items() if f in fam}
        if sum(w.values()) <= 0:
            out[name] = {"error": "no active family has weight"}
            continue
        w = W.normalise(w)
        s = S.tile_score(fam, w)
        rho = spearmanr(base, s).statistic
        out[name] = {"weights": w, "top1pct_overlap_jaccard": top_overlap(base, s), "spearman": float(rho)}
    return out


def gate_summary(job: Job) -> dict[str, Any]:
    vc = job.gate_df["reason"].value_counts().to_dict()
    return {"n_tiles": int(len(job.gate_df)), "n_passed": int(job.gate_df["passed"].sum()),
            "rejected_by_reason": {k: int(v) for k, v in vc.items() if k != "ok"}}


def run_job(job: Job, cfg: dict[str, Any], out_dir: Path | str, runs: int, workers: int, work_dir: Path | str,
            free_bytes: float, with_mc: bool = True) -> dict[str, Any]:
    """Base score, alt-weight checks and Monte Carlo for one job. Writes files into out_dir; returns summary."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    score, illum, fam = base_score(job)
    tid = job.earth["tile_id"].to_numpy()[job.gated_rows]
    cols = {"tile_id": tid, "score": score.astype(np.float32)}
    if illum is not None:
        cols["illum_match"] = illum.astype(np.float32)
    atomic_to_parquet(pd.DataFrame(cols), out_dir / "base_scores.parquet", index=False)
    alt = alt_weight_checks(job, cfg["weights"], score, fam)
    write_json(out_dir / "alt_weight_checks.json", alt)
    summary: dict[str, Any] = {
        "body": job.body, "target": job.target, "profile": job.profile, "confidence": job.confidence,
        "fails_own_gate": bool(job.mars_check and job.mars_check["fails_own_gate"]),
        "mars_target_check": job.mars_check, "dropped_columns": job.dropped_columns,
        "gates": gate_summary(job), "target_values": job.target_vals, "sigma": job.sigma,
        "profile_weights": job.profile_weights, "weights_derived": W.derive_weights(job.body_cfg),
        "base_score_summary": {"min": float(score.min()), "median": float(np.median(score)), "max": float(score.max())},
        "illumination_note": "Earth cannot match polar lighting; see illum_match in base_scores.parquet",
    }
    if with_mc:
        plan = MC.memory_plan(job.X.shape[1], job.X.shape[0], workers, free_bytes, float(cfg["run"]["ram_fraction"]))
        summary["memory_plan"] = plan
        res = MC.simulate(job.X, job.spec, runs, Path(work_dir) / job.name, workers=workers,
                          chunk_tiles=plan["chunk_tiles"], cand_cfg=cfg["run"]["candidates"],
                          robust_cfg=cfg["run"]["robust"], checkpoints=list(cfg["run"]["convergence_checkpoints"]))
        c = res.candidates.copy()
        rows = job.gated_rows[c.pop("row").to_numpy()]
        c.insert(0, "tile_id", job.earth["tile_id"].to_numpy()[rows])
        c.insert(1, "lat", job.earth["lat"].to_numpy()[rows])
        c.insert(2, "lon", job.earth["lon"].to_numpy()[rows])
        base_by_tile = pd.Series(score, index=tid)
        c["score_base"] = base_by_tile.reindex(c["tile_id"]).to_numpy()
        atomic_to_parquet(c, out_dir / "mc_summary.parquet", index=False)
        atomic_savez(out_dir / "mc_counts.npz", compressed=True, tile_id=tid, counts=res.counts.astype(np.uint16),
                     mean_score=res.mean_score.astype(np.float32))
        write_json(out_dir / "convergence.json", res.convergence)
        summary.update({"runs": runs, "mc_timings_s": res.timings_s, "weight_draw_stats": res.weight_stats,
                        "n_robust": int(res.robust_mask.sum())})
    summary["seconds"] = time.perf_counter() - t0
    write_json(out_dir / "summary.json", summary)
    return summary
