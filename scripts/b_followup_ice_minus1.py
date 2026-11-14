"""B2 follow-up 3: cross-count of ice_depth == -1.0 against temp_max < 110 K at shackleton_rim (R = 5 km primary).

Counts only. No interpretation of -1.0 (the PRP label does not define it). Appends rows to data/reference/thermal_refs.csv.
Source: dlre_prp_south.tab (https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_prp/),
read from the cache written by scripts/b_thermal_refs.py. Run: python -I scripts/b_followup_ice_minus1.py
"""
import csv, importlib.util, json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bt", ROOT / "scripts" / "b_thermal_refs.py")
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

prp = ROOT / "runs" / "v2" / "cache" / bt.PRP_FILE
sha = next(r[3] for r in csv.reader(open(ROOT / "data" / "reference" / "thermal_refs_files.csv", encoding="utf-8"))
           if r[0] == bt.PRP_FILE)
site = "shackleton_rim"
sel, _ = bt.prp_scan(prp, {site: bt.SITES[site]})
a = sel[site]
out = []
for r_km, suf in ((5.0, ""), (2.5, "_R2p5km"), (10.0, "_R10km")):
    s = a[a[:, 0] <= r_km]
    tm, ice = s[:, 2], s[:, 3]
    good = np.isfinite(tm) & (tm > 0) & (tm < 500)
    cold = good & (tm < bt.COLD_TRAP_K)
    m1 = ice == -1.0
    both = int((m1 & cold).sum())
    out += [(st + suf, v) for st, v in (
        ("n_triangles", int(s.shape[0])), ("n_ice_depth_minus1", int(m1.sum())),
        ("n_tmax_below_110K", int(cold.sum())), ("n_minus1_and_tmax_below_110K", both),
        ("n_minus1_not_below_110K", int((m1 & ~cold).sum())),
        ("n_below_110K_not_minus1", int((cold & ~m1).sum())))]
rows = [dict(site_slug=site, body="moon", layer="prp_ice_depth_x_cold_trap", stat=st, value=v, units="count",
             product=bt.PRODUCT_PRP, version=bt.VERSION_PRP, source_url=bt.PRP_URL, sha256=sha) for st, v in out]
with open(ROOT / "data" / "reference" / "thermal_refs.csv", "a", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["site_slug", "body", "layer", "stat", "value", "units", "product", "version",
                                       "source_url", "sha256"])
    for r in rows:
        w.writerow(r)
for r in rows:
    print(r["stat"], r["value"])
