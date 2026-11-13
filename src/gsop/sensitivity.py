"""Sensitivity of the index (D09): which family or assumption do the top tiles depend on?

For the primary (base) profile of one target:
  * drop one family at a time (weights renormalised): top-1% overlap and Spearman with the full index, and whether
    each reference-robust tile is still in the top `robust.membership` share of the reduced index;
  * widen and narrow every family's weight range about its midpoint by documented factors and rerun a short Monte Carlo;
  * vary the IQR multiplier of the sigma rule (default 0.15, 0.25, 0.35), recompute the score and rerun a short Monte Carlo.
A reference Monte Carlo of the same short length is run first, so every variant is compared with a run of equal noise.
`survivors` are the reference-robust tiles that are robust in every Monte Carlo variant AND stay in the top share under
every drop-one-family index. Nothing here feeds back into the weights (D9, pre-registration).
"""

from __future__ import annotations

import dataclasses
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import spearmanr

from . import montecarlo as MC
from . import pipeline as P
from . import similarity as S
from . import weights as W

log = logging.getLogger("gsop.sensitivity")
MAX_LISTED_SURVIVORS = 500


def scale_ranges(ranges: dict[str, tuple[float, float]], factor: float) -> dict[str, tuple[float, float]]:
    """Scale each range's half-width by `factor` about its midpoint (lower end kept above 0.001)."""
    out = {}
    for f, (lo, hi) in ranges.items():
        mid, half = (lo + hi) / 2.0, (hi - lo) / 2.0 * factor
        out[f] = (max(0.001, mid - half), mid + half)
    return out


def sigma_with_iqr_factor(job: P.Job, factor: float) -> dict[str, float]:
    """The sigma rule with a different IQR multiplier; the other two terms are the job's own."""
    out = {}
    for c, t in job.sigma_table.items():
        terms = [v for v in (t["target_spread"], t["measurement_uncertainty"]) if v is not None]
        out[c] = max(max(terms + [factor * t["iqr_earth"]]), S.SIGMA_MIN)
    return out


def _mc(job: P.Job, spec: MC.MCSpec, runs: int, work: Path, workers: int, free_bytes: float, cfg: dict[str, Any]):
    plan = MC.memory_plan(job.X.shape[1], job.X.shape[0], workers, free_bytes, float(cfg["run"]["ram_fraction"]))
    t0 = time.perf_counter()
    res = MC.simulate(job.X, spec, runs, work, workers=workers, chunk_tiles=plan["chunk_tiles"],
                      cand_cfg=cfg["run"]["candidates"], robust_cfg=cfg["run"]["robust"], checkpoints=[])
    return res, time.perf_counter() - t0


def _robust_ids(job: P.Job, res: MC.MCResult) -> set[int]:
    return set(job.earth["tile_id"].to_numpy()[job.gated_rows[np.flatnonzero(res.robust_mask)]].tolist())


