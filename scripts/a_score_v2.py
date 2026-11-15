"""ROLE A: re-score with the v1 engine (a7d96d9) plus thermal columns, and the terrain-only baseline (PREREG_A).

  python scripts/a_score_v2.py baseline   -> results/a_baseline/<body>/   (v1 config, v1 Earth file, base profile only)
  python scripts/a_score_v2.py thermal    -> results/a_thermal/<body>/    (v2 weights, v2 Earth file, base profile, Monte Carlo)

Only the base profile is run (PREREG_A). Seed and runs come from config/run.yaml (20261114, 2000).
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from gsop import pipeline as P  # noqa: E402
from gsop import weights as _W  # noqa: E402
P.W = _W
from gsop.config import load_all  # noqa: E402
from gsop.provenance import sha256_file  # noqa: E402
from gsop.runner import BodyRun  # noqa: E402

V1P = ROOT / "data/raw/v1/gsop_v1/data/processed"
V2_EARTH = ROOT / "data/processed/earth_features_v2_6km.parquet"
REF = ROOT / "data/interim/a_thermal/ref_targets.json"


THERMAL_FAM = {"moon": "temperature", "mars": "thermal_inertia"}
VARIANTS = ("baseline", "B3", "S0", "H", "S1", "S2", "S3")   # PREREG_A addendum 1: H is the headline; S0..S3, B3 sensitivity


def v2_cfg(variant: str = "S0", body: str = "moon") -> dict:
    """Config for a variant. baseline: v1 as is. B3: v1 without the Moon illumination family. S0: PREREG_A weighting with the
    thermal columns added to their families. H, S1, S2, S3: addendum 1 column weightings (S3 = H without illumination)."""
    cfg = copy.deepcopy(load_all())
    if variant == "baseline":
        return cfg
    if variant != "B3":
        cfg["weights"]["moon"]["temperature"]["columns"] = ["th_mean", "th_max", "t_mean", "t_coldest"]
        cfg["weights"]["mars"]["thermal_inertia"]["columns"] = ["th_ti", "ti_proxy", "dust_index"]
    if variant in ("B3", "S3") and body == "moon":
        d = cfg["run"]["drop_columns"]
        d["moon"] = list(d["moon"]) + ["sun_max_elev", "sun_low_share"]
    if variant in ("H", "S1", "S2", "S3"):
        drop = P.drop_columns_for(cfg["run"], body, cfg["weights"][body])
        act = P.active_body_cfg(cfg["weights"][body], drop)
        tf = THERMAL_FAM[body]
        n = {f: len(v["columns"]) for f, v in act.items()}
        n_ter = sum(c for f, c in n.items() if f != tf)
        n_all = sum(n.values())
        share = {"H": 0.5, "S3": 0.5, "S2": 0.75}.get(variant)
        w = {}
        for f in act:
            if variant == "S1":
                w[f] = n[f] / n_all
            elif f == tf:
                w[f] = share
            else:
                w[f] = (1 - share) * n[f] / n_ter
        for f, v in cfg["weights"][body].items():
            if f in w:
                v["paper_score"], v["matchability"] = w[f], 1.0
                v["range"] = [0.7 * w[f], 1.3 * w[f]]
                v["published"] = w[f]
    return cfg


def add_thermal_targets(body: str, tprofs: dict) -> dict:
    ref = json.loads(REF.read_text())
    if body == "moon":
        for tgt in ("connecting_ridge_c1", "shackleton_rim"):
            for col in ("th_mean", "th_max"):
                s = ref["moon"][col]["sites"][tgt]
                tprofs[tgt]["cols"][col] = {"value": s["rank_median"], "spread": s["rank_spread_iqr_1349"],
                                            "source": f"PRP {col} rank, R=5 km (PREREG_A)", "evidence_grade": "B", "window": "5 km"}
    else:
        s = ref["mars"]["sites"]["prereg_3389.5"]
        tprofs["jezero"]["cols"]["th_ti"] = {"value": s["rank_median"], "spread": s["rank_spread_iqr_1349"],
                                             "source": "TES TI day+night rank, R=10 km (PREREG_A), proxy",
                                             "evidence_grade": "C", "window": "10 km"}
    return tprofs


def make_br(variant: str, body: str, runs: int, workers: int) -> BodyRun:
    cfg = v2_cfg(variant, body)
    cfg["purposes"]["profiles"][body] = ["base"]
    cfg["run"]["skip_profiles"] = {}          # only the base profile is run, so no profile is skipped
    thermal = variant not in ("baseline", "B3")
    ep = V2_EARTH if thermal else V1P / "earth_features_6km.parquet"
    earth = pd.read_parquet(ep)
    tprofs = P.load_target_profiles(V1P / f"targets_{body}.parquet")
    if thermal:
        tprofs = add_thermal_targets(body, tprofs)
    res_dir = ROOT / "results" / f"a_{variant}" / body
    work = ROOT / "data/interim/a_mc" / variant / body
    return BodyRun(body, cfg, earth, tprofs, res_dir, work, runs, workers, float(psutil.virtual_memory().available),
                   sha256_file(ep), use_store=False)


def run(variant: str, body: str, runs: int, workers: int) -> None:
    br = make_br(variant, body, runs, workers)
    stages = ("gates", "simulate", "validate") if variant == "H" else ("gates", "score", "validate")
    br.run(stages)
    w = {t: {k: round(v, 6) for k, v in P.W.derive_weights(br.job(t, "base").body_cfg).items()} for t in br.targets}
    print(body, variant, "done; unscored:", br.unscored, "derived weights", next(iter(w.values())) if w else None, flush=True)


if __name__ == "__main__":
    mode = sys.argv[1]          # one of VARIANTS
    assert mode in VARIANTS, mode
    bodies = sys.argv[2].split(",") if len(sys.argv) > 2 else ["moon", "mars"]
    runs = int(sys.argv[3]) if len(sys.argv) > 3 else int(load_all()["run"]["runs"])
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else (os.cpu_count() or 1)
    for b in bodies:
        run(mode, b, runs, workers)
