"""ROLE A: evaluate G1 to G3 (PREREG_A) and write runs/v2/metrics.json, ledger.json, claims_a.csv, results_a.md.

Needs: data/processed/earth_features_v2_6km.parquet, results/a_baseline/*, results/a_H/*, data/interim/a_thermal/*.json
Status strings are exactly PASS, FAIL, NOT TESTED. Nothing is tuned; a FAIL is reported as FAIL.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from gsop.config import load_all  # noqa: E402
from gsop.discover import known_points  # noqa: E402
from gsop.grid import haversine_km  # noqa: E402

V2 = ROOT / "runs" / "v2"
EARTH = ROOT / "data/processed/earth_features_v2_6km.parquet"
TH = ROOT / "data/interim/a_thermal"
NCOLS, NROWS = 5790, 2448
V1_ZIP_DIR = ROOT / "data/raw/v1/gsop_v1"
TARGETS = {"moon": ["connecting_ridge_c1", "shackleton_rim"], "mars": ["jezero"]}
GATE_PTS = {"rub_al_khali": (21.0, 51.0), "namib_sand_sea": (-24.8853, 15.4078), "amazon_basin": (-2.9, -60.0),
            "lonar": (19.98, 76.51), "haughton": (75.37, -89.68)}


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def rj(p: Path):
    return json.loads(Path(p).read_text()) if Path(p).exists() else None


CLAIMS: list[tuple[str, str, str, str]] = []


def claim(text: str, value, src: Path | str) -> None:
    p = Path(src)
    h = sha(p) if p.exists() else ""
    rel = str(p.relative_to(ROOT)).replace("\\", "/") if p.is_absolute() and str(p).startswith(str(ROOT)) else str(src)
    CLAIMS.append((text, str(value), rel, h))


def fmt(x, d=1):
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{d}f}"


# ------------------------------------------------------------------ G1
def g1(e: pd.DataFrame) -> dict:
    asm = rj(TH / "assemble.json")
    p1, p2 = rj(V2 / "logs" / "pull_state.json") or {}, rj(V2 / "logs" / "pull_state_rev.json") or {}
    cache = TH / "blocks"
    # a block is failed only if neither process cached all of its pieces: judged by the first process's final todo pass
    pull = {"finished": bool(p1.get("finished")), "failed": p1.get("failed", []), "rev_failed": p2.get("failed", [])}
    out = {"status": "NOT TESTED", "reasons": [], "points": {}}
    if asm is None:
        out["reasons"].append("assembly did not run")
        return out
    lat, lon = e["lat"].to_numpy(), e["lon"].to_numpy()
    for n, (la, lo) in GATE_PTS.items():
        d = haversine_km(la, lo, lat, lon)
        i = int(np.argmin(d))
        r = e.iloc[i]
        out["points"][n] = {"tile_id": int(r["tile_id"]), "km": float(d[i]), "th_mean_K": float(r["th_mean_K"]),
                            "th_max_K": float(r["th_max_K"]), "th_dn_K": float(r["th_dn_K"])}
    P = out["points"]
    conds = {}
    conds["coverage_band_ge_85pct"] = asm["band_valid_share"] >= 0.85
    fin = all(np.isfinite([p["th_mean_K"], p["th_max_K"]]).all() for p in P.values())
    conds["points_finite"] = bool(fin)
    if fin:
        conds["values_in_200_360_and_max_gt_mean"] = all(200 <= p["th_mean_K"] <= 360 and 200 <= p["th_max_K"] <= 360
                                                         and p["th_max_K"] > p["th_mean_K"] for p in P.values())
        conds["mean_270_320_four_sites"] = all(270 <= P[k]["th_mean_K"] <= 320 for k in ("rub_al_khali", "namib_sand_sea", "amazon_basin", "lonar"))
        conds["haughton_mean_220_270"] = 220 <= P["haughton"]["th_mean_K"] <= 270
        conds["rub_max_gt_amazon_max"] = P["rub_al_khali"]["th_max_K"] > P["amazon_basin"]["th_max_K"]
        conds["rub_dn_gt_amazon_dn"] = P["rub_al_khali"]["th_dn_K"] > P["amazon_basin"]["th_dn_K"]
    out["conditions"] = conds
    pull_ok = bool(pull.get("finished"))
    if not pull_ok:
        out["reasons"].append("pull_state.json does not say finished")
    if not conds or not fin:
        out["status"] = "FAIL" if pull_ok else "NOT TESTED"
    else:
        out["status"] = "PASS" if (all(conds.values()) and pull_ok) else ("FAIL" if pull_ok else "NOT TESTED")
    land = pd.read_parquet(TH / "land_ixiy.parquet")
    keys = set(zip((land["ix"] // 50 * 50).tolist(), (land["iy"] // 50 * 50).tolist()))
    flags = {tuple(map(int, f.stem.split("_")[1:3])) for f in (TH / "blocks").glob("done_*.flag")}
    out["land_blocks"] = len(keys)
    out["blocks_without_data"] = sorted(k for k in keys if k not in flags)
    out["failed_blocks"] = len(out["blocks_without_data"])
    out["asm"] = asm
    return out


# ------------------------------------------------------------------ G2
def val(mode: str, body: str):
    return rj(ROOT / "results" / f"a_{mode}" / body / "validation.json")


def g2() -> dict:
    out = {"clauses": {}}
    vm, vs = val("H", "moon"), val("H", "mars")
    bm, bs = val("baseline", "moon"), val("baseline", "mars")
    # (a)
    if vm and vm.get("results"):
        c = vm["results"]["negative_controls"]
        vals = {k: c[k] for k in ("namib_sand_sea", "rub_al_khali")}
        rp = {k: v.get("rank_pct") for k, v in vals.items()}
        ok = all(v is not None and v <= 25.0 for v in rp.values())
        miss = [k for k, v in rp.items() if v is None]
        out["clauses"]["a"] = {"status": "NOT TESTED" if miss else ("PASS" if ok else "FAIL"), "rank_pct": rp,
                               "status_by_control": {k: v["status"] for k, v in vals.items()}}
    else:
        out["clauses"]["a"] = {"status": "NOT TESTED", "reason": "Moon thermal run missing"}
    # (b)
    if vs and vs.get("results"):
        prim = vs["results"]["primary"]
        scorable = {k: v for k, v in prim.items() if v["status"] == "scored"}
        rec = {k: v["rank_pct"] >= 95.0 for k, v in scorable.items()}
        share = (sum(rec.values()) / len(rec)) if rec else None
        out["clauses"]["b"] = {"status": "NOT TESTED" if share is None else ("PASS" if share >= 0.6 else "FAIL"),
                               "recalled": rec, "n_scorable": len(rec), "share_scorable": share,
                               "share_all_six": sum(rec.values()) / len(prim), "rank_pct": {k: v.get("rank_pct") for k, v in prim.items()},
                               "status_by_site": {k: v["status"] for k, v in prim.items()}}
    else:
        out["clauses"]["b"] = {"status": "NOT TESTED", "reason": "Mars thermal run missing"}
    out["moon_layer2"] = {"status": "NOT TESTED", "reason": "Moon has 2 positives (lonar, haughton) and lonar is gated out"}
    # (c)
    if bm and bs and bm.get("results") and bs.get("results"):
        r = {"namib": bm["results"]["negative_controls"]["namib_sand_sea"]["rank_pct"],
             "rub": bm["results"]["negative_controls"]["rub_al_khali"]["rank_pct"],
             "mars_median": bs["results"]["primary_median_rank_pct"]}
        want = {"namib": 90.2, "rub": 75.6, "mars_median": 61.3}
        match = {k: (r[k] is not None and round(r[k], 1) == want[k]) for k in want}
        out["clauses"]["c"] = {"status": "PASS" if all(match.values()) else "FAIL", "values": r, "v1": want, "match": match}
    else:
        out["clauses"]["c"] = {"status": "NOT TESTED", "reason": "baseline run missing"}
    st = [c["status"] for c in out["clauses"].values()]
    out["status"] = "FAIL" if "FAIL" in st else ("NOT TESTED" if "NOT TESTED" in st else "PASS")
    return out


# ------------------------------------------------------------------ G3
def label_wrap(mask: np.ndarray) -> tuple[np.ndarray, int]:
    lab, n = ndimage.label(mask, structure=np.ones((3, 3), int))
    parent = list(range(n + 1))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for r in range(mask.shape[0]):
        if mask[r, 0]:
            for rr in (r - 1, r, r + 1):
                if 0 <= rr < mask.shape[0] and mask[rr, -1]:
                    a, b = find(int(lab[r, 0])), find(int(lab[rr, -1]))
                    if a != b:
                        parent[a] = b
    m = np.array([find(i) for i in range(n + 1)])
    return m[lab], n


def g3(e: pd.DataFrame, cfg: dict) -> dict:
    import a_score_v2 as S
    out = {"views": {}, "n_supported": 0}
    pts = known_points(cfg["known_sites"], "any")
    tid_all = e["tile_id"].to_numpy()
    lat, lon = e["lat"].to_numpy(), e["lon"].to_numpy()
    ixa, iya = e["ix"].to_numpy(), e["iy"].to_numpy()
    complete = True
    for body, tgts in TARGETS.items():
        br = None
        for t in tgts:
            d = ROOT / "results" / "a_H" / body / f"{t}__base"
            mcp = d / "mc_summary.parquet"
            v1p = V1_ZIP_DIR / "results" / body / f"{t}__base" / "mc_summary.parquet"
            if not mcp.exists() or not v1p.exists():
                out["views"][f"{t}__base"] = {"status": "NOT TESTED", "reason": "Monte Carlo output or v1 robust file missing"}
                complete = False
                continue
            mc = pd.read_parquet(mcp)
            v1 = pd.read_parquet(v1p)
            rob = mc.loc[mc["robust"], "tile_id"].to_numpy()
            v1rob = set(v1.loc[v1["robust"], "tile_id"].to_numpy().tolist())
            ras = np.zeros((NROWS, NCOLS), bool)
            ras[rob // NCOLS, rob % NCOLS] = True
            lab, _ = label_wrap(ras)
            ids = lab[rob // NCOLS, rob % NCOLS]
            br = br or S.make_br("H", body, 2000, 1)
            job = br.job(t, "base")
            fam = S.P.fam_arrays(job)
            famname = "temperature" if body == "moon" else "thermal_inertia"
            gt = job.earth["tile_id"].to_numpy()[job.gated_rows]
            th_sim = pd.Series(fam[famname], index=gt)
            med_all = float(np.median(fam[famname]))
            tile_row = pd.Series(np.arange(len(tid_all)), index=tid_all)
            regs = []
            for cid in np.unique(ids):
                tiles = rob[ids == cid]
                if tiles.size < 100:
                    continue
                rows = tile_row.reindex(tiles).to_numpy()
                dmin = np.inf
                for _, la, lo in pts:
                    dmin = min(dmin, float(haversine_km(la, lo, lat[rows], lon[rows]).min()))
                if dmin <= 100.0:
                    continue
                share_v1 = float(np.mean([int(x) in v1rob for x in tiles]))
                med_reg = float(th_sim.reindex(tiles).median())
                sup = bool(share_v1 >= 0.5 and med_reg >= med_all)
                regs.append({"n_tiles": int(tiles.size), "centroid_lat": float(lat[rows].mean()), "centroid_lon": float(lon[rows].mean()),
                             "share_in_v1_robust": share_v1, "median_thermal_sim": med_reg, "median_thermal_sim_all_gated": med_all,
                             "supported": sup, "km_to_nearest_known": dmin})
            out["views"][f"{t}__base"] = {"status": "computed", "n_robust_tiles_v2": int(rob.size), "n_robust_tiles_v1": len(v1rob),
                                          "n_regions": len(regs), "n_supported": int(sum(r["supported"] for r in regs)),
                                          "regions": sorted(regs, key=lambda r: -r["n_tiles"])[:30]}
            out["n_supported"] += int(sum(r["supported"] for r in regs))
    out["status"] = "NOT TESTED" if not complete else ("PASS" if out["n_supported"] >= 3 else "FAIL")
    return out


# ------------------------------------------------------------------ outputs
def main() -> None:
    cfg = load_all()
    cols = ["tile_id", "ix", "iy", "lat", "lon", "th_mean_K", "th_max_K", "th_dn_K", "th_valid_mean", "th_valid_max", "th_valid_dn"]
    e = pd.read_parquet(EARTH, columns=cols)
    G1 = g1(e)
    G2 = g2()
    G3 = g3(e, cfg)
    asm = G1.get("asm") or {}
    status = {"G1": G1["status"], "G2": G2["status"], "G3": G3["status"]}
    entries = []

    def add(id_, group, label, unit, value, display, src, note, status_=None):
        d = {"id": id_, "group": group, "label": label, "unit": unit, "value": value, "display": display,
             "source_file": src, "sha256": sha(ROOT / src) if (ROOT / src).exists() else "", "what_this_means_for_the_analogy": note}
        if status_:
            d["status"] = status_
        entries.append(d)
        claim(label, display, ROOT / src if (ROOT / src).exists() else src)

    pre = "runs/v2/PREREG_A.md"
    add("gate.G1", "gates", "G1 data pulled and smoke test", "status", status["G1"], status["G1"], "runs/v2/results_a.md",
        "Shows the thermal layer was built and gives plausible values at fixed points; it says nothing about whether the analogy holds.", status["G1"])
    add("gate.G2", "gates", "G2 scoring clauses a, b, c", "status", status["G2"], status["G2"], "runs/v2/results_a.md",
        "A FAIL here is a result about the score with these thermal layers.", status["G2"])
    add("gate.G3", "gates", "G3 supported regions, target 3 or more", "status", status["G3"], status["G3"], "runs/v2/results_a.md",
        "Counts regions that survive in the v2 run and are not contradicted by the thermal family.", status["G3"])
    for k, c in G2["clauses"].items():
        add(f"gate.G2{k}", "gates", f"G2 clause ({k})", "status", c["status"], c["status"], "runs/v2/results_a.md", "See results_a.md for the rule.", c["status"])
    add("gate.G2.moon_layer2", "gates", "Moon layer-2 held-out recall", "status", "NOT TESTED", "NOT TESTED", "runs/v2/results_a.md",
        "Moon has two positives and one is gated out, so no recall can be computed.", "NOT TESTED")
    if asm:
        add("earth.valid_tiles_all_three", "coverage", "Earth tiles valid in all three thermal features", "count", asm["valid_all_three"], f"{asm['valid_all_three']:,}", "data/interim/a_thermal/assemble.json", "Tiles without a value cannot be scored on thermal columns and are rejected as missing data.")
        add("earth.valid_th_mean_K", "coverage", "Earth tiles with a valid mean thermal value", "count", asm["valid_th_mean_K"], f"{asm['valid_th_mean_K']:,}", "data/interim/a_thermal/assemble.json", "Out of the v1 land tiles.")
        add("earth.band_valid_share", "coverage", "Share of land tiles 55S to 60N with valid th_mean_K", "ratio", asm["band_valid_share"], f"{asm['band_valid_share']:.4f}", "data/interim/a_thermal/assemble.json", "G1 coverage test threshold is 0.85.")
        add("earth.n_v1_land_tiles", "coverage", "v1 land tiles", "count", asm["n_v1_land_tiles"], f"{asm['n_v1_land_tiles']:,}", "data/interim/a_thermal/assemble.json", "Tile set is the v1 grid.")
    c = G2["clauses"]
    if "values" in c.get("c", {}):
        for k, v in c["c"]["values"].items():
            add(f"g2c.{k}", "baseline", f"terrain-only baseline {k}", "rank_pct", v, f"{v:.1f}", f"results/a_baseline/{'mars' if k == 'mars_median' else 'moon'}/validation.json", "Reproduction of the v1 number with the v1 config and Earth file.")
    if "rank_pct" in c.get("a", {}):
        for k, v in c["a"]["rank_pct"].items():
            add(f"g2a.{k}", "controls", f"thermal run control {k} rank percentile", "rank_pct", v, fmt(v), "results/a_H/moon/validation.json", "Negative control; the pre-registered maximum is 25.0.")
    if "rank_pct" in c.get("b", {}):
        for k, v in c["b"]["rank_pct"].items():
            add(f"g2b.{k}", "positives", f"thermal run Mars positive {k} rank percentile", "rank_pct", v, fmt(v), "results/a_H/mars/validation.json", f"Status {c['b']['status_by_site'][k]}.")
        add("g2b.share_scorable", "positives", "Mars positives recalled in top 5 percent, scorable denominator", "ratio", c["b"]["share_scorable"], fmt(c["b"]["share_scorable"], 4) if c["b"]["share_scorable"] is not None else "n/a", "results/a_H/mars/validation.json", "Pre-registered pass level is 0.6.")
    for name, p in G1.get("points", {}).items():
        for f in ("th_mean_K", "th_max_K", "th_dn_K"):
            add(f"g1.{name}.{f}", "smoke_test", f"{name} {f}", "K", p[f], fmt(p[f], 2), "data/processed/earth_features_v2_6km.parquet", f"Nearest v1 tile {p['tile_id']} at {p['km']:.1f} km.")
    for v, d in G3["views"].items():
        if d.get("status") == "computed":
            add(f"g3.{v}.n_regions", "regions", f"{v} v2 regions (at least 100 tiles, 100 km from known sites)", "count", d["n_regions"], str(d["n_regions"]), "runs/v2/results_a.md", "Region rule from PREREG_A.")
            add(f"g3.{v}.n_supported", "regions", f"{v} supported regions", "count", d["n_supported"], str(d["n_supported"]), "runs/v2/results_a.md", "Supported = half in v1 robust tiles and thermal family not below the gated median.")
    ref = rj(TH / "ref_targets.json")
    meta = {"schema_version": 1, "file": "runs/v2/metrics.json", "role": "A", "label": "v2 Earth thermal layer and gates; gate statuses are PASS, FAIL or NOT TESTED",
            "limits": ["Earth thermal layers are MODIS 8-day 1 km land surface temperature aggregated to 6 km; they are skin temperatures at satellite overpass times.",
                       "Comparison is by percentile rank inside each body's own set, never by absolute value.",
                       "Moon has 2 positives, so a Moon layer-2 recall is NOT TESTED."],
            "sources": [{"source_file": pre, "sha256": sha(ROOT / pre)}], "seed": 20261114}
    (V2 / "metrics.json").write_text(json.dumps({"meta": meta, "gates": {"G1": status["G1"], "G2": status["G2"], "G3": status["G3"]}, "entries": entries}, indent=1, sort_keys=False), encoding="utf-8")
    ledger = [
        {"id": "src.modis", "type": "source", "status": "used", "statement": "MODIS/061/MOD11A2 8-day 1 km LST, bands LST_Day_1km, LST_Night_1km, QC_Day, QC_Night, 2019 to 2023, QC bits 0-1 equal 0. MODIS/061/MOD11C3 is not in the Earth Engine catalog.", "source_file": "runs/v2/PREREG_A.md", "sha256": sha(ROOT / pre), "limit": "Skin temperature at overpass; cloud gaps; 1 km pixels averaged to 6 km."},
        {"id": "src.v1_earth", "type": "source", "status": "used", "statement": "v1 Earth feature file, 3,972,955 land tiles", "source_file": "data/raw/v1/gsop_v1/data/processed/earth_features_6km.parquet", "sha256": sha(V1_ZIP_DIR / "data/processed/earth_features_6km.parquet"), "limit": "v1 terrain limits apply (see v1 docs/UNVERIFIED.md)."},
        {"id": "src.v2_earth", "type": "output", "status": "built", "statement": "v1 columns plus th_mean_K, th_max_K, th_dn_K, valid shares and rank columns th_mean, th_max, th_ti", "source_file": "data/processed/earth_features_v2_6km.parquet", "sha256": sha(EARTH), "limit": "Not committed to git; rebuild with scripts/a_build_earth.py from the block cache."},
    ]
    if ref:
        for n, d in ref["files"].items():
            ledger.append({"id": f"src.{n}", "type": "source", "status": "used" if d["match"] else "hash_mismatch", "statement": f"{n} sha256 equals the Role B record: {d['match']}", "source_file": "data/reference/thermal_refs_files.csv (branch data/thermal-refs)", "sha256": d["sha256"], "limit": "Moon PRP is a modelled 2 cm depth temperature on about 500 m triangles; Mars TES is 3 km pixels."})
    ledger += [
        {"id": "limit.proxy", "type": "known_limit", "status": "open", "statement": "Mars thermal inertia is paired with the inverted Earth day-minus-night range, a proxy driven also by humidity, cloud, vegetation and soil moisture.", "source_file": "docs/refs_limits.md (branch data/thermal-refs)", "sha256": "", "limit": "Proxy"},
        {"id": "limit.moon_not_scored", "type": "unscored_property", "status": "open", "statement": "Moon ice_depth, diurnal range and cold-trap share are not scored; Mars surface temperature and Arcadia are not covered.", "source_file": "runs/v2/PREREG_A.md", "sha256": sha(ROOT / pre), "limit": "No Earth partner or no source."},
    ]
    (V2 / "ledger.json").write_text(json.dumps({"meta": {"schema_version": 1, "file": "runs/v2/ledger.json", "role": "A"}, "entries": ledger}, indent=1), encoding="utf-8")
    with open(V2 / "claims_a.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["claim", "number", "source_file", "sha256"])
        for r in CLAIMS:
            w.writerow(r)
    (TH / "gates_eval.json").write_text(json.dumps({"G1": G1, "G2": G2, "G3": G3}, indent=1, default=str))
    print(json.dumps(status))


if __name__ == "__main__":
    main()
