"""ROLE A: write runs/v2/results_a.md and append the descriptive v1/H/S0/S1/S2/S3 rows to metrics.json and claims_a.csv.

Run after a_gates.py (needs data/interim/a_thermal/gates_eval.json) and a_secondary.py for each variant.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "runs" / "v2"
TH = ROOT / "data/interim/a_thermal"
PRE = "1758b132701ea831dea51c82ee9ebc3bd5c2c3a9e1544fdfe3eb7cd7a1e7992e"
ADD = "8e4fb4c8c555b30d748d763bd18b88d597b291663a2cab732a33d1e7511c7d92"
LABEL = {"baseline": "v1 (terrain only)", "B3": "v1 without illumination (post-PREREG sensitivity)", "H": "v2 headline H (thermal 0.5)",
         "S0": "S0 PREREG_A family weights (sensitivity)", "S1": "S1 equal per column (sensitivity)", "S2": "S2 thermal 0.75 (sensitivity)",
         "S3": "S3 H without illumination (post-PREREG sensitivity)"}
ORDER = ["baseline", "B3", "H", "S0", "S1", "S2", "S3"]


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def rj(p):
    p = Path(p)
    return json.loads(p.read_text()) if p.exists() else None


def f1(x):
    return "n/a" if x is None else f"{x:.1f}"


def chance(c):
    return "n/a" if not c else f"{c['mean']:.1f} ({c['p2.5']:.1f} to {c['p97.5']:.1f}; min {c['min']:.1f}, max {c['max']:.1f})"


def main() -> None:
    ev = rj(TH / "gates_eval.json") or {}
    G1, G2, G3 = ev.get("G1", {}), ev.get("G2", {}), ev.get("G3", {})
    asm = rj(TH / "assemble.json") or {}
    sec = {v: rj(ROOT / "results" / f"a_{v}" / "secondary.json") for v in ORDER}
    val = {(v, b): rj(ROOT / "results" / f"a_{v}" / b / "validation.json") for v in ORDER for b in ("moon", "mars")}
    claims: list[tuple[str, str, str, str]] = []

    def cl(text, num, src):
        p = ROOT / src
        claims.append((text, str(num), src, sha(p) if p.exists() else ""))

    L: list[str] = []
    A = L.append
    A("# results_a: Earth thermal layer from MODIS and the v2 gates (ROLE A)\n")
    A(f"- Pre-registration: `runs/v2/PREREG_A.md`, sha256 `{PRE}`.")
    A(f"- `runs/v2/PREREG_A_addendum1.md`, sha256 `{ADD}`, was added after PREREG_A and before any v2 result (no v2 control score, positive score or Mars median had been computed or read; a 50-run smoke test on partial data was deleted unread). It sets the headline weights (H), the secondary site statistic and the illumination sensitivity.")
    A("- Seed 20261114. Engine: v1 run code at commit a7d96d9 (see Deviations). Earth thermal source: MODIS/061/MOD11A2, 2019 to 2023.\n")
    A("## Gates\n")
    A("| Gate | Status | Basis |\n|---|---|---|")
    A(f"| G1 data pulled and smoke test | {G1.get('status', 'NOT TESTED')} | {json.dumps(G1.get('conditions', {}))} |")
    for k, name in (("a", "(a) Moon controls at most 25"), ("b", "(b) Mars recall at least 60%"), ("c", "(c) terrain-only baseline reproduces v1")):
        c = G2.get("clauses", {}).get(k, {"status": "NOT TESTED"})
        A(f"| G2 {name} | {c['status']} | {json.dumps({kk: vv for kk, vv in c.items() if kk != 'status'})[:300]} |")
    ml = G2.get("moon_layer2", {"status": "NOT TESTED", "reason": ""})
    A(f"| G2 Moon layer-2 recall | {ml['status']} | {ml['reason']} |")
    A(f"| G2 overall | {G2.get('status', 'NOT TESTED')} | FAIL if any clause FAIL |")
    A(f"| G3 supported regions (target 3 or more) | {G3.get('status', 'NOT TESTED')} | {G3.get('n_supported', 'n/a')} supported |")
    A("\nG2(a) cannot be met by construction under a best-of-35-tiles score; G2(b) passes by chance about 83% of the time. See ENGINE_AUDIT.md.\n")
    A("## Earth tiles\n")
    if asm:
        A(f"- v1 land tiles: {asm['n_v1_land_tiles']:,}. Valid in all three thermal features: {asm['valid_all_three']:,}. Valid `th_mean_K`: {asm['valid_th_mean_K']:,}. Share valid between 55 S and 60 N: {asm['band_valid_share']:.4f}.")
        cl("v1 land tiles", asm["n_v1_land_tiles"], "data/interim/a_thermal/assemble.json")
        cl("valid in all three thermal features", asm["valid_all_three"], "data/interim/a_thermal/assemble.json")
    A("")
    A("### Tiles with missing thermal values by latitude band\n")
    try:
        import numpy as np
        import pandas as pd
        e = pd.read_parquet(ROOT / "data/processed/earth_features_v2_6km.parquet", columns=["lat", "th_mean_K", "th_max_K", "th_dn_K"])
        edges = [-90, -80, -70, -60, -50, -40, -30, -20, -10, 0, 10, 20, 30, 40, 50, 60, 70, 80, 90]
        names = {-90: "Antarctica (south polar plateau)", -80: "Antarctica (interior, shelves and coast)",
                 -70: "Antarctica (coast and peninsula)", -60: "Southern Ocean margin (sub-Antarctic islands, Patagonia tip)",
                 60: "Arctic fringe", 70: "Arctic (Greenland, Arctic islands)", 80: "high Arctic (north Greenland, Ellesmere)"}
        A("| Latitude band | Land tiles | Missing th_mean_K | Missing share | Missing th_max_K | Note |")
        A("|---|---|---|---|---|---|")
        lat = e["lat"].to_numpy()
        for lo, hi in zip(edges[:-1], edges[1:]):
            m = (lat >= lo) & (lat < hi) if hi < 90 else (lat >= lo) & (lat <= hi)
            n = int(m.sum())
            if n == 0:
                continue
            mm = int(e["th_mean_K"].isna()[m].sum())
            mx = int(e["th_max_K"].isna()[m].sum())
            A(f"| {lo} to {hi} | {n:,} | {mm:,} | {mm / n:.3f} | {mx:,} | {names.get(lo, '')} |")
            cl(f"land tiles with missing th_mean_K, latitude {lo} to {hi}", mm, "data/processed/earth_features_v2_6km.parquet")
        vmin = float(np.nanmin(e["th_mean_K"]))
        A("")
        A(f"The lowest valid `th_mean_K` is {vmin:.2f} K. Tiles with no thermal value are left out of the Earth percentile set (it is built only from valid tiles) and are rejected as missing data when scoring. The polar plateau and the high-latitude interior are the least covered bands, so the coldest Earth tiles may be absent from the thermal ranking. A Moon polar value that ranks low within the Moon set is therefore compared with an Earth set that lacks the coldest Earth surfaces, and the low end of the Earth ranking is less reliable than the middle.\n")
        cl("lowest valid Earth th_mean_K", f"{vmin:.4f}", "data/processed/earth_features_v2_6km.parquet")
    except Exception as ex:  # noqa: BLE001
        A(f"Latitude-band table not available: {type(ex).__name__}: {ex}\n")
    A("")
    A("## Descriptive results, whatever the gate status\n")
    A("Percentiles are 100 * share of gated tiles of the view scoring below the site value. Best-of-radius is the v1 statistic (best gated tile within 20 km). Own tile is the tile nearest the site point. Chance = mean of 1000 shuffled-feature draws (seed 20261114) with the 2.5 to 97.5 percentile range and min to max. Mean over the body's targets. `gated_out` = no gated tile.\n")
    for body in ("moon", "mars"):
        A(f"### {body.capitalize()}\n")
        A("| Weighting | Site | Role | Best-of-radius | chance (best) | Own tile | chance (own) |\n|---|---|---|---|---|---|---|")
        for v in ORDER:
            s = (sec.get(v) or {}).get("bodies", {}).get(body)
            if not s:
                continue
            for name, d in s.items():
                t0 = next(iter(d["targets"].values()), None)
                cb = chance(t0["chance_best"]) if t0 else "n/a"
                co = chance(t0["chance_own"]) if t0 else "n/a"
                A(f"| {LABEL[v]} | {name} | {d['role']} | {f1(d.get('mean_best_of_radius_pct'))} | {cb} | {f1(d.get('mean_own_tile_pct'))} | {co} |")
                src = f"results/a_{v}/secondary.json"
                if d.get("mean_best_of_radius_pct") is not None:
                    cl(f"{body} {name} best-of-radius percentile, {v}", f"{d['mean_best_of_radius_pct']:.4f}", src)
                if d.get("mean_own_tile_pct") is not None:
                    cl(f"{body} {name} own-tile percentile, {v}", f"{d['mean_own_tile_pct']:.4f}", src)
        A("")
        A("Chance column shows the first target's draw summary; the mean over targets is in `results/a_<variant>/secondary.json`.\n")
    A("### Mars positives, own-tile percentile (single nearest tile) against chance\n")
    A("Own tile = the tile nearest the site point, percentile among the gated tiles of the Jezero view. Chance = 1000 shuffled-feature draws, seed 20261114: mean (2.5 to 97.5 percentile range; min to max). `gated_out` = the nearest tile is rejected by a gate, so there is no number.\n")
    A("| Weighting | Site | Own tile | Chance, own tile | Best-of-radius | Chance, best-of-radius |")
    A("|---|---|---|---|---|---|")
    for v in ORDER:
        s = (sec.get(v) or {}).get("bodies", {}).get("mars")
        if not s:
            continue
        for name, d in s.items():
            if d["role"] != "positive":
                continue
            t0 = next(iter(d["targets"].values()), None)
            if not t0:
                continue
            ownv = f1(t0.get("own_tile_pct")) if t0.get("own_status") == "scored" else "gated_out"
            A(f"| {LABEL[v]} | {name} | {ownv} | {chance(t0['chance_own'])} | {f1(t0.get('best_of_radius_pct'))} | {chance(t0['chance_best'])} |")
    A("")
    A("### Mars primary median rank percentile (v1 rule, scorable and no-gated-tile sites as v1 reports them)\n")
    A("| Weighting | Median |\n|---|---|")
    for v in ORDER:
        r = (val.get((v, "mars")) or {}).get("results")
        if r:
            A(f"| {LABEL[v]} | {f1(r['primary_median_rank_pct'])} |")
            cl(f"mars primary median rank percentile, {v}", f"{r['primary_median_rank_pct']:.4f}", f"results/a_{v}/mars/validation.json")
    A("\nPREREG_A sha256 and addendum sha256 are stated at the top of this file and apply to every row above.\n")
    A("## What failed and what is NOT TESTED\n")
    c1 = G1.get("conditions", {})
    P1 = G1.get("points", {})
    A(f"- G1: {G1.get('status', 'NOT TESTED')}. Coverage between 55 S and 60 N is {asm.get('band_valid_share', float('nan')):.4f} against the pre-registered 0.85 ({'met' if c1.get('coverage_band_ge_85pct') else 'not met'}). At the five smoke-test points: " + "; ".join(
        (f"{k} th_mean {p['th_mean_K']:.1f} K, th_max {p['th_max_K']:.1f} K, th_dn {p['th_dn_K']:.1f} K" if p['th_mean_K'] == p['th_mean_K'] else f"{k} has no valid value") for k, p in P1.items())
      + f". {G1.get('failed_blocks', 'n/a')} of {G1.get('land_blocks', 'n/a')} land blocks returned no data (south-polar rows; Earth Engine could not transform them).")
    for k, p in P1.items():
        for f in ("th_mean_K", "th_max_K", "th_dn_K"):
            if p[f] == p[f]:
                cl(f"smoke test {k} {f}", f"{p[f]:.4f}", "data/processed/earth_features_v2_6km.parquet")
    ca, cb = G2.get("clauses", {}).get("a", {}), G2.get("clauses", {}).get("b", {})
    if ca.get("rank_pct"):
        A("- G2(a): " + ", ".join(f"{k} {f1(v)}" for k, v in ca["rank_pct"].items()) + " on the v1 site statistic (best-of-radius), maximum allowed 25.0.")
    if cb.get("n_scorable") is not None:
        A(f"- G2(b): {sum(cb['recalled'].values())} of {cb['n_scorable']} scorable Mars positives at or above the 95th percentile (needs 60 percent). Not scorable: " + ", ".join(k for k, s in cb["status_by_site"].items() if s != "scored") + ".")
    for vname, d in G3.get("views", {}).items():
        if d.get("status") == "computed":
            A(f"- G3 {vname}: {d['n_regions']} regions of at least 100 robust tiles and 100 km from known sites, {d['n_supported']} supported ({d['n_robust_tiles_v2']:,} robust tiles in v2, {d['n_robust_tiles_v1']:,} in v1).")
    A("")
    A("### Reading\n")
    sb, sh = (sec.get("baseline") or {}).get("bodies", {}), (sec.get("H") or {}).get("bodies", {})
    def g(s, body, site, key):
        return ((s.get(body) or {}).get(site) or {}).get(key)
    A("- Descriptive change from v1 to H (thermal 0.5): " + "; ".join(
        f"{lab} best-of-radius {f1(g(sb, b, s, 'mean_best_of_radius_pct'))} to {f1(g(sh, b, s, 'mean_best_of_radius_pct'))}, own tile {f1(g(sb, b, s, 'mean_own_tile_pct'))} to {f1(g(sh, b, s, 'mean_own_tile_pct'))}"
        for lab, b, s in (("Moon Namib", "moon", "namib_sand_sea"), ("Moon Rub' al Khali", "moon", "rub_al_khali"), ("Moon Haughton", "moon", "haughton"), ("Mars Atacama", "mars", "atacama_salars"), ("Mars MDRS", "mars", "mdrs_utah"), ("Mars Ladakh", "mars", "ladakh_puga"))) + ".")
    A("- Chance level for the best-of-radius statistic is about 97, so every best-of-radius value above sits below it. The own-tile statistic has chance level about 50.")
    A("- The thermal columns lower the Moon controls and the Mars positives together. Two causes are untested hypotheses: the thermal pair is a coarse physical match, and the Earth thermal set lacks the tiles with no thermal value (see the coverage finding).")
    A("- Coverage finding: under the pre-registered QC rule (QC bits 0-1 equal 0) the composites over central Australia carry bits 0-1 equal to 1 (other quality), so those tiles have no thermal value (checked at one point, 133 E 25 S, where all 229 composites carry bits 0-1 equal to 1; the regional validity shares are in the table above). Indonesia, the Amazon, parts of Siberia and the tropics lose most tiles to cloud and quality flags. Missing tiles are rejected as missing data, so the Earth set that is scored is not a random sample of Earth. This was not corrected; a rerun with bits 0-1 in {0, 1} would be a separate, labelled sensitivity.")
    A("- The Moon thermal target ranks come from only the two polar PRP sites inside a south-polar set; the Mars target from Jezero alone. Neither is checked against any positive.\n")
    A("### Not run or not tested\n")
    A("- Moon layer-2 recall: NOT TESTED (two positives, one gated out).")
    A("- Arcadia: NOT TESTED (no centre in the v1 target list, no thermal reference).")
    A("- Moon ice depth, diurnal range, cold-trap share; Mars surface temperature: not scored (no Earth partner or no source).")
    A("- Failed Earth Engine blocks stay NaN and their tiles are rejected as missing data; see STATUS_A.md for the count.\n")
    A("## Deviations\n")
    A("1. Engine commit. PREREG_A named origin/main ca9a816. The v1 results were produced by a7d96d9 (local branch `integrate`, 59 commits ahead, not on origin). The baseline only reproduces v1 with a7d96d9, so its `src`, `config` and `tests` were imported into this branch.")
    A("2. Config wording. PREREG_A said the thermal columns replace the family columns. The config keeps the dropped v1 columns in the family lists and adds the thermal columns, so the v1 `drop_columns` lists need no change. The active columns are the same.")
    A("3. Weights. The headline weighting is the addendum's H, not the family weights written in PREREG_A. The PREREG_A weighting is reported as S0.")
    A("4. Mars radius. PREREG_A wrote 3389.5 km; Role B used 3396.0 km (label). Both give the same 38 pixels at Jezero and the same medians.")
    A("5. Earth Engine blocks. 50 x 50 tile blocks, split into halves where a block exceeded the memory limit or could not be transformed near the poles; two worker processes. Not outcome-affecting.")
    A("6. Profiles. Only the base profile was run, as PREREG_A states.")
    A("7. Two log files were committed by mistake in 978910c and untracked later (no secrets).")
    mp = V2 / "metrics.json"
    m = json.loads(mp.read_text(encoding="utf-8"))
    m["meta"]["preregistration_hashes"] = {"PREREG_A": PRE, "PREREG_A_addendum1": ADD}
    m["meta"]["limits"].append("G2(a) cannot be met by construction under a best-of-35-tiles score; G2(b) passes by chance about 83% of the time. See ENGINE_AUDIT.md.")
    m["meta"]["limits"].append("Under the pre-registered QC rule, tiles in central Australia, Indonesia, the Amazon and much of the high latitudes have no thermal value and are not scored.")
    for v in ORDER:
        sv = (sec.get(v) or {}).get("bodies", {})
        for body, ss in sv.items():
            for site, d in ss.items():
                for key, lab in (("mean_best_of_radius_pct", "best-of-radius percentile"), ("mean_own_tile_pct", "own-tile percentile")):
                    if d.get(key) is None:
                        continue
                    m["entries"].append({"id": f"desc.{v}.{body}.{site}.{key}", "group": "descriptive", "label": f"{LABEL[v]}: {body} {site} {lab}",
                                         "unit": "rank_pct", "value": d[key], "display": f"{d[key]:.1f}", "source_file": f"results/a_{v}/secondary.json",
                                         "sha256": sha(ROOT / "results" / f"a_{v}" / "secondary.json"),
                                         "what_this_means_for_the_analogy": "Descriptive. The best-of-radius statistic has a chance level near 97; the own-tile statistic near 50. Not a gate."})
        r = (val.get((v, "mars")) or {}).get("results")
        if r:
            m["entries"].append({"id": f"desc.{v}.mars.primary_median", "group": "descriptive", "label": f"{LABEL[v]}: Mars primary median rank percentile",
                                 "unit": "rank_pct", "value": r["primary_median_rank_pct"], "display": f"{r['primary_median_rank_pct']:.1f}",
                                 "source_file": f"results/a_{v}/mars/validation.json", "sha256": sha(ROOT / "results" / f"a_{v}" / "mars" / "validation.json"),
                                 "what_this_means_for_the_analogy": "Descriptive, v1 site statistic."})
    mp.write_text(json.dumps(m, indent=1), encoding="utf-8")
    (V2 / "results_a.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    with open(V2 / "claims_a.csv", "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for r in claims:
            w.writerow(r)
    print("wrote results_a.md,", len(claims), "claims appended")


if __name__ == "__main__":
    main()
