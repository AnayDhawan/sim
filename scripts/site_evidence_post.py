#!/usr/bin/env python
"""Role C post-processing: gate summary, ledger_c.json, claims_c.csv, chip credits.

Reads data/evidence/site_measurements.csv (or --src). Writes:
  data/evidence/ledger_c.json
  runs/v2/claims_c.csv
  public/img/sites/credits.json
  runs/v2/cache/summary.json   (git-ignored; numbers quoted in docs come from here)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from site_evidence import CACHE, CHIP_DIR, CREDIT, META, slugify  # noqa: E402

SRC = ROOT / "data" / "evidence" / "site_measurements.csv"
LEDGER = ROOT / "data" / "evidence" / "ledger_c.json"
CLAIMS = ROOT / "runs" / "v2" / "claims_c.csv"

PRIMARY = [
    ("cop_dem", "elevation", "mean"), ("cop_dem", "elevation", "min"), ("cop_dem", "elevation", "max"),
    ("cop_dem", "relief", "p95_minus_p5"), ("cop_dem", "slope", "mean"), ("cop_dem", "slope", "p90"),
    ("cop_dem", "roughness", "std_of_slope"),
    ("dem_crosscheck", "elevation_diff_alos_minus_cop", "mean"),
    ("mod11a2", "lst_day_mean", "mean"), ("mod11a2", "lst_night_mean", "mean"),
    ("mod11a2", "lst_day_max8d", "mean"), ("mod11a2", "lst_night_min8d", "mean"),
    ("mod11a2", "lst_day_night_diff", "mean_day_minus_mean_night"),
    *[("aster_ged", f"emissivity_band{i}", "mean") for i in range(10, 15)],
    ("aster_ged", "qi_silica_proxy", "ratio_eps11sq_over_eps10_eps12"),
    ("s2", "ndvi", "mean"), ("worldcover", "bare_fraction", "fraction"),
    ("s1", "vv_db", "mean"), ("s1", "vh_db", "mean"),
    ("s2_chip", "chip_available", "flag"),
]
GROUPS = {"terrain": ("cop_dem", "dem_crosscheck"), "temperature": ("mod11a2",), "emissivity": ("aster_ged",),
          "cover": ("s2", "worldcover"), "radar": ("s1",), "chip": ("s2_chip",)}


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(SRC))
    ap.add_argument("--no-write", action="store_true", help="summary only")
    a = ap.parse_args()
    src = Path(a.src)
    with src.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    src_hash = sha256_file(src)
    rel_src = src.relative_to(ROOT).as_posix() if src.is_relative_to(ROOT) else src.as_posix()

    # ---- per-row (site_name, body) coverage at 10 km
    by_site: dict[tuple, dict] = defaultdict(dict)
    for r in rows:
        if r["radius_km"] != "10":
            continue
        key = (r["site_name"], r["body"])
        k3 = (r["dataset"], r["variable"], r["stat"])
        if k3 in PRIMARY:
            by_site[key][k3] = r["value"] != ""
        if k3 == ("s2_chip", "chip_clear_fraction", "fraction"):
            by_site[key][("s2_chip", "chip_available", "flag")] = r["note"].startswith("chip saved")
    full = part = none = passing = 0
    group_missing: dict[str, int] = defaultdict(int)
    per_site = {}
    for key, d in by_site.items():
        have = sum(1 for p in PRIMARY if d.get(p))
        per_site[f"{key[0]} [{key[1]}]"] = have
        full += have == len(PRIMARY)
        none += have == 0
        part += 0 < have < len(PRIMARY)
        passing += have >= 20
        for gname, dss in GROUPS.items():
            if not any(d.get(p) for p in PRIMARY if p[0] in dss):
                group_missing[gname] += 1
    failed = sorted({(r["site_name"], r["dataset"], r["note"]) for r in rows if r["stat"] == "FAILED"})
    summary = dict(rows=len(rows), site_rows=len(by_site), primary_vars=len(PRIMARY), full=full, partial=part,
                   none=none, passing_20_of_24=passing, gc2_pass=passing >= 110, groups_all_null=dict(group_missing),
                   failed_tasks=[list(x) for x in failed], per_site=per_site)
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "per_site"}, indent=1))
    if a.no_write:
        return 0

    # ---- ledger (O2)
    ledger = []
    for ds, meta in META.items():
        sub = [r for r in rows if r["dataset"] == ds]
        if not sub:
            continue
        buf = [",".join(sub[0].keys())]
        import io
        s = io.StringIO()
        w = csv.DictWriter(s, fieldnames=list(sub[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(sub)
        pulled = sorted(r["pulled_utc"] for r in sub if r["pulled_utc"])
        ledger.append(dict(
            dataset=ds, product=meta["product"], version=meta["version"], doi_or_url=meta["doi"],
            date_range=meta["dates"], date_pulled_first=pulled[0] if pulled else "",
            date_pulled_last=pulled[-1] if pulled else "", rows=len(sub),
            null_rows=sum(1 for r in sub if r["value"] == ""),
            output_file=rel_src, sha256_of_dataset_rows=hashlib.sha256(s.getvalue().encode("utf-8")).hexdigest(),
            sha256_method="rows of this dataset, file column order and row order, CSV, LF line endings, UTF-8"))
    LEDGER.write_text(json.dumps(dict(source_file=rel_src, source_sha256=src_hash, datasets=ledger), indent=1) + "\n",
                      encoding="utf-8")

    # ---- claims: one row per non-null measurement row
    CLAIMS.parent.mkdir(parents=True, exist_ok=True)
    with CLAIMS.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["claim", "number", "source_file", "sha256"])
        for r in rows:
            if r["value"] == "":
                continue
            claim = (f"{r['site_name']} [{r['body']}] r={r['radius_km']}km coord_flag={r['coord_flag']} "
                     f"{r['dataset']} {r['variable']} {r['stat']} ({r['units']})")
            w.writerow([claim, r["value"], rel_src, src_hash])
        for k in ("rows", "site_rows", "full", "partial", "none", "passing_20_of_24"):
            w.writerow([f"gate summary: {k}", summary[k], "runs/v2/cache/summary.json (derived from " + rel_src + ")", src_hash])

    # ---- credits.json
    sites = {}
    total = 0
    for p in sorted((CACHE / "chips").glob("*.json")):
        st = json.loads(p.read_text(encoding="utf-8"))
        jp = CHIP_DIR / f"{st['slug']}.jpg"
        if jp.exists():
            total += jp.stat().st_size
        sites[st["slug"]] = dict(status=st["status"], clear_fraction=st["clear_fraction"],
                                 scene_count=st["scene_count"], credit=CREDIT if st["status"] == "ok" else None)
    (CHIP_DIR / "credits.json").write_text(json.dumps(dict(
        credit=CREDIT, window="2024-01-01 to 2025-12-31", product="COPERNICUS/S2_SR_HARMONIZED",
        box="20 km x 20 km centred on the site, 512 x 512 px", sites=sites), indent=1) + "\n", encoding="utf-8")
    print("chips:", sum(1 for s in sites.values() if s["status"] == "ok"), "ok of", len(sites),
          "| total bytes", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
