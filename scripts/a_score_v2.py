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
from gsop.config import load_all  # noqa: E402
from gsop.provenance import sha256_file  # noqa: E402
from gsop.runner import BodyRun  # noqa: E402

V1P = ROOT / "data/raw/v1/gsop_v1/data/processed"
V2_EARTH = ROOT / "data/processed/earth_features_v2_6km.parquet"
REF = ROOT / "data/interim/a_thermal/ref_targets.json"


def v2_cfg() -> dict:
    cfg = load_all()
    cfg = copy.deepcopy(cfg)
    cfg["weights"]["moon"]["temperature"]["columns"] = ["th_mean", "th_max", "t_mean", "t_coldest"]
    cfg["weights"]["mars"]["thermal_inertia"]["columns"] = ["th_ti", "ti_proxy", "dust_index"]
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


def make_br(mode: str, body: str, runs: int, workers: int) -> BodyRun:
    cfg = v2_cfg() if mode == "thermal" else load_all()
    cfg["purposes"]["profiles"][body] = ["base"]
    cfg["run"]["skip_profiles"] = {}          # only the base profile is run, so no profile is skipped
    ep = V2_EARTH if mode == "thermal" else V1P / "earth_features_6km.parquet"
    earth = pd.read_parquet(ep)
    tprofs = P.load_target_profiles(V1P / f"targets_{body}.parquet")
    if mode == "thermal":
        tprofs = add_thermal_targets(body, tprofs)
    res_dir = ROOT / "results" / f"a_{mode}" / body
    work = ROOT / "data/interim/a_mc" / mode / body
    return BodyRun(body, cfg, earth, tprofs, res_dir, work, runs, workers, float(psutil.virtual_memory().available),
                   sha256_file(ep), use_store=False)


def run(mode: str, body: str, runs: int, workers: int) -> None:
    br = make_br(mode, body, runs, workers)
    stages = ("gates", "score", "validate") if mode == "baseline" else ("gates", "simulate", "validate")
    br.run(stages)
    print(body, mode, "done; unscored:", br.unscored, flush=True)


if __name__ == "__main__":
    mode = sys.argv[1]
    bodies = sys.argv[2].split(",") if len(sys.argv) > 2 else ["moon", "mars"]
    runs = int(sys.argv[3]) if len(sys.argv) > 3 else int(load_all()["run"]["runs"])
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else (os.cpu_count() or 1)
    for b in bodies:
        run(mode, b, runs, workers)
