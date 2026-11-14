"""ROLE B: Moon/Mars thermal reference features for the Space Apps analog run.

Pre-registration: runs/v2/PREREG_B.md (sha256 in runs/v2/prereg_b.sha256), deviations in runs/v2/PREREG_B_DEVIATIONS.md.
Run (background):  nohup python -I scripts/b_thermal_refs.py --full > runs/v2/logs/run.out 2>&1 &
Smoke test:        python -I scripts/b_thermal_refs.py --smoke

Checkpoint/resume: runs/v2/cache/state.json records finished stages; rerun skips them. Downloads resume with Range.
Sources (labels were read on 2026-11-15; where a label disagrees with the brief the label wins, see deviations file):
  PRP  https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_prp/  (DOI 10.17189/wj0s-w188)
  TES  https://pds-geosciences.wustl.edu/mgs/mgs-m-tes-5-timap-v1/mgst_9001/data/                  (DOI 10.17189/1519489)
"""
import argparse, csv, datetime as dt, hashlib, json, os, shutil, sys, threading, time, traceback, urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "runs" / "v2"
CACHE = V2 / "cache"
LOGS = V2 / "logs"
STATE_F = CACHE / "state.json"
STATUS_F = V2 / "STATUS_B.md"
OUT_CSV = ROOT / "data" / "reference" / "thermal_refs.csv"
OUT_LEDGER = ROOT / "data" / "reference" / "thermal_refs_files.csv"

SEED = 20261114  # reserved; no stochastic step in this run
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
HARD_STOP = dt.datetime(2026, 11, 15, 17, 0, tzinfo=IST)
STAGE_BUDGET_S = 30 * 60  # blocked > 30 min: log and move on

PRP_BASE = "https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_prp/"
TES_BASE = "https://pds-geosciences.wustl.edu/mgs/mgs-m-tes-5-timap-v1/mgst_9001/data/"
PRP_FILE = "dlre_prp_south.tab"
PRP_BYTES = 604_800_210
TES_FILES = ["global_ti_day_2007.img", "global_ti_night_2007.img",
             "global_ti_msk_day_2007.img", "global_ti_msk_night_2007.img"]
TES_BYTES = {"global_ti_day_2007.img": 51_840_000, "global_ti_night_2007.img": 51_840_000,
             "global_ti_msk_day_2007.img": 25_920_000, "global_ti_msk_night_2007.img": 25_920_000}

# PREREG_B sites (config/targets.yaml at ca9a816). lon_e is degrees east.
SITES = {
    "connecting_ridge_c1": dict(body="moon", lat=-89.45, lon=222.84),
    "shackleton_rim": dict(body="moon", lat=-89.78, lon=203.97),
    "jezero": dict(body="mars", lat=18.4386, lon=77.5031),
    "arcadia": dict(body="mars", lat=None, lon=None),
}
R_MOON_KM = 1737.4
R_MARS_KM = 3396.0  # TES label A/B/C axis radius (deviation 4)
MOON_R_PRIMARY, MOON_R_SENS = 5.0, (2.5, 10.0)
MARS_R = 10.0
COLD_TRAP_K = 110.0  # Hayne et al. 2020 Nat Astron; Williams et al. 2019 JGR Planets 124:2505 (PREREG_B)

# PRP fixed-width layout, 1-based start bytes from dlre_prp_south.xml
REC, HDR = 210, 210
COLS = dict(v=(1, 12), clon=(127, 15), clat=(144, 15), calt=(161, 15), tavg=(178, 8), tmax=(188, 8), ice=(198, 11))
VERT_START = [1, 15, 29, 43, 57, 71, 85, 99, 113]  # tri1_x .. tri3_z, 12 wide

PRP_URL = PRP_BASE + PRP_FILE
PRODUCT_PRP = "Diviner South Polar Resource Product (PRP)"
VERSION_PRP = "bundle v5.0 (brief); label version_id 1.0, product_version_id 2"
PRODUCT_TES = "MGS TES TIMAP thermal inertia 2007"
VERSION_TES = "MGS-M-TES-5-TIMAP-V1.0"

STATE = {"stage": "init", "pct": 0.0, "last_error": "", "stages_done": [], "blocked": [], "bytes_down": 0}
LOCK = threading.Lock()


def now_ist():
    return dt.datetime.now(IST)


