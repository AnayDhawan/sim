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
    A("### Mars primary median rank percentile (v1 rule, scorable and no-gated-tile sites as v1 reports them)\n")
    A("| Weighting | Median |\n|---|---|")
    for v in ORDER:
        r = (val.get((v, "mars")) or {}).get("results")
        if r:
            A(f"| {LABEL[v]} | {f1(r['primary_median_rank_pct'])} |")
            cl(f"mars primary median rank percentile, {v}", f"{r['primary_median_rank_pct']:.4f}", f"results/a_{v}/mars/validation.json")
    A("\nPREREG_A sha256 and addendum sha256 are stated at the top of this file and apply to every row above.\n")
    A("## What failed and what is NOT TESTED\n")
    for g, d in (("G1", G1), ("G2", G2), ("G3", G3)):
        A(f"- {g}: {d.get('status', 'NOT TESTED')}. {' '.join(d.get('reasons', []))}")
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
    (V2 / "results_a.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    with open(V2 / "claims_a.csv", "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for r in claims:
            w.writerow(r)
    print("wrote results_a.md,", len(claims), "claims appended")


if __name__ == "__main__":
    main()
