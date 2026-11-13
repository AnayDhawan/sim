"""compare, merge and verify-data."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from .golden import compare_golden, jaccard
from .provenance import read_json, sha256_file, verify_manifest, write_json, write_manifest


def compare_dirs(a: Path, b: Path, tol: dict[str, float], report_path: Path | None = None) -> list[dict[str, Any]]:
    """Compare two result folders (or two golden.json files) with tolerances. Not bit-for-bit."""
    rows: list[dict[str, Any]] = []
    if a.is_file() and b.is_file():
        rows = compare_golden(read_json(a), read_json(b), tol)
    else:
        for name in sorted({p.parent.name for p in a.glob("*/mc_summary.parquet")} &
                           {p.parent.name for p in b.glob("*/mc_summary.parquet")}):
            x, y = pd.read_parquet(a / name / "mc_summary.parquet"), pd.read_parquet(b / name / "mc_summary.parquet")
            m = x.merge(y, on="tile_id", suffixes=("_a", "_b"))
            rows.append({"name": f"{name}: shared candidate tiles", "ok": len(m) >= 0.99 * max(len(x), len(y)),
                         "detail": f"{len(m)} of {len(x)} / {len(y)}"})
            d = float((m["mc_median_a"] - m["mc_median_b"]).abs().max()) if len(m) else float("nan")
            rows.append({"name": f"{name}: mc_median", "ok": d <= tol["mc_abs"], "detail": f"max abs diff {d:.2e}"})
            j = jaccard(x.loc[x["robust"], "tile_id"].tolist(), y.loc[y["robust"], "tile_id"].tolist())
            rows.append({"name": f"{name}: robust set Jaccard", "ok": j >= tol["jaccard_min"], "detail": f"{j:.4f}"})
        ma, mb = a / "run_meta.json", b / "run_meta.json"
        if ma.exists() and mb.exists():
            ra, rb = read_json(ma), read_json(mb)
            rows.append({"name": "same config hash", "ok": ra["config_hash"] == rb["config_hash"], "detail": ""})
            rows.append({"name": "same Earth file hash", "ok": ra.get("earth_hash") == rb.get("earth_hash"), "detail": ""})
        if not rows:
            rows.append({"name": "nothing to compare", "ok": False, "detail": "no matching jobs or golden files"})
    if report_path:
        write_json(report_path, {"a": str(a), "b": str(b), "tolerances": tol, "checks": rows,
                                 "ok": all(r["ok"] for r in rows)})
    return rows


def merge_results(moon: Path, mars: Path, out: Path, force: bool = False) -> list[str]:
    """Merge the two bodies' export folders into results/all/ for the site. Returns warnings."""
    warns: list[str] = []
    metas = {}
    for body, d in (("moon", moon), ("mars", mars)):
        if not (d / "export" / "MANIFEST.json").exists():
            raise FileNotFoundError(f"{d}: no export/MANIFEST.json (run `gsop s8 export --body {body}`)")
        bad = verify_manifest(d / "export")
        if bad:
            raise RuntimeError(f"{d}: export manifest check failed: {bad}")
        metas[body] = read_json(d / "run_meta.json")
    a, b = metas["moon"], metas["mars"]
    if a["earth_hash"] != b["earth_hash"]:
        msg = "the two bodies were run on different Earth feature files"
        if not force:
            raise RuntimeError(msg + " (use --force only if you know why)")
        warns.append(msg)
    if a["config_hash"] != b["config_hash"]:
        msg = "config hash differs between the two runs"
        if not force:
            raise RuntimeError(msg + " (use --force only if you know why)")
        warns.append(msg)
    if a["git_commit"] != b["git_commit"]:
        warns.append(f"git commits differ: {a['git_commit']} vs {b['git_commit']}")
    if out.exists():
        shutil.rmtree(out)
    files = []
    views = []
    for body, d in (("moon", moon), ("mars", mars)):
        for f in sorted((d / "export").iterdir()):
            if f.name == "MANIFEST.json":
                continue
            dst = out / body / f.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dst)
            files.append(dst)
        views += [{**v, "body": body} for v in read_json(d / "export" / "index.json")["views"]]
    write_json(out / "index.json", {"schema_version": 1, "views": views,
                                    "run_meta": {"moon": {k: a[k] for k in ("git_commit", "config_hash", "earth_hash")},
                                                 "mars": {k: b[k] for k in ("git_commit", "config_hash", "earth_hash")}},
                                    "warnings": warns})
    files.append(out / "index.json")
    write_manifest(out, files)
    return warns


def verify_data(processed: Path) -> list[str]:
    """Check sha256 of data/processed files against MANIFEST.json."""
    man = processed / "MANIFEST.json"
    if not man.exists():
        return [f"{man} not found"]
    return verify_manifest(processed)


def write_data_manifest(processed: Path) -> Path:
    files = [p for p in processed.iterdir() if p.is_file() and p.name not in (".gitkeep", "MANIFEST.json")]
    return write_manifest(processed, files)
