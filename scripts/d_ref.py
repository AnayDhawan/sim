"""ROLE D: Moon and Mars thermal reference side (PREREG_D, section Thermal feature pairs).
Reads the raw PDS products Role B used, checks sha256 against Role B's file list, rebuilds the ranking sets and writes
the target rank values and spreads to data/interim/d_ref/ref_targets_d.json, plus the cross-check against Role B's value-space medians.
Raw products are read from a folder given on the command line (read only)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"C:\Users\lenovo\sim-a\data\raw\ref")
OUT = ROOT / "data" / "interim" / "d_ref"
EXPECT = {  # sha256 and bytes from Role B's thermal_refs_files.csv (branch data/thermal-refs)
    "dlre_prp_south.tab": ("393deaa5d8925d45bb2ed608f937a824f5eae029c2558aad1d2da8206b83a62d", 604800210),
    "global_ti_day_2007.img": ("d8b1ac57c5f2c6d4f43d7e5331591fae0254f48af7629bd0d230c2603da48f9a", 51840000),
    "global_ti_night_2007.img": ("faee32838da40045ee7ebd21bed156cc649620312c01165b556d77a2128258f4", 51840000),
    "global_ti_msk_day_2007.img": ("23bab175ab99e5aa7b68a4b664f3d616f08c92fcc410188c116d5083103d16cb", 25920000),
    "global_ti_msk_night_2007.img": ("fca7ec6fab8b3e81226e1d14dbb3a22509ad111bda4e03bf2b64f050bd550d0b", 25920000),
}
# Role B value-space rows (K for the Moon; SI for Mars), radius 5 km Moon, 10 km Mars. Used only as a cross-check.
B_ROWS = {"connecting_ridge_c1": {"avg": 129.226, "max": 238.191, "n": 613},
          "shackleton_rim": {"avg": 115.269, "max": 263.82, "n": 612},
          "jezero": {"day": 293.0, "night": 304.0}}
SITES_MOON = {"connecting_ridge_c1": (-89.45, 222.84), "shackleton_rim": (-89.78, 203.97)}
JEZERO = (18.4386, 77.5031)
R_MOON, R_MARS = 1737.4, 3389.5
REC, HDR = 210, 210
COLS = {"clon": (127, 15), "clat": (144, 15), "tavg": (178, 8), "tmax": (188, 8)}


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 24), b""):
            h.update(b)
    return h.hexdigest()


def unit(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=-1)


def gc_km(u, v, r):
    return r * np.arctan2(np.linalg.norm(np.cross(u, v), axis=-1), np.sum(u * v, axis=-1))


def midrank(sorted_set: np.ndarray, v: np.ndarray) -> np.ndarray:
    lo = np.searchsorted(sorted_set, v, side="left")
    hi = np.searchsorted(sorted_set, v, side="right")
    return 100.0 * (lo + 0.5 * (hi - lo)) / sorted_set.size


def field(blk: np.ndarray, name: str) -> np.ndarray:
    s, w = COLS[name]
    return np.ascontiguousarray(blk[:, s - 1:s - 1 + w]).view(f"S{w}").ravel().astype(np.float64)


def spread(r: np.ndarray) -> float:
    q75, q25 = np.percentile(r, [75, 25])
    return float((q75 - q25) / 1.349)


def moon() -> dict:
    mm = np.memmap(RAW / "dlre_prp_south.tab", dtype=np.uint8, mode="r", offset=HDR)
    nrec = mm.size // REC
    mm = mm.reshape(nrec, REC)
    sv = {k: unit(*v) for k, v in SITES_MOON.items()}
    allv = {"avg": [], "max": []}
    sel = {k: [] for k in SITES_MOON}
    for i in range(0, nrec, 200_000):
        blk = mm[i:i + 200_000]
        u = unit(field(blk, "clat"), field(blk, "clon"))
        ta, tm = field(blk, "tavg"), field(blk, "tmax")
        for k, v in sv.items():
            m = gc_km(u, v[None, :], R_MOON) <= 5.0
            if m.any():
                sel[k].append(np.column_stack([ta[m], tm[m]]))
        allv["avg"].append(ta)
        allv["max"].append(tm)
    out = {"n_records": int(nrec), "cols": {}}
    for name, j in (("th_mean", "avg"), ("th_max", "max")):
        a = np.concatenate(allv[j])
        good = np.isfinite(a) & (a > 0) & (a <= 500)
        s = np.sort(a[good])
        col = {"set_n": int(s.size), "n_excluded": int((~good).sum()), "sites": {}}
        jj = 0 if j == "avg" else 1
        for k in SITES_MOON:
            v = np.vstack(sel[k])[:, jj]
            v = v[np.isfinite(v) & (v > 0) & (v <= 500)]
            r = midrank(s, v)
            col["sites"][k] = {"n": int(v.size), "value_median_K": float(np.median(v)), "rank_median": float(np.median(r)),
                               "rank_spread_iqr_1349": spread(r)}
        out["cols"][name] = col
    return out


def mars() -> dict:
    day = np.fromfile(RAW / "global_ti_day_2007.img", dtype=">i2").reshape(3600, 7200).astype(np.float64)
    night = np.fromfile(RAW / "global_ti_night_2007.img", dtype=">i2").reshape(3600, 7200).astype(np.float64)
    mday = np.fromfile(RAW / "global_ti_msk_day_2007.img", dtype=">u1").reshape(3600, 7200)
    mnight = np.fromfile(RAW / "global_ti_msk_night_2007.img", dtype=">u1").reshape(3600, 7200)
    ok = (day > 0) & (night > 0) & (mday != 0) & (mnight != 0)
    val = (day + night) / 2.0
    s = np.sort(val[ok])
    r0 = int(round(1799.5 - JEZERO[0] * 20))
    c0 = int(round(JEZERO[1] * 20 + 3599.5))
    rr, cc = np.meshgrid(np.arange(r0 - 20, r0 + 21), np.arange(c0 - 20, c0 + 21), indexing="ij")
    d = gc_km(unit((1799.5 - rr) / 20.0, (cc - 3599.5) / 20.0), unit(*JEZERO), R_MARS)
    inside = d <= 10.0
    sel = inside & ok[rr, cc]
    v = val[rr, cc][sel]
    r = midrank(s, v)
    dd, nn = day[rr, cc][inside & (day[rr, cc] > 0)], night[rr, cc][inside & (night[rr, cc] > 0)]
    return {"set_n": int(s.size), "n_pixels_total": int(day.size),
            "jezero": {"n_in_R": int(inside.sum()), "n_used": int(v.size), "value_median": float(np.median(v)),
                       "day_median_all_positive": float(np.median(dd)), "night_median_all_positive": float(np.median(nn)),
                       "rank_median": float(np.median(r)), "rank_spread_iqr_1349": spread(r)}}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    res: dict = {"files": {}}
    for n, (h, b) in EXPECT.items():
        p = RAW / n
        got = sha(p)
        res["files"][n] = {"bytes": p.stat().st_size, "sha256": got, "expected_sha256": h, "match": got == h and p.stat().st_size == b}
        print(n, res["files"][n]["match"], flush=True)
    res["moon"] = moon() if res["files"]["dlre_prp_south.tab"]["match"] else "NOT TESTED: sha mismatch"
    res["mars"] = mars() if all(res["files"][n]["match"] for n in EXPECT if n != "dlre_prp_south.tab") else "NOT TESTED: sha mismatch"
    chk = {}
    if isinstance(res["moon"], dict):
        for k in SITES_MOON:
            for col, key in (("th_mean", "avg"), ("th_max", "max")):
                s = res["moon"]["cols"][col]["sites"][k]
                rel = abs(s["value_median_K"] - B_ROWS[k][key]) / B_ROWS[k][key]
                chk[f"{k}_{key}"] = {"mine": s["value_median_K"], "role_b": B_ROWS[k][key], "rel_diff": rel, "n_mine": s["n"],
                                     "n_role_b": B_ROWS[k]["n"], "ok": bool(rel <= 0.005)}
    if isinstance(res["mars"], dict):
        j = res["mars"]["jezero"]
        for key, mine in (("day", j["day_median_all_positive"]), ("night", j["night_median_all_positive"])):
            rel = abs(mine - B_ROWS["jezero"][key]) / B_ROWS["jezero"][key]
            chk[f"jezero_{key}"] = {"mine": mine, "role_b": B_ROWS["jezero"][key], "rel_diff": rel, "ok": bool(rel <= 0.005)}
    res["cross_check_role_b"] = chk
    res["cross_check_all_ok"] = bool(chk) and all(v["ok"] for v in chk.values())
    (OUT / "ref_targets_d.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res["cross_check_role_b"], indent=1), res["cross_check_all_ok"])


if __name__ == "__main__":
    main()
