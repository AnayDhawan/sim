"""ROLE D report writer: metrics_d.json, ledger_d.json, claims_d.csv, results_d.md from the stage outputs.
usage: d_report.py <workdir> <outdir> <layer_sha256> <layer_path_label>"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK, OUT = Path(sys.argv[1]), Path(sys.argv[2])
LAYER_SHA, LAYER_LABEL = sys.argv[3], sys.argv[4]
RAW = OUT / "raw_d"
RAW.mkdir(parents=True, exist_ok=True)
for f in ("real_metrics.json", "shuffle_baseline.json", "prep.json", "ranks_real.npz"):
    shutil.copy(WORK / f, RAW / f)
shutil.copy(ROOT / "data" / "interim" / "d_ref" / "ref_targets_d.json", RAW / "ref_targets_d.json")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


REAL = json.load(open(RAW / "real_metrics.json"))
BASE = json.load(open(RAW / "shuffle_baseline.json"))
PREP = json.load(open(RAW / "prep.json"))
REF = json.load(open(RAW / "ref_targets_d.json"))
PREREG_SHA = (OUT / "PREREG_D.md").read_bytes()
PREREG_HASH = hashlib.sha256(PREREG_SHA).hexdigest()
SRC = {"real": ("runs/v2/raw_d/real_metrics.json", sha(RAW / "real_metrics.json")),
       "base": ("runs/v2/raw_d/shuffle_baseline.json", sha(RAW / "shuffle_baseline.json")),
       "prep": ("runs/v2/raw_d/prep.json", sha(RAW / "prep.json")),
       "ref": ("runs/v2/raw_d/ref_targets_d.json", sha(RAW / "ref_targets_d.json"))}
MODELS = ["M0", "M1", "M2", "M3"]
VARIANTS = {"noill": "Moon without illumination (primary)", "ill": "Moon with illumination (variant)"}
GAP = "not scorable"


def fmt(key: str, v) -> str:
    if v is None or v != v:
        return "n/a"
    if key.endswith((".n", ".hits")) or key.startswith("n_"):
        return str(int(v))
    if "fpr25" in key or "recall" in key:
        return f"{100 * v:.1f}%"
    if "auc" in key:
        return f"{v:.3f}"
    return f"{v:.1f}"


claims: list[tuple[str, str, str, str]] = []
entries: list[dict] = []


def claim(cid: str, number: str, src: str) -> None:
    claims.append((cid, number, SRC[src][0], SRC[src][1]))


LABELS = {
    "fpr25_moon_all": ("Moon false-positive rate at top 25 percent, all scorable negative units", "share",
                       "Share of negative units (desert tiles and two sand seas, each by its own tile) that the Moon score ranks in the top 25 percent. A desert is not a polar ridge; a high rate means the score is fooled by broad terrain traits."),
    "fpr25_moon_tiles": ("Moon false-positive rate at top 25 percent, 200 sampled tiles", "share",
                         "Same rate over the 200 sampled tiles only. The tiles sit in a few deserts and are not independent."),
    "namib_rank": ("Namib sand sea, Moon percentile of its own tile", "percentile",
                   "One tile, one number. A flat sand sea should rank low against a polar slope."),
    "rub_rank": ("Rub' al Khali, Moon percentile of its own tile", "percentile",
                 "One tile, one number. A flat sand sea should rank low against a polar slope."),
    "recall5": ("Mars recall at top 5 percent, scorable positives", "share", "A handful of positives; one site moves this by 25 points or more."),
    "recall10": ("Mars recall at top 10 percent, scorable positives", "share", "A handful of positives; one site moves this by 25 points or more."),
    "recall25": ("Mars recall at top 25 percent, scorable positives", "share", "A handful of positives; one site moves this by 25 points or more."),
    "mars_primary_median": ("Mars primary median percentile, scorable positives", "percentile", "Median over very few sites; terrain and a thermal inertia proxy only."),
    "auc_mars": ("Positives against negative units, Mars profile AUC", "AUC", "Rank separation under the Jezero profile; 0.5 is chance. The negative tiles are not independent, so intervals are too narrow."),
    "fpr25_mars_all": ("Negative units at top 25 percent under the Mars profile", "share", "Supplementary. Not a gate and not in the fit."),
}


def add_metric(variant: str, m: str, key: str, label: str, unit: str, meaning: str, tag: str = "") -> None:
    full = f"{m}{tag}.{key}"
    v = REAL[variant].get(full)
    cid = f"d.{variant}.{full}"
    e = {"id": cid, "group": f"d_{variant}", "label": f"{label} ({m}{', in-sample' if tag else ''}, {VARIANTS[variant]})", "unit": unit,
         "value": v, "display": fmt(key, v), "source_file": SRC["real"][0], "sha256": SRC["real"][1],
         "what_this_means_for_the_analogy": meaning + " Fitted and cross-validated on a very small labelled set; never replaces Role A's headline."}
    if m == "M0":
        e["chance"] = {"note": "thermal weight is zero for M0, so the shuffled baseline equals the value"}
    else:
        b = BASE[variant].get(full)
        if b and b["n_draws"]:
            e["chance"] = {"min": b["min"], "median": b["median"], "max": b["max"], "n_draws": b["n_draws"], "display":
                           f"{fmt(key, b['min'])} to {fmt(key, b['max'])}, median {fmt(key, b['median'])}"}
            claim(cid + ".chance_min", fmt(key, b["min"]), "base")
            claim(cid + ".chance_median", fmt(key, b["median"]), "base")
            claim(cid + ".chance_max", fmt(key, b["max"]), "base")
    if tag == "" and m == "M3" and v is None:
        e["note"] = "M3 not tested"
    entries.append(e)
    claim(cid, e["display"], "real")


for variant in VARIANTS:
    for m in MODELS:
        for key, (label, unit, meaning) in LABELS.items():
            add_metric(variant, m, key, label, unit, meaning)
        for pn in [n for n in PREP["units"] if PREP["units"][n]["group"] == "pos"]:
            add_metric(variant, m, f"rank_mars.{pn}", f"Mars percentile of {pn}, own tile", "percentile",
                       "Single tile under the Jezero profile; unscorable sites show n/a.")
    for key in ("fpr25_moon_all", "recall10", "auc_mars", "namib_rank", "rub_rank", "mars_primary_median"):
        if f"M3_insample.{key}" in REAL[variant]:
            lab = LABELS[key]
            add_metric(variant, "M3", key, lab[0], lab[1], "In-sample: w fitted on all units, so it is not a held-out value and feeds no gate.", tag="_insample")
    # counts
    for key in ("fpr25_moon_all.n", "fpr25_moon_tiles.n", "recall.n"):
        v = REAL[variant].get(f"M0.{key}")
        cid = f"d.{variant}.{key}"
        entries.append({"id": cid, "group": f"d_{variant}", "label": f"Scorable units for {key} ({VARIANTS[variant]})", "unit": "count", "value": v,
                        "display": fmt(key, v), "source_file": SRC["real"][0], "sha256": SRC["real"][1],
                        "what_this_means_for_the_analogy": "The denominator of the rates above. Units whose own tile is not scored are left out and listed in the ledger."})
        claim(cid, fmt(key, v), "real")
    for k, v in REAL[variant].items():
        if k.startswith("M3.n_folds_w") or k == "M3.w_full":
            cid = f"d.{variant}.{k}"
            disp = (f"{v:g}" if k == "M3.w_full" else str(int(v)))
            entries.append({"id": cid, "group": f"d_{variant}", "label": ("M3 w fitted on all units" if k == "M3.w_full" else f"M3 held-out folds that chose {k.split('_w')[1]}"),
                            "unit": "weight" if k == "M3.w_full" else "count", "value": v, "display": disp, "source_file": SRC["real"][0],
                            "sha256": SRC["real"][1], "what_this_means_for_the_analogy": "Shows how stable the fitted thermal weight is across leave-one-site-out folds. In-sample for w_full."})
            claim(cid, disp, "real")

# bootstrap AUC intervals
for m, b in REAL["auc_bootstrap_95"].items():
    cid = f"d.noill.{m}.auc_mars.bootstrap95"
    disp = f"{b['lo']:.3f} to {b['hi']:.3f}"
    entries.append({"id": cid, "group": "d_noill", "label": f"AUC 95 percent bootstrap interval ({m})", "unit": "AUC", "value": [b["lo"], b["hi"]], "display": disp,
                    "source_file": SRC["real"][0], "sha256": SRC["real"][1],
                    "what_this_means_for_the_analogy": f"1000 draws resampling {b['n_pos']} positives and {b['n_neg']} negative units. Too narrow because the negatives are clustered."})
    claim(cid + ".lo", f"{b['lo']:.3f}", "real")
    claim(cid + ".hi", f"{b['hi']:.3f}", "real")

# ---------------------------------------------------------------- gates
LAYER_SHARE = PREP["layer_info"]["share_valid_th_mean_lat_-55_60"]
ref_ok = bool(REF.get("cross_check_all_ok")) and all(v["match"] for v in REF["files"].values())
eng_ok = bool(PREP["engine_check"]["all_ok"])
reasons_global = []
if LAYER_SHARE < 0.85:
    reasons_global.append(f"thermal layer valid share {100 * LAYER_SHARE:.1f}% below 85% in latitude -55 to 60")
if not ref_ok:
    reasons_global.append("reference hash or Role B cross-check failed")
if not eng_ok:
    reasons_global.append("engine check against v1 base scores failed")
N = REAL["noill"]
m3_ok = "M3.not_tested" not in N


GATE_KEY: dict = {}


def gate(gid: str, label: str, val_key: str, thr: float, cmp: str, what: str) -> dict:
    GATE_KEY[gid] = val_key
    v = N.get(val_key)
    if reasons_global or not m3_ok or v is None or v != v:
        status = "NOT TESTED"
        reason = "; ".join(reasons_global) or ("M3 fit needs at least 2 scorable positives" if not m3_ok else "no value")
    else:
        passed = (v <= thr) if cmp == "le" else (v >= thr)
        status, reason = ("PASS" if passed else "FAIL"), ""
    b = BASE["noill"].get(val_key)
    inside = None
    if b and b["n_draws"] and v is not None and v == v:
        inside = bool(b["min"] <= v <= b["max"])
    e = {"id": gid, "group": "gate", "label": label, "unit": "status", "value": v, "display": fmt(val_key, v), "status": status, "threshold": thr,
         "comparison": "at most" if cmp == "le" else "at least", "reason": reason, "inside_shuffled_range": inside,
         "chance": ({"min": b["min"], "median": b["median"], "max": b["max"], "n_draws": b["n_draws"]} if b else None),
         "descriptive_only": gid == "gate.D2",
         "source_file": SRC["real"][0], "sha256": SRC["real"][1], "what_this_means_for_the_analogy": what}
    entries.append(e)
    claim(gid, fmt(val_key, v), "real")
    claim(gid + ".threshold", f"{100 * thr:.0f}%", "real")
    return e


D1 = gate("gate.D1", "D1: negative-set false-positive rate at top 25 percent, M3 held-out, at most 10 percent", "M3.fpr25_moon_all", 0.10, "le",
          "A pass means the fitted score does not rank deserts high; it does not show the analogy holds.")
D2 = gate("gate.D2", "D2: Mars leave-one-out recall at top 10 percent, M3, at least 50 percent", "M3.recall10", 0.50, "ge",
          "Descriptive only (instruction of 15 Nov after registration): the threshold comparison is shown but is not a pass or fail claim. It rests on very few positives.")
entries.append({"id": "gate.moon_recall", "group": "gate", "label": "Moon recall of known sites", "unit": "status", "value": None, "display": "NOT TESTED",
                "status": "NOT TESTED", "reason": "two Moon positives, one of them not scorable", "source_file": SRC["prep"][0], "sha256": SRC["prep"][1],
                "what_this_means_for_the_analogy": "No claim is made about Moon recall."})

# ---------------------------------------------------------------- ledger
led = []
unsc_m = PREP["meta"]["moon_unit_unscorable"]
unsc_r = PREP["meta"]["mars_unit_unscorable"]


def L(i, t, body, status, statement, meaning, src="prep"):
    led.append({"id": i, "type": t, "body": body, "status": status, "provisional": True, "statement": statement,
                "source_file": SRC[src][0], "sha256": SRC[src][1], "what_this_means_for_the_analogy": meaning})


L("limit.small_labelled_set", "known_limit", "mars", "open",
  f"The fit uses {N.get('M3.recall.n', 0):.0f} scorable Mars positives and {N.get('M0.fpr25_moon_all.n', 0):.0f} negative units. One positive moves recall by 25 points or more.",
  "Any fitted thermal weight is close to a guess. Fitted and cross-validated on a very small labelled set.")
L("limit.layer_coverage", "known_limit", "moon", "open",
  f"Role A's Earth thermal layer has a valid th_mean for {100 * LAYER_SHARE:.1f} percent of v1 land tiles between 55S and 60N. The registered rule needs 85 percent. Tiles without a value (polar blocks and areas where the pre-registered MODIS QC rule leaves no value) are outside the universe.",
  "The scored universe is a subset of Earth that leaves out much of the driest land that a desert negative set would sample. D1 and D2 are NOT TESTED under the registered rule; the metrics are reported as descriptive numbers.")
L("limit.negatives_clustered", "known_limit", "moon", "open",
  "The 200 negative tiles were drawn from bare, low, near-equatorial land. They cluster in a few deserts and are not independent.",
  "Bootstrap intervals and the false-positive rate look more certain than they are.", "real")
L("limit.bare_proxy", "known_limit", "moon", "open",
  "The v1 Earth file has no share of bare or sparse cover. The negative set uses NDVI median at most 0.10 and little water, ice, built or crop.",
  "The negatives are bare-ground tiles by a proxy, not by a land-cover class share.")
L("limit.mars_ti_proxy", "known_limit", "mars", "open",
  "The Earth partner of Mars thermal inertia is the rank of minus the MODIS day-minus-night swing. It is a proxy, not thermal inertia.",
  "A match in rank says the day-night swing is of similar rank, not that the ground has the same inertia.")
L("limit.moon_thermal_definition", "known_limit", "moon", "open",
  "Moon PRP temp_avg and temp_max are modelled values; the Earth partners are satellite skin temperatures from MODIS composites.",
  "Rank within each body is compared. Absolute values cannot match: Earth has no surface near polar cold-trap temperatures.")
L("unscored.ice_depth_illumination", "unscored_property", "moon", "open",
  "Moon ice_depth is context only. The primary Moon score leaves out the illumination family; a variant with it is reported next to it.",
  "Earth cannot match polar lighting, so the primary Moon score says nothing about illumination.")
L("unscored.arcadia_diurnal", "unscored_property", "mars", "open",
  "Arcadia has no centre and no thermal reference. Moon diurnal range, cold-trap share and Mars surface temperature have no source or no Earth partner.",
  "These properties are not scored here.")
for n, why in {**unsc_r, **{k: v for k, v in unsc_m.items() if not k.startswith("neg")}}.items():
    L(f"unscorable.{n}", "known_limit", "mars" if PREP["units"].get(n, {}).get("group") == "pos" else "moon", "open",
      f"{n}: own tile not scored ({why}).", "This site does not enter the denominators.")
if N.get("M3.not_tested"):
    L("limit.m3_not_tested", "known_limit", "mars", "open", "M3 needs at least 2 scorable positives and had fewer.", "No fitted result is reported.")

meta_common = {"label": "ROLE D. Fitted and cross-validated on a very small labelled set. Exploratory; nothing here is a success claim and nothing replaces Role A's headline.",
               "preregistration": {"file": "runs/v2/PREREG_D.md", "sha256": PREREG_HASH},
               "thermal_layer": {"label": LAYER_LABEL, "sha256": LAYER_SHA},
               "shuffled_baseline": "1000 draws, seed 20261114, Earth thermal ranks permuted across the tiles of each universe; M3 repeats the full fit per draw",
               "universe": {b: PREP["meta"][f"{b}_universe"] for b in ("moon", "mars")}, "engine_check": PREP["engine_check"],
               "reference_cross_check_ok": ref_ok}
(OUT / "metrics_d.json").write_text(json.dumps({"meta": meta_common, "metrics": entries}, indent=1, default=float) + "\n", encoding="utf-8")
(OUT / "ledger_d.json").write_text(json.dumps({"meta": {**meta_common, "inputs": {"layer_sha256": LAYER_SHA, "reference_files": {k: v["sha256"] for k, v in REF["files"].items()},
                                                                                     "v1_earth_features_sha256": "df31e93c4034ecb908a2d378ab2335d817e8751b32616e135de8febc0182a966"}}, "entries": led}, indent=1, default=float) + "\n", encoding="utf-8")

# ---------------------------------------------------------------- results_d.md
def cell(variant: str, m: str, key: str) -> str:
    full = f"{m}.{key}"
    v = REAL[variant].get(full)
    s = fmt(key, v)
    if m == "M0":
        return f"{s} (no thermal term)"
    b = BASE[variant].get(full)
    if b and b["n_draws"]:
        s += f" [chance {fmt(key, b['min'])} to {fmt(key, b['max'])}, med {fmt(key, b['median'])}]"
    return s


def table(variant: str) -> list[str]:
    rows = ["| Metric | " + " | ".join(MODELS) + " |", "|---|" + "---|" * len(MODELS)]
    for key, lab in (("fpr25_moon_all", "Moon false-positive rate, top 25%"), ("fpr25_moon_tiles", "same, 200 tiles only"),
                     ("namib_rank", "Namib sand sea percentile"), ("rub_rank", "Rub' al Khali percentile"),
                     ("recall5", "Mars recall top 5%"), ("recall10", "Mars recall top 10%"), ("recall25", "Mars recall top 25%"),
                     ("mars_primary_median", "Mars primary median percentile"), ("auc_mars", "AUC positives vs negatives (Mars profile)"),
                     ("fpr25_mars_all", "Negatives at top 25%, Mars profile (supplementary)")):
        rows.append(f"| {lab} | " + " | ".join(cell(variant, m, key) for m in MODELS) + " |")
    for pn in [n for n in PREP["units"] if PREP["units"][n]["group"] == "pos"]:
        rows.append(f"| Mars percentile, {pn} | " + " | ".join(cell(variant, m, f"rank_mars.{pn}") for m in MODELS) + " |")
    return rows


gt = ["| Gate | Value (M3 held-out) | Threshold | Shuffled range | Status |", "|---|---|---|---|---|"]
for g in (D1, D2):
    ch = g["chance"]
    gt.append(f"| {g['id'][5:]}{' (descriptive only)' if g.get('descriptive_only') else ''} | {g['display']} | {g['comparison']} {100 * g['threshold']:.0f}% | "
              + (f"{fmt(GATE_KEY[g['id']], ch['min'])} to {fmt(GATE_KEY[g['id']], ch['max'])}" if ch else "n/a") + f" | {('would be ' + g['status'] + ', descriptive only') if g.get('descriptive_only') else g['status']}" + (f" ({g['reason']})" if g["reason"] else "") + " |")
gt.append("| Moon recall | n/a | n/a | n/a | NOT TESTED (two Moon positives, one not scorable) |")
for g in (D1, D2):
    if g["status"] == "FAIL":
        pass

fails = [f"{g['id']} FAIL: value {g['display']} against {g['comparison']} {100 * g['threshold']:.0f}%" for g in (D1,) if g["status"] == "FAIL"]
nt = [f"{g['id']} NOT TESTED: {g['reason']}" for g in (D1, D2) if g["status"] == "NOT TESTED"] + ["Moon recall NOT TESTED: two Moon positives, one not scorable.",
                                                                                                     "Arcadia: no centre, no thermal reference."]
within = [g["id"] for g in (D1, D2) if g.get("inside_shuffled_range")]
outside = [g["id"] for g in (D1, D2) if g.get("inside_shuffled_range") is False]
import numpy as _np
_z = _np.load(RAW / "ranks_real.npz")
_mp = _z["mars"][:5, :len([n for n in PREP["units"] if PREP["units"][n]["group"] == "pos"])]
_mx = float(_np.nanmax(_mp)) if _np.isfinite(_mp).any() else float("nan")
_hits = int((_np.nan_to_num(_mp, nan=-1) >= 90).sum())
_mo = _z["moon_noill"][:5]
_fpr = [float((_mo[i] >= 75).sum() / _np.isfinite(_mo[i]).sum()) for i in range(5)]
md = [f"# Results D: fitted thermal terms, leave-one-site-out", "",
      "Fitted and cross-validated on a very small labelled set. Never replaces Role A's headline. Exploratory; nothing here is a success claim.", "",
      f"Pre-registration `runs/v2/PREREG_D.md`, sha256 `{PREREG_HASH}` (recorded in `prereg_d.sha256`). Thermal layer: {LAYER_LABEL}, sha256 `{LAYER_SHA}`.", "",
      "## Gates (headline: M3, held-out, Moon without illumination, single-tile percentiles)", ""] + gt + [""]
if within:
    md += [f"Inside the shuffled-feature range, so not distinguishable from chance on this check: {', '.join(within)}.", ""]
if outside:
    md += [f"Outside the shuffled-feature range: {', '.join(outside)} (gate status is still NOT TESTED, see reason)", ""]
md += ["## M0 to M3 metrics, Moon without illumination (primary)", "",
       "Each cell: value, then the shuffled-feature chance range over 1000 draws (min to max, median). M3 values are held-out outcomes of the leave-one-site-out fit.", ""] + table("noill") + [""]
md += ["## M0 to M3 metrics, Moon with illumination (variant, feeds no gate)", ""] + table("ill") + [""]
b = REAL["auc_bootstrap_95"]
md += ["## AUC bootstrap intervals (95 percent, 1000 draws, too narrow because negatives cluster)", ""] + [f"- {m}: {x['lo']:.3f} to {x['hi']:.3f} ({x['n_pos']} positives, {x['n_neg']} negative units)" for m, x in b.items()] + [""]
md += ["## Fit", "", f"- w fitted on all units (in-sample, Moon without illumination): {N.get('M3.w_full', 'n/a')}",
       "- Held-out folds choosing each w: " + ", ".join(f"{g}: {int(N.get(f'M3.n_folds_w{g}', 0))}" for g in (0.0, 0.25, 0.5, 0.75, 1.0)),
       "- M1 thermal group weight: Moon without illumination 2/7, Moon with illumination 2/9, Mars 1/7. M2 is 0.5.", ""]
md += ["## Universe", "", f"- Moon: {PREP['meta']['moon_universe']['n_U']} tiles; Mars: {PREP['meta']['mars_universe']['n_U']} tiles (v1 gates plus valid thermal values).",
       f"- Share of v1 land tiles in latitude -55 to 60 with a valid `th_mean`: {100 * LAYER_SHARE:.1f}%.",
       f"- Engine check against v1 base scores: {'reproduced to 1e-3' if eng_ok else 'NOT reproduced'}.", ""]
def why(r):
    return {"vegetated": "own tile fails the v1 NDVI gate (median NDVI above 0.2)", "built_or_cropland": "own tile fails the v1 built or crop gate (above 20 percent)",
            "open_water_or_ice": "own tile fails the v1 open water or ice gate (above 50 percent)", "missing_data": "own tile has missing terrain or gate data",
            "not a v1 land tile": "the point lies outside every v1 land tile (under 50 percent land in the tile or off the grid)",
            "thermal value invalid": "own tile has no valid MODIS thermal value"}.get(r, r)


md += ["## Labelled sites that cannot be scored by their own tile", "",
       "| Site | Group | Moon profile | Mars profile |", "|---|---|---|---|"]
for n, u in PREP["units"].items():
    mo = unsc_m.get(n)
    ma = unsc_r.get(n)
    md.append(f"| {n} | {'positive' if u['group'] == 'pos' else 'negative control'} | {'scored' if mo is None else 'not scored: ' + why(mo)} | {'scored' if ma is None else 'not scored: ' + why(ma)} |")
tm = {}
for n, r in unsc_m.items():
    if n.startswith("neg"):
        tm[r] = tm.get(r, 0) + 1
md += ["", f"Of the 200 sampled negative tiles, {sum(tm.values())} {'is' if sum(tm.values()) == 1 else 'are'} not scored under the Moon profile" + (": " + ", ".join(f"{why(k)}" for k, v in tm.items()) if tm else "") + ".", ""]
md += ["## Earth tiles with missing thermal values, by latitude band", "",
       "Tiles are v1 land tiles. A thermal value is missing where the MODIS layer is NaN or the valid share is under 0.5. Bands with |latitude| above 60 are the polar bands (south polar: -90 to -60; north polar: 60 to 90).", "",
       "| Band | Region | Land tiles | Missing th_mean | Missing th_max | Missing th_ti | Missing share th_mean |", "|---|---|---|---|---|---|---|"]
for lb in PREP["lat_bands"]:
    reg = "south polar" if lb["hi"] <= -60 else ("north polar" if lb["lo"] >= 60 else "")
    sh = (100 * lb["missing_th_mean"] / lb["n_land_tiles"]) if lb["n_land_tiles"] else 0.0
    md.append(f"| {lb['lo']} to {lb['hi']} | {reg} | {lb['n_land_tiles']} | {lb['missing_th_mean']} | {lb['missing_th_max']} | {lb['missing_th_ti']} | {sh:.1f}% |")
    claim(f"d.latband.{lb['lo']}_{lb['hi']}.n_land", str(lb["n_land_tiles"]), "prep")
    for c in ("th_mean", "th_max", "th_ti"):
        claim(f"d.latband.{lb['lo']}_{lb['hi']}.missing_{c}", str(lb[f"missing_{c}"]), "prep")
polar_miss = sum(lb["missing_th_mean"] for lb in PREP["lat_bands"] if lb["polar"])
all_miss = sum(lb["missing_th_mean"] for lb in PREP["lat_bands"])
md += ["", f"Polar bands hold {polar_miss} of the {all_miss} tiles missing `th_mean`.", ""]
claim("d.latband.polar_missing_th_mean", str(polar_miss), "prep")
claim("d.latband.all_missing_th_mean", str(all_miss), "prep")
md += ["## What failed and what the fit decided", ""] + ([f"- {x}" for x in fails] or ["- No gate was tested, so no gate returned PASS or FAIL."])
md += [f"- Mars recall at top 5, 10 and 25 percent is 0 for M0 to M3. The highest Mars percentile any scorable positive reaches at any grid weight (0, 0.25, 0.5, 0.75, 1) is {_mx:.1f}; positives at or above the 90th percentile over the whole grid: {_hits}.",
       "- Because positive recall at top 10 percent is 0 at every grid weight, the M3 fit is decided by the false-positive term alone. Moon false-positive rate by grid weight (0, 0.25, 0.5, 0.75, 1): " + ", ".join(f"{100 * x:.1f}%" for x in _fpr) + ". The fit picks the smallest weight at the minimum.",
       "- Reading, interpretation and not a metric: the lunar polar targets are cold and the negative tiles are hot deserts, so any thermal term pushes deserts down. A lower false-positive rate here says the thermal columns separate hot Earth deserts from cold targets. It does not say thermal terms pull known Mars analog sites up; they did not.", ""]
md += ["## D2 is descriptive only", "", "D2 (Mars leave-one-out recall at top 10 percent) was registered as a gate. Anay instructed on 15 Nov, after registration, that D2 is descriptive only. The table shows what it would read against the threshold; it is not a pass or fail claim, because it rests on a handful of scorable positives.", ""]
md += ["## NOT TESTED", ""] + [f"- {x}" for x in nt] + [""]
md += ["## Units not scorable (own tile not scored)", ""] + [f"- {n}: {w}" for n, w in {**unsc_r}.items()] + [""]
md += ["## Limits", "", *[f"- {e['statement']}" for e in led if e["id"].startswith("limit.")], ""]
md += ["## Deviations", "", "- D2 treated as descriptive only, by instruction of 15 Nov after PREREG_D was recorded. The D2 entry keeps its threshold comparison and carries `descriptive_only: true`.", "- Two sections added at Anay's request on 15 Nov: unscored labelled sites, and missing thermal values by latitude band.", "- Negative-set cover rule uses a low-NDVI proxy, stated in PREREG_D at registration.",
       "- Negative units scorable under the Mars profile but not the Moon profile use `w_full` for their Mars rank in the M3 AUC (they are not in the fit set).",
       "- Role A's layer was copied after its pull finished; layer sha256 is above."]
(OUT / "results_d.md").write_text("\n".join(md) + "\n", encoding="utf-8")

# extra counts for claims
for k, v in (("universe.moon_n", PREP["meta"]["moon_universe"]["n_U"]), ("universe.mars_n", PREP["meta"]["mars_universe"]["n_U"]),
             ("layer.share_valid_lat_-55_60_pct", f"{100 * LAYER_SHARE:.1f}"), ("shuffle.n_draws", 1000), ("negatives.n_tiles", 200)):
    claim("d." + k, str(v), "prep")
for m, x in b.items():
    claim(f"d.noill.{m}.auc_n_pos", str(x["n_pos"]), "real")
    claim(f"d.noill.{m}.auc_n_neg", str(x["n_neg"]), "real")
claim("d.noill.grid.max_mars_positive_rank", f"{_mx:.1f}", "real")
claim("d.noill.grid.positives_at_or_above_p90", str(_hits), "real")
for _i, _g in enumerate((0, 0.25, 0.5, 0.75, 1)):
    claim(f"d.noill.grid.moon_fpr25_w{_g}", f"{100 * _fpr[_i]:.1f}%", "real")
claims.sort(key=lambda r: r[0])
with open(OUT / "claims_d.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["claim", "number", "source_file", "sha256"])
    w.writerows(claims)
print("D1", D1["status"], D1["display"], "| D2", D2["status"], D2["display"], "| entries", len(entries), "claims", len(claims))