def log(msg):
    line = f"{now_ist().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LOGS / "run.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def write_status(final=""):
    free_gb = shutil.disk_usage(str(ROOT)).free / 1e9
    with LOCK:
        s = dict(STATE)
    txt = (f"# STATUS_B (ROLE B reference side)\n\n"
           f"- updated: {now_ist().isoformat(timespec='seconds')}\n"
           f"- stage: {s['stage']}\n- percent done: {s['pct']:.0f}\n"
           f"- stages done: {', '.join(s['stages_done']) or 'none'}\n"
           f"- blocked and skipped: {', '.join(s['blocked']) or 'none'}\n"
           f"- last error: {s['last_error'] or 'none'}\n"
           f"- downloaded this run: {s['bytes_down'] / 1e9:.3f} GB\n"
           f"- free disk: {free_gb:.0f} GB\n")
    if final:
        txt += f"- final: {final}\n"
    V2.mkdir(parents=True, exist_ok=True)
    STATUS_F.write_text(txt, encoding="utf-8")


def status_thread(stop):
    while not stop.wait(600):
        write_status()


def set_stage(name, pct=None):
    with LOCK:
        STATE["stage"] = name
        if pct is not None:
            STATE["pct"] = pct
    write_status()
    log(f"stage {name}")


def check_time():
    if now_ist() >= HARD_STOP:
        raise SystemExit("hard stop 17:00 IST reached, no new work")


def load_done():
    if STATE_F.exists():
        return json.loads(STATE_F.read_text())
    return {}


def save_done(d):
    STATE_F.write_text(json.dumps(d, indent=1))


def sha256_file(p, chunk=1 << 24):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def head_len(url):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers["Content-Length"])


def download(url, dest, expect, byte_limit=None):
    """Resumable download with retries; fails loud. byte_limit is for the smoke test only."""
    dest = Path(dest)
    part = dest.with_suffix(dest.suffix + ".part")
    if dest.exists() and dest.stat().st_size == expect:
        return
    t0 = time.time()
    attempt = 0
    target = byte_limit or expect
    while True:
        check_time()
        if time.time() - t0 > STAGE_BUDGET_S:
            raise TimeoutError(f"blocked > 30 min: {url}")
        have = part.stat().st_size if part.exists() else 0
        if have >= target:
            break
        attempt += 1
        try:
            req = urllib.request.Request(url, headers={"Range": f"bytes={have}-{target - 1}"})
            with urllib.request.urlopen(req, timeout=60) as r, open(part, "ab") as f:
                if r.status not in (200, 206):
                    raise IOError(f"HTTP {r.status}")
                if r.status == 200 and have:
                    f.truncate(0)  # server ignored Range; restart
                    have = 0
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
                    with LOCK:
                        STATE["bytes_down"] += len(b)
        except Exception as e:
            with LOCK:
                STATE["last_error"] = f"{type(e).__name__}: {e} ({url}, attempt {attempt})"
            log(f"download error {STATE['last_error']}")
            time.sleep(min(60, 5 * attempt))
    if byte_limit is None:
        if part.stat().st_size != expect:
            raise IOError(f"size mismatch {part.stat().st_size} != {expect} for {url}")
        part.replace(dest)
    else:
        part.replace(dest)


# ---------- geometry ----------
def unit(lat_deg, lon_deg):
    la, lo = np.radians(lat_deg), np.radians(lon_deg)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=-1)


def gc_km(u, v, radius):
    cross = np.linalg.norm(np.cross(u, v), axis=-1)
    dot = np.sum(u * v, axis=-1)
    return radius * np.arctan2(cross, dot)


# ---------- PRP ----------
def col(block, name):
    s, w = COLS[name]
    return np.ascontiguousarray(block[:, s - 1:s - 1 + w]).view(f"S{w}").ravel().astype(np.float64)


