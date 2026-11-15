"""ROLE A: rebuild the Moon and Mars ranking sets from the raw products Role B used (PREREG_A, section Ranking and pairs).
Downloads (resumable, sha256 checked against data/reference/thermal_refs_files.csv of branch data/thermal-refs), then writes
data/interim/a_thermal/ref_targets.json with the site rank values and spreads, plus the value-space medians for the cross-check."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "ref"
OUT = ROOT / "data" / "interim" / "a_thermal"
PRP_BASE = "https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_prp/"
TES_BASE = "https://pds-geosciences.wustl.edu/mgs/mgs-m-tes-5-timap-v1/mgst_9001/data/"
FILES = {
    "dlre_prp_south.tab": (PRP_BASE, 604_800_210, "393deaa5d8925d45bb2ed608f937a824f5eae029c2558aad1d2da8206b83a62d"),
    "global_ti_day_2007.img": (TES_BASE, 51_840_000, "d8b1ac57c5f2c6d4f43d7e5331591fae0254f48af7629bd0d230c2603da48f9a"),
    "global_ti_night_2007.img": (TES_BASE, 51_840_000, "faee32838da40045ee7ebd21bed156cc649620312c01165b556d77a2128258f4"),
    "global_ti_msk_day_2007.img": (TES_BASE, 25_920_000, "23bab175ab99e5aa7b68a4b664f3d616f08c92fcc410188c116d5083103d16cb"),
    "global_ti_msk_night_2007.img": (TES_BASE, 25_920_000, "fca7ec6fab8b3e81226e1d14dbb3a22509ad111bda4e03bf2b64f050bd550d0b"),
}
SITES_MOON = {"connecting_ridge_c1": (-89.45, 222.84), "shackleton_rim": (-89.78, 203.97)}
JEZERO = (18.4386, 77.5031)
R_MOON, R_MARS_PREREG, R_MARS_LABEL = 1737.4, 3389.5, 3396.0
REC, HDR = 210, 210
COLS = dict(clon=(127, 15), clat=(144, 15), tavg=(178, 8), tmax=(188, 8))


def download(name, tries=20):
    base, size, _ = FILES[name]
    RAW.mkdir(parents=True, exist_ok=True)
    dest = RAW / name
    part = RAW / (name + ".part")
    if dest.exists() and dest.stat().st_size == size:
        return dest
    for k in range(tries):
        have = part.stat().st_size if part.exists() else 0
        if have >= size:
            break
        try:
            req = urllib.request.Request(base + name, headers={"Range": f"bytes={have}-{size - 1}"})
            with urllib.request.urlopen(req, timeout=60) as r, open(part, "ab") as f:
                if r.status == 200 and have:
                    f.truncate(0)
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
        except Exception as e:  # noqa: BLE001
            print("download error", name, k, type(e).__name__, str(e)[:120], flush=True)
            time.sleep(min(60, 5 * (k + 1)))
    if part.stat().st_size != size:
        raise IOError(f"size mismatch {name}")
    part.replace(dest)
    return dest


def sha(p):
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


def midrank(sorted_set, v):
    n = sorted_set.size
    lo = np.searchsorted(sorted_set, v, side="left")
    hi = np.searchsorted(sorted_set, v, side="right")
    return 100.0 * (lo + 0.5 * (hi - lo)) / n


def col(blk, name):
    s, w = COLS[name]
    return np.ascontiguousarray(blk[:, s - 1:s - 1 + w]).view(f"S{w}").ravel().astype(np.float64)


def moon():
    p = RAW / "dlre_prp_south.tab"
    mm = np.memmap(p, dtype=np.uint8, mode="r", offset=HDR)
    nrec = mm.size // REC
    assert nrec == 2_880_000, nrec
    mm = mm.reshape(nrec, REC)
    tavg_all, tmax_all = [], []
    sel = {k: [] for k in SITES_MOON}
    sv = {k: unit(*v) for k, v in SITES_MOON.items()}
    for i in range(0, nrec, 200_000):
        blk = mm[i:i + 200_000]
        clon, clat, ta, tm = col(blk, "clon"), col(blk, "clat"), col(blk, "tavg"), col(blk, "tmax")
        u = unit(clat, clon)
        for k, v in sv.items():
            d = gc_km(u, v[None, :], R_MOON)
            m = d <= 5.0
            if m.any():
                sel[k].append(np.column_stack([ta[m], tm[m]]))
        tavg_all.append(ta)
        tmax_all.append(tm)
    ta, tm = np.concatenate(tavg_all), np.concatenate(tmax_all)
    out = {"n_records": int(nrec)}
    for name, arr, j in (("th_mean", ta, 0), ("th_max", tm, 1)):
        good = np.isfinite(arr) & (arr > 0) & (arr <= 500)
        s = np.sort(arr[good])
        out[name] = {"set_n": int(s.size), "n_excluded": int((~good).sum()), "sites": {}}
        for k in SITES_MOON:
            v = np.vstack(sel[k])[:, j]
            v = v[np.isfinite(v) & (v > 0) & (v <= 500)]
            r = midrank(s, v)
            q75, q25 = np.percentile(r, [75, 25])
            out[name]["sites"][k] = {"n": int(v.size), "value_median_K": float(np.median(v)), "rank_median": float(np.median(r)),
                                     "rank_spread_iqr_1349": float((q75 - q25) / 1.349),
                                     "rank_p5_p95": [float(np.percentile(r, 5)), float(np.percentile(r, 95))]}
    return out


def mars():
    day = np.fromfile(RAW / "global_ti_day_2007.img", dtype=">i2").reshape(3600, 7200).astype(np.float64)
    night = np.fromfile(RAW / "global_ti_night_2007.img", dtype=">i2").reshape(3600, 7200).astype(np.float64)
    mday = np.fromfile(RAW / "global_ti_msk_day_2007.img", dtype=">u1").reshape(3600, 7200)
    mnight = np.fromfile(RAW / "global_ti_msk_night_2007.img", dtype=">u1").reshape(3600, 7200)
    ok = (day > 0) & (night > 0) & (mday != 0) & (mnight != 0)
    val = (day + night) / 2.0
    s = np.sort(val[ok])
    out = {"set_n": int(s.size), "n_pixels_total": int(day.size), "sites": {}}
    r0 = int(round(1799.5 - JEZERO[0] * 20))
    c0 = int(round(JEZERO[1] * 20 + 3599.5))
    w = 20
    rr, cc = np.meshgrid(np.arange(r0 - w, r0 + w + 1), np.arange(c0 - w, c0 + w + 1), indexing="ij")
    lat = (1799.5 - rr) / 20.0
    lon = (cc - 3599.5) / 20.0
    for tag, R in (("prereg_3389.5", R_MARS_PREREG), ("label_3396.0", R_MARS_LABEL)):
        d = gc_km(unit(lat, lon), unit(*JEZERO), R)
        inside = d <= 10.0
        sel_ok = inside & ok[rr, cc]
        v = val[rr, cc][sel_ok]
        r = midrank(s, v)
        q75, q25 = np.percentile(r, [75, 25])
        dd = day[rr, cc][inside & (day[rr, cc] > 0)]
        nn = night[rr, cc][inside & (night[rr, cc] > 0)]
        out["sites"][tag] = {"n_in_R": int(inside.sum()), "n_used": int(v.size), "value_median": float(np.median(v)),
                             "day_median_all_positive": float(np.median(dd)), "night_median_all_positive": float(np.median(nn)),
                             "rank_median": float(np.median(r)), "rank_spread_iqr_1349": float((q75 - q25) / 1.349)}
    return out


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"files": {}}
    for n in FILES:
        p = download(n)
        h = sha(p)
        res["files"][n] = {"bytes": p.stat().st_size, "sha256": h, "expected_sha256": FILES[n][2], "match": h == FILES[n][2]}
        print(n, h == FILES[n][2], flush=True)
    res["mars"] = mars() if all(res["files"][n]["match"] for n in FILES if n != "dlre_prp_south.tab") else "NOT TESTED: sha mismatch"
    res["moon"] = moon() if res["files"]["dlre_prp_south.tab"]["match"] else "NOT TESTED: sha mismatch"
    (OUT / "ref_targets.json").write_text(json.dumps(res, indent=1))
    print("done", flush=True)
