"""Export (s8, minimal): JSON per view for the site, with a sha256 manifest. Schema: docs/RESULTS_SCHEMA.md.

Verbatim numbers only. Each file is kept under 3 MB (the site limit); a larger file is truncated by rank and flagged.
sha256 manifest pattern recycled from the IRIS export_web.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .fidelity import fidelity, ledger_table
from .provenance import _jsonable, read_json, write_json, write_manifest

MAX_BYTES = 3 * 1024 * 1024
TOP_N = 500
SCHEMA_VERSION = 1


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(df.to_json(orient="records", double_precision=6))


def export_job(job_dir: Path, out_dir: Path, name: str, summary: dict[str, Any]) -> list[Path]:
    mc = pd.read_parquet(job_dir / "mc_summary.parquet")
    base = pd.read_parquet(job_dir / "base_scores.parquet")
    if "illum_match" in base:
        mc = mc.merge(base[["tile_id", "illum_match"]], on="tile_id", how="left")
    mc = mc.sort_values(["robust", "mc_median"], ascending=False).head(TOP_N)
    cols = [c for c in ("tile_id", "lat", "lon", "score_base", "mc_median", "mc_p05", "mc_p95", "rank_pct_p05",
                        "rank_pct_p50", "rank_pct_p95", "freq_top1", "freq_top5", "freq_top10", "robust",
                        "illum_match") if c in mc]
    doc = {"schema_version": SCHEMA_VERSION, "body": summary["body"], "target": summary["target"],
           "profile": summary["profile"], "confidence": summary["confidence"],
           "fails_own_gate": summary["fails_own_gate"], "runs": summary.get("runs"),
           "n_robust": summary.get("n_robust"), "n_gated_tiles": summary["gates"]["n_passed"],
           "candidates": _records(mc[cols])}
    while len(json.dumps(doc, default=_jsonable)) > MAX_BYTES and len(doc["candidates"]) > 10:
        doc["candidates"] = doc["candidates"][: len(doc["candidates"]) // 2]
        doc["truncated_to_fit_3mb"] = True
    p = out_dir / f"candidates__{name}.json"
    write_json(p, doc)
    conv = out_dir / f"convergence__{name}.json"
    shutil.copyfile(job_dir / "convergence.json", conv)
    return [p, conv]


def export_body(body: str, res_dir: Path, ledger: dict[str, Any], summaries: dict[str, dict[str, Any]],
                unscored: dict[str, str], profiles: list[str]) -> Path:
    out = res_dir / "export"
    out.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    meta_rows = []
    for name, s in summaries.items():
        job_dir = res_dir / name
        if not (job_dir / "mc_summary.parquet").exists():
            continue
        files += export_job(job_dir, out, name, s)
        fid = fidelity(ledger, body, s["profile"])
        meta_rows.append({"name": name, "target": s["target"], "profile": s["profile"],
                          "confidence": s["confidence"], "fails_own_gate": s["fails_own_gate"],
                          "fidelity": fid["fidelity"], "n_robust": s.get("n_robust"),
                          "dropped_columns": s["dropped_columns"]})
    write_json(out / "fidelity.json", {"body": body, "relevance_provisional": True,
                                       "per_purpose": {p: fidelity(ledger, body, p) for p in profiles},
                                       "ledger": ledger_table(ledger, body),
                                       "note": "Reported beside the score. Never multiplied into it."})
    write_json(out / "index.json", {"schema_version": SCHEMA_VERSION, "body": body, "views": meta_rows,
                                    "unscored": unscored})
    files += [out / "fidelity.json", out / "index.json"]
    if (res_dir / "validation.json").exists():
        shutil.copyfile(res_dir / "validation.json", out / "validation.json")
        files.append(out / "validation.json")
    write_manifest(out, files)
    return out