def prp_scan(path, sites, limit_rows=None):
    """One pass. Returns per-site selected rows (max radius) and whole-file sanity counts."""
    mm = np.memmap(path, dtype=np.uint8, mode="r", offset=HDR)
    nrec = mm.size // REC
    if limit_rows is not None:
        nrec = min(nrec, limit_rows)
    elif mm.size != REC * 2_880_000:
        raise RuntimeError(f"PRP record count {mm.size / REC} != 2,880,000 (failure-first check)")
    mm = mm[:nrec * REC].reshape(nrec, REC)
    rmax = max([MOON_R_PRIMARY, *MOON_R_SENS])
    sv = {k: unit(v["lat"], v["lon"]) for k, v in sites.items()}
    sel = {k: [] for k in sites}
    n_tmax_lt = n_tmax_bad = n_rows = 0
    step = 200_000
    for i in range(0, nrec, step):
        check_time()
        blk = mm[i:i + step]
        clon, clat = col(blk, "clon"), col(blk, "clat")
        tmax = col(blk, "tmax")
        ok = np.isfinite(tmax) & (tmax > 0) & (tmax < 500)
        n_tmax_bad += int((~ok).sum())
        n_tmax_lt += int((ok & (tmax < COLD_TRAP_K)).sum())
        n_rows += len(blk)
        u = unit(clat, clon)
        for k, v in sv.items():
            d = gc_km(u, v[None, :], R_MOON_KM)
            idx = np.nonzero(d <= rmax)[0]
            if idx.size:
                sub = blk[idx]
                verts = np.stack([np.ascontiguousarray(sub[:, s - 1:s + 11]).view("S12").ravel().astype(np.float64)
                                  for s in VERT_START], axis=1)
                a = verts[:, 0:3]; b = verts[:, 3:6]; c = verts[:, 6:9]
                area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
                sel[k].append(np.column_stack([d[idx], col(sub, "tavg"), col(sub, "tmax"), col(sub, "ice"), area]))
        with LOCK:
            STATE["pct"] = 40 + 30 * (i + step) / nrec
        if (i // step) % 5 == 0:
            log(f"prp scan {min(i + step, nrec)}/{nrec} rows")
    out = {k: (np.vstack(v) if v else np.empty((0, 5))) for k, v in sel.items()}
    return out, dict(n_rows=n_rows, n_tmax_below_110=n_tmax_lt, n_tmax_unparsed_or_out_of_range=n_tmax_bad)


def pct(a, q):
    return float(np.percentile(a, q)) if a.size else None


def prp_rows(site, arr, r_km, suffix, meta):
    m = arr[:, 0] <= r_km
    a = arr[m]
    rows = []

    def add(layer, stat, value, units):
        rows.append(dict(site_slug=site, body="moon", layer=layer, stat=stat + suffix, value=value, units=units,
                         product=PRODUCT_PRP, version=VERSION_PRP, source_url=PRP_URL, sha256=meta["sha"]))

    n = int(a.shape[0])
    add("prp_triangles", "n", n, "count")
    if n < 20:
        add("prp_triangles", "flag_n_lt_20", 1, "flag")
    if n == 0:
        return rows
    for layer, j, name in (("prp_temp_avg", 1, "temp_avg"), ("prp_temp_max", 2, "temp_max")):
        v = a[:, j]
        good = np.isfinite(v) & (v > 0) & (v < 500)
        add(layer, "n_excluded_out_of_range", int((~good).sum()), "count")
        v = v[good]
        for st, val in (("n", int(v.size)), ("median", pct(v, 50)), ("mean", float(v.mean()) if v.size else None),
                        ("p5", pct(v, 5)), ("p95", pct(v, 95)), ("min", float(v.min()) if v.size else None),
                        ("max", float(v.max()) if v.size else None)):
            add(layer, st, val, "count" if st == "n" else "K")
    tm = a[:, 2]; ar = a[:, 4]
    g = np.isfinite(tm) & (tm > 0) & (tm < 500)
    ct = g & (tm < COLD_TRAP_K)
    add("prp_cold_trap", "threshold_K", COLD_TRAP_K, "K")
    add("prp_cold_trap", "n_below_threshold", int(ct.sum()), "count")
    add("prp_cold_trap", "frac_unweighted", float(ct.sum() / max(g.sum(), 1)), "fraction")
    add("prp_cold_trap", "frac_area_weighted", float(ar[ct].sum() / max(ar[g].sum(), 1e-12)), "fraction")
    ice = a[:, 3]
    inv = ice == -999.0
    val = ice[~inv & np.isfinite(ice)]
    add("prp_ice_depth", "n_total", n, "count")
    add("prp_ice_depth", "n_invalid_999", int(inv.sum()), "count")
    add("prp_ice_depth", "frac_invalid_999", float(inv.sum() / n), "fraction")
    add("prp_ice_depth", "n_valid", int(val.size), "count")
    for st, q in (("median_valid", 50), ("p5_valid", 5), ("p95_valid", 95)):
        add("prp_ice_depth", st, pct(val, q), "m")
    # deviation 11: the file also holds -1.0 in 100,319 records; the label does not define it. Primary rows above are
    # unchanged (as pre-registered); these supplemental rows report it separately.
    m1 = val == -1.0
    val2 = val[~m1]
    add("prp_ice_depth", "n_minus1_undocumented", int(m1.sum()), "count")
    add("prp_ice_depth", "frac_minus1_undocumented", float(m1.sum() / n), "fraction")
    for st, q in (("median_valid_excl_minus1", 50), ("p5_valid_excl_minus1", 5), ("p95_valid_excl_minus1", 95)):
        add("prp_ice_depth", st, pct(val2, q), "m")
    return rows


# ---------- TES ----------
def tes_rows(site, meta):
    s = SITES[site]
    rows = []
    sv = unit(s["lat"], s["lon"])
    r0 = int(round(1799.5 - s["lat"] * 20))
    c0 = int(round(s["lon"] * 20 + 3599.5))
    w = 20
    rr, cc = np.meshgrid(np.arange(r0 - w, r0 + w + 1), np.arange(c0 - w, c0 + w + 1), indexing="ij")
    lat = (1799.5 - rr) / 20.0
    lon = (cc - 3599.5) / 20.0
    d = gc_km(unit(lat, lon), sv, R_MARS_KM)
    inside = d <= MARS_R
    near = np.unravel_index(np.argmin(d), d.shape)
    for tag, mp, mk in (("day", "global_ti_day_2007.img", "global_ti_msk_day_2007.img"),
                        ("night", "global_ti_night_2007.img", "global_ti_msk_night_2007.img")):
        ti = np.fromfile(CACHE / mp, dtype=">i2").reshape(3600, 7200)[rr, cc].astype(float)
        mask = np.fromfile(CACHE / mk, dtype=">u1").reshape(3600, 7200)[rr, cc]
        layer = f"tes_ti_{tag}"

        def add(stat, value, units):
            rows.append(dict(site_slug=site, body="mars", layer=layer, stat=stat, value=value, units=units,
                             product=PRODUCT_TES, version=VERSION_TES, source_url=TES_BASE + mp, sha256=meta["sha"][mp]))

        pos = ti > 0
        sel = inside
        v_all = ti[sel & pos]
        interp = (mask == 0)
        v_non = ti[sel & pos & ~interp]
        n_in = int(sel.sum())
        add("n_pixels_in_R", n_in, "count")
        add("n_nonpositive_excluded", int((sel & ~pos).sum()), "count")
        add("n_value_4999_in_R", int((sel & (ti == 4999)).sum()), "count")  # whole-map max is 4999, possible cap (deviation 9)
        add("n_interpolated", int((sel & interp).sum()), "count")
        fi = float((sel & interp).sum() / max(n_in, 1))
        add("frac_interpolated", fi, "fraction")
        for st, val in (("median", pct(v_all, 50)), ("p5", pct(v_all, 5)), ("p95", pct(v_all, 95)),
                        ("min", float(v_all.min()) if v_all.size else None),
                        ("max", float(v_all.max()) if v_all.size else None)):
            add(st, val, "J m-2 K-1 s-1/2")
        add("n_noninterp", int(v_non.size), "count")
        add("median_noninterp", pct(v_non, 50), "J m-2 K-1 s-1/2")
        add("nearest_pixel_value", float(ti[near]), "J m-2 K-1 s-1/2")
        add("nearest_pixel_interpolated", int(interp[near]), "flag")
        basis = "noninterp" if fi > 0.5 else "all"
        add("primary_basis", basis, "label")
        add("primary_median", pct(v_non if basis == "noninterp" else v_all, 50), "J m-2 K-1 s-1/2")
    return rows


def not_covered_rows():
    rows = []
    def nc(site, body, layer):
        rows.append(dict(site_slug=site, body=body, layer=layer, stat="not_covered", value="", units="", product="none",
                         version="", source_url="", sha256=""))
    for s in ("connecting_ridge_c1", "shackleton_rim"):
        nc(s, "moon", "rcp_diurnal_range")
        nc(s, "moon", "pcp_diurnal_range")
    for s in ("connecting_ridge_c1", "shackleton_rim", "jezero", "arcadia"):
        pass
    nc("jezero", "mars", "surface_temperature")
    for layer in ("tes_ti_day", "tes_ti_night", "surface_temperature"):
        nc("arcadia", "mars", layer)
    return rows


def write_csv(rows):
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    cols = ["site_slug", "body", "layer", "stat", "value", "units", "product", "version", "source_url", "sha256"]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            r = dict(r)
            if isinstance(r["value"], float):
                r["value"] = f"{r['value']:.6g}"
            elif r["value"] is None:
                r["value"] = ""
            w.writerow(r)


def write_ledger(files):
    with open(OUT_LEDGER, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["file", "url", "bytes", "sha256", "date_pulled_ist", "doi"])
        for name, (url, p, doi) in files.items():
            pp = Path(p)
            w.writerow([name, url, pp.stat().st_size, sha256_file(pp),
                        dt.datetime.fromtimestamp(pp.stat().st_mtime, IST).isoformat(timespec="seconds"), doi])


# ---------- stages ----------
def run(smoke):
    CACHE.mkdir(parents=True, exist_ok=True)
    done = load_done()
    stop = threading.Event()
    threading.Thread(target=status_thread, args=(stop,), daemon=True).start()
    meta = {"sha": {}}
    free = shutil.disk_usage(str(ROOT)).free
    if free < 3e9:
        raise RuntimeError(f"disk free {free / 1e9:.1f} GB < 3 GB")
    log(f"download estimate: PRP south {PRP_BYTES / 1e6:.0f} MB + TES maps/masks {sum(TES_BYTES.values()) / 1e6:.0f} MB "
        f"= {(PRP_BYTES + sum(TES_BYTES.values())) / 1e9:.2f} GB; free disk {free / 1e9:.0f} GB")
    try:
        # --- TES ---
        if smoke or "tes_dl" not in done:
            set_stage("tes download", 5)
            names = TES_FILES if not smoke else ["global_ti_day_2007.img", "global_ti_msk_day_2007.img"]
            for n in names:
                size = head_len(TES_BASE + n)
                if size != TES_BYTES[n]:
                    log(f"NOTE size of {n} is {size}, expected {TES_BYTES[n]}")
                download(TES_BASE + n, CACHE / n, size)
            if not smoke:
                done["tes_dl"] = True; save_done(done)
        for n in TES_FILES:
            if (CACHE / n).exists():
                meta["sha"][n] = sha256_file(CACHE / n)
        rows = []
        if smoke:
            set_stage("smoke tes (jezero)", 50)
            rows_j = tes_rows_smoke("jezero", meta)
            for r in rows_j[:12]:
                log(f"SMOKE {r['site_slug']} {r['layer']} {r['stat']} = {r['value']}")
            set_stage("smoke prp (first 20 MB range)", 70)
            part = CACHE / "smoke_prp_head.tab"
            nbytes = HDR + REC * 100_000
            download(PRP_URL, part, PRP_BYTES, byte_limit=nbytes)
            two = {k: SITES[k] for k in ("shackleton_rim", "connecting_ridge_c1")}
            sel, san = prp_scan(part, two, limit_rows=100_000)
            log(f"SMOKE prp sanity {san}; triangles within 10 km in first 100k records: "
                f"{ {k: int(v.shape[0]) for k, v in sel.items()} }")
            rr = prp_rows("shackleton_rim", sel["shackleton_rim"], 5.0, "", {"sha": "smoke"})
            log(f"SMOKE prp rows produced: {len(rr)}")
            # parse check on a record
            mm = np.memmap(part, dtype=np.uint8, mode="r", offset=HDR).reshape(-1, REC)
            log("SMOKE sample record: " + bytes(mm[12345]).decode("ascii", "replace").rstrip())
            log(f"SMOKE sample parsed clon,clat,tavg,tmax,ice = {[float(col(mm[12345:12346], k)[0]) for k in ('clon','clat','tavg','tmax','ice')]}")
            log("SMOKE OK")
            write_status("smoke done")
            return
        # --- PRP ---
        prp = CACHE / PRP_FILE
        if "prp_dl" not in done:
            set_stage("prp download", 10)
            size = head_len(PRP_URL)
            if size != PRP_BYTES:
                log(f"NOTE PRP Content-Length {size} != brief {PRP_BYTES}; label/server wins")
            download(PRP_URL, prp, size)
            done["prp_dl"] = True; save_done(done)
        set_stage("prp sha256", 38)
        meta["sha"]["prp"] = sha256_file(prp)
        set_stage("prp scan and clip", 40)
        sites_moon = {k: v for k, v in SITES.items() if v["body"] == "moon"}
        sel, san = prp_scan(prp, sites_moon)
        log(f"prp sanity {san}")
        if san["n_tmax_below_110"] == 0:
            raise RuntimeError("no temp_max < 110 K anywhere in the south file: parsing fault (failure-first check)")
        json.dump(san, open(CACHE / "prp_sanity.json", "w"))
        pm = {"sha": meta["sha"]["prp"]}
        for k in sites_moon:
            log(f"{k}: triangles within 5 km = {int((sel[k][:, 0] <= 5).sum())}, 2.5 km = {int((sel[k][:, 0] <= 2.5).sum())}, 10 km = {int((sel[k][:, 0] <= 10).sum())}")
            rows += prp_rows(k, sel[k], MOON_R_PRIMARY, "", pm)
            rows += prp_rows(k, sel[k], MOON_R_SENS[0], "_R2p5km", pm)
            rows += prp_rows(k, sel[k], MOON_R_SENS[1], "_R10km", pm)
        for k in sites_moon:
            rows.append(dict(site_slug=k, body="moon", layer="prp_sanity", stat="n_south_file_temp_max_below_110K",
                             value=san["n_tmax_below_110"], units="count", product=PRODUCT_PRP, version=VERSION_PRP,
                             source_url=PRP_URL, sha256=meta["sha"]["prp"]))
        # --- Mars ---
        set_stage("tes extract", 75)
        rows += tes_rows("jezero", meta)
        rows += not_covered_rows()
        set_stage("write outputs", 90)
        write_csv(rows)
        files = {PRP_FILE: (PRP_URL, prp, "10.17189/wj0s-w188")}
        for n in TES_FILES:
            files[n] = (TES_BASE + n, CACHE / n, "10.17189/1519489")
        write_ledger(files)
        done["outputs"] = True; save_done(done)
        with LOCK:
            STATE["pct"] = 100
        write_status("complete")
        log(f"B DONE, outputs written: {OUT_CSV} ({len(rows)} rows)")
    except BaseException as e:
        with LOCK:
            STATE["last_error"] = f"FATAL {type(e).__name__}: {e}"
        log("FAILED " + traceback.format_exc())
        write_status("FAILED")
        raise
    finally:
        stop.set()


def tes_rows_smoke(site, meta):
    """Day-map-only variant for the smoke test (night files not downloaded yet)."""
    s = SITES[site]
    sv = unit(s["lat"], s["lon"])
    r0 = int(round(1799.5 - s["lat"] * 20)); c0 = int(round(s["lon"] * 20 + 3599.5))
    rr, cc = np.meshgrid(np.arange(r0 - 20, r0 + 21), np.arange(c0 - 20, c0 + 21), indexing="ij")
    d = gc_km(unit((1799.5 - rr) / 20.0, (cc - 3599.5) / 20.0), sv, R_MARS_KM)
    ti = np.fromfile(CACHE / "global_ti_day_2007.img", dtype=">i2").reshape(3600, 7200)[rr, cc].astype(float)
    mk = np.fromfile(CACHE / "global_ti_msk_day_2007.img", dtype=">u1").reshape(3600, 7200)[rr, cc]
    ins = d <= MARS_R
    rows = [dict(site_slug=site, layer="tes_ti_day", stat="n_pixels_in_R", value=int(ins.sum())),
            dict(site_slug=site, layer="tes_ti_day", stat="median", value=float(np.median(ti[ins & (ti > 0)]))),
            dict(site_slug=site, layer="tes_ti_day", stat="min", value=float(ti[ins].min())),
            dict(site_slug=site, layer="tes_ti_day", stat="max", value=float(ti[ins].max())),
            dict(site_slug=site, layer="tes_ti_day", stat="frac_interpolated", value=float((mk[ins] == 0).mean())),
            dict(site_slug=site, layer="tes_ti_day", stat="whole_map_min_max", value=str((int(np.fromfile(CACHE / 'global_ti_day_2007.img', dtype='>i2').min()), int(np.fromfile(CACHE / 'global_ti_day_2007.img', dtype='>i2').max()))))]
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--full", action="store_true")
    a = ap.parse_args()
    if not (a.smoke or a.full):
        ap.error("pass --smoke or --full")
    try:
        run(a.smoke)
    except SystemExit as e:
        log(f"STOP: {e}")
        write_status(f"stopped: {e}")
        sys.exit(2)
