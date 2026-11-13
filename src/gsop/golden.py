"""Golden slice: a fixed 5,000-tile synthetic Earth, 50 runs, both bodies. Inputs are checked in (tests/golden/) and
hashed exactly. Outputs are compared with tolerance, never bit-for-bit: Windows and macOS use different BLAS and SIMD.
The data are synthetic. This proves the two machines compute the same thing, not that the science is right.
"""

from __future__ import annotations

import copy
import shutil
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import pipeline as P
from .config import load_all
from .provenance import ROOT, machine_info, read_json, sha256_file, write_json
from .runner import BodyRun, hash_frame
from .synthetic import ALL_COLUMNS, make_earth, target_profile

GOLDEN_DIR = ROOT / "tests" / "golden"
N_TILES, N_RUNS, SEED = 5000, 50, 11
TARGET_ROWS = {"golden_a": 100, "golden_b": 2500}


def golden_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    g = copy.deepcopy(cfg)
    g["run"]["runs"] = N_RUNS
    g["run"]["batch_runs"] = 25
    g["run"]["convergence_checkpoints"] = [25, 50]
    g["targets"]["moon"] = {t: {"lat": -89.0, "lon_e": 10.0, "source": "synthetic"} for t in TARGET_ROWS}
    g["targets"]["mars"] = {"golden_a": {"lat": 18.0, "lon_e": 77.0, "source": "synthetic"}}
    return g


def make_inputs(directory: Path = GOLDEN_DIR) -> None:
    """Regenerate the checked-in inputs. Maintainers only: a change here changes the expected output."""
    directory.mkdir(parents=True, exist_ok=True)
    earth = make_earth(N_TILES, SEED)
    earth.to_parquet(directory / "earth_slice.parquet", index=False)
    rows = []
    for tname, r in TARGET_ROWS.items():
        for c in ALL_COLUMNS:
            v = float(earth.loc[r, c]) * (1.0 + 0.05 * (1 if tname == "golden_b" else -1))
            rows.append({"target": tname, "col": c, "value": v, "spread": 0.0, "source": "synthetic",
                         "evidence_grade": "C", "window": "synthetic", "unavailable": False})
        for k, v in (("aux_lat", 18.0), ("aux_elevation_m", -2500.0), ("aux_thermal_inertia_si", 300.0)):
            rows.append({"target": tname, "col": k, "value": v, "spread": np.nan, "source": "synthetic",
                         "evidence_grade": "C", "window": "synthetic", "unavailable": False})
    pd.DataFrame(rows).to_parquet(directory / "targets_golden.parquet", index=False)
    write_json(directory / "INPUTS.sha256.json",
               {f: sha256_file(directory / f) for f in ("earth_slice.parquet", "targets_golden.parquet")})


def verify_inputs(directory: Path = GOLDEN_DIR) -> list[str]:
    want = read_json(directory / "INPUTS.sha256.json")
    return [f"{f}: sha256 differs" for f, h in want.items() if sha256_file(directory / f) != h]


def run_golden(workers: int = 1, directory: Path = GOLDEN_DIR, out: Path | None = None) -> dict[str, Any]:
    bad = verify_inputs(directory)
    if bad:
        raise RuntimeError("golden inputs changed: " + "; ".join(bad))
    cfg = golden_cfg(load_all())
    earth = pd.read_parquet(directory / "earth_slice.parquet")
    tp = P.load_target_profiles(directory / "targets_golden.parquet")
    result: dict[str, Any] = {"inputs_sha256": read_json(directory / "INPUTS.sha256.json"),
                              "machine": machine_info(), "synthetic": True, "bodies": {}}
    tmp = Path(tempfile.mkdtemp(prefix="gsop_golden_"))
    try:
        for body in ("moon", "mars"):
            tprofs = {k: v for k, v in tp.items() if k in cfg["targets"][body]}
            br = BodyRun(body, cfg, earth, tprofs, tmp / body, tmp / f"work_{body}", N_RUNS, workers, 8 * 2**30,
                         hash_frame(earth), use_store=False)
            br.run(("gates", "score", "simulate"))
            jobs = {}
            for name in br.summaries:
                d = tmp / body / name
                base = pd.read_parquet(d / "base_scores.parquet")
                mc = pd.read_parquet(d / "mc_summary.parquet")
                k = max(1, int(np.ceil(0.01 * len(base))))
                top = base.nlargest(k, "score")["tile_id"].tolist()
                mtop = mc.nlargest(k, "mc_mean")["tile_id"].tolist()
                jobs[name] = {
                    "n_gated": int(len(base)),
                    "score_first100": base.sort_values("tile_id")["score"].head(100).round(6).tolist(),
                    "score_mean": float(base["score"].mean()), "score_max": float(base["score"].max()),
                    "top1pct_base": sorted(top), "top1pct_mc_mean": sorted(mtop),
                    "robust_tiles": sorted(mc.loc[mc["robust"], "tile_id"].tolist()),
                    "mc_median_top20": dict(zip(map(str, mc.nlargest(20, "mc_median")["tile_id"]),
                                                mc.nlargest(20, "mc_median")["mc_median"].round(6))),
                }
            result["bodies"][body] = jobs
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if out:
        write_json(out, result)
    return result


def jaccard(a: list, b: list) -> float:
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if (a | b) else 1.0


def compare_golden(a: dict[str, Any], b: dict[str, Any], tol: dict[str, float]) -> list[dict[str, Any]]:
    """Returns a list of check rows {name, ok, detail}. Inputs must match exactly; outputs within tolerance."""
    rows = [{"name": "inputs identical (sha256)", "ok": a["inputs_sha256"] == b["inputs_sha256"], "detail": ""}]
    for body in sorted(set(a["bodies"]) | set(b["bodies"])):
        ja, jb = a["bodies"].get(body, {}), b["bodies"].get(body, {})
        rows.append({"name": f"{body}: same jobs", "ok": set(ja) == set(jb), "detail": f"{sorted(ja)} vs {sorted(jb)}"})
        for name in sorted(set(ja) & set(jb)):
            x, y = ja[name], jb[name]
            d = float(np.max(np.abs(np.array(x["score_first100"]) - np.array(y["score_first100"]))))
            rows.append({"name": f"{body}/{name}: base scores", "ok": d <= tol["score_abs"], "detail": f"max abs diff {d:.2e}"})
            for k in ("top1pct_base", "top1pct_mc_mean", "robust_tiles"):
                j = jaccard(x[k], y[k])
                rows.append({"name": f"{body}/{name}: {k} Jaccard", "ok": j >= tol["jaccard_min"], "detail": f"{j:.4f}"})
            common = set(x["mc_median_top20"]) & set(y["mc_median_top20"])
            dm = max((abs(x["mc_median_top20"][t] - y["mc_median_top20"][t]) for t in common), default=0.0)
            rows.append({"name": f"{body}/{name}: mc_median (top 20)", "ok": dm <= tol["mc_abs"], "detail": f"max abs diff {dm:.2e}"})
    return rows