def run_sensitivity(job: P.Job, cfg: dict[str, Any], work_dir: Path | str, runs: int | None = None, workers: int = 1,
                    free_bytes: float = 8 * 2**30) -> dict[str, Any]:
    scfg = cfg["run"]["sensitivity"]
    runs = int(runs or scfg["runs"])
    work = Path(work_dir)
    t_all = time.perf_counter()
    tid = job.earth["tile_id"].to_numpy()[job.gated_rows]
    fam = P.fam_arrays(job)
    base = S.tile_score(fam, job.profile_weights)
    n = base.size
    top_frac = MC._membership_frac(cfg["run"]["robust"]["membership"])
    k_top = max(1, int(np.ceil(top_frac * n)))
    out: dict[str, Any] = {"body": job.body, "target": job.target, "profile": job.profile, "mc_runs": runs,
                           "n_gated_tiles": int(n), "note": "Reference and variants all use the same short run length; "
                           "robust sets from short runs are noisier than the 2,000-run result."}
    ref, t_ref = _mc(job, job.spec, runs, work / "ref", workers, free_bytes, cfg)
    ref_ids = _robust_ids(job, ref)
    out["reference"] = {"n_robust": len(ref_ids), "seconds": t_ref}
    row_of = {int(t): i for i, t in enumerate(tid)}

    # --- drop one family
    drop = {}
    keep_top = {t: True for t in ref_ids}
    for f in job.profile_weights:
        w = {g: (0.0 if g == f else v) for g, v in job.profile_weights.items()}
        if sum(w.values()) <= 0:
            drop[f] = {"error": "only one family"}
            continue
        s = S.tile_score(fam, W.normalise(w))
        top5 = set(np.argpartition(-s, k_top - 1)[:k_top].tolist())
        in_top = {t for t in ref_ids if row_of[t] in top5}
        for t in ref_ids - in_top:
            keep_top[t] = False
        drop[f] = {"top1pct_overlap_jaccard": float(P.top_overlap(base, s)), "spearman": float(spearmanr(base, s).statistic),
                   "reference_robust_still_in_top": f"{len(in_top)} of {len(ref_ids)}"}
    out["drop_one_family"] = drop

    # --- weight ranges
    ranges_out, survivors = {}, set(ref_ids)
    for fac in scfg["range_factors"]:
        spec = dataclasses.replace(job.spec, ranges=scale_ranges(job.spec.ranges, float(fac)))
        res, dt = _mc(job, spec, runs, work / f"range_{fac}", workers, free_bytes, cfg)
        ids = _robust_ids(job, res)
        survivors &= ids
        ranges_out[f"x{fac}"] = {"n_robust": len(ids), "reference_robust_kept": len(ref_ids & ids),
                                 "overlap_jaccard": len(ref_ids & ids) / max(1, len(ref_ids | ids)), "seconds": dt}
    out["weight_ranges"] = ranges_out

    # --- sigma IQR multiplier
    sig_out = {}
    for k in scfg["iqr_factors"]:
        sg = sigma_with_iqr_factor(job, float(k))
        fam_k = S.family_scores({c: job.X[i] for i, c in enumerate(job.columns)}, job.target_vals, sg, job.fam_cols)
        s = S.tile_score(fam_k, job.profile_weights)
        spec = dataclasses.replace(job.spec, sigma=sg)
        res, dt = _mc(job, spec, runs, work / f"iqr_{k}", workers, free_bytes, cfg)
        ids = _robust_ids(job, res)
        survivors &= ids
        sig_out[str(k)] = {"top1pct_overlap_jaccard": float(P.top_overlap(base, s)),
                           "spearman": float(spearmanr(base, s).statistic), "n_robust": len(ids),
                           "reference_robust_kept": len(ref_ids & ids),
                           "overlap_jaccard": len(ref_ids & ids) / max(1, len(ref_ids | ids)), "seconds": dt}
    out["sigma_iqr_factor"] = sig_out

    survivors = {t for t in survivors if keep_top[t]}
    ranked = sorted(survivors)[:MAX_LISTED_SURVIVORS]
    out["survivors"] = {"definition": f"reference-robust, robust in every Monte Carlo variant, and in the top "
                        f"{top_frac:.0%} of every drop-one-family index", "n_reference_robust": len(ref_ids),
                        "n_survivors": len(survivors), "tile_ids": [int(t) for t in ranked],
                        "listed_at_most": MAX_LISTED_SURVIVORS}
    out["seconds_total"] = time.perf_counter() - t_all
    log.info("sensitivity %s/%s: %d of %d reference-robust tiles survive every variant (%.0f s)", job.target, job.profile,
             len(survivors), len(ref_ids), out["seconds_total"])
    return out


def markdown(rep: dict[str, Any]) -> str:
    L = [f"# Sensitivity: {rep['body']} / {rep['target']} / {rep['profile']}", "",
         f"{rep['n_gated_tiles']:,} gated tiles; Monte Carlo variants use {rep['mc_runs']} runs. {rep['note']}", "",
         "## Drop one family (renormalised)", "", "| family dropped | top-1% overlap | Spearman | reference-robust still in top share |",
         "|---|---|---|---|"]
    for f, d in rep["drop_one_family"].items():
        L.append(f"| {f} | - | - | {d['error']} |" if "error" in d else
                 f"| {f} | {d['top1pct_overlap_jaccard']:.3f} | {d['spearman']:.3f} | {d['reference_robust_still_in_top']} |")
    L += ["", f"## Monte Carlo variants (reference: {rep['reference']['n_robust']} robust tiles)", "",
          "| variant | robust tiles | reference-robust kept | Jaccard | seconds |", "|---|---|---|---|---|"]
    for k, d in rep["weight_ranges"].items():
        L.append(f"| weight ranges {k} | {d['n_robust']} | {d['reference_robust_kept']} | {d['overlap_jaccard']:.3f} | {d['seconds']:.1f} |")
    for k, d in rep["sigma_iqr_factor"].items():
        L.append(f"| sigma IQR factor {k} (index top-1% overlap {d['top1pct_overlap_jaccard']:.3f}) | {d['n_robust']} | "
                 f"{d['reference_robust_kept']} | {d['overlap_jaccard']:.3f} | {d['seconds']:.1f} |")
    s = rep["survivors"]
    L += ["", f"## Survivors: {s['n_survivors']} of {s['n_reference_robust']} reference-robust tiles", "", s["definition"] + ".",
          f"Total run time {rep['seconds_total']:.0f} s."]
    return "\n".join(L) + "\n"
