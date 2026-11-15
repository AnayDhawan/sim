"""Query the Mars Climate Database web interface (CGI) for surface temperature at the Jezero target.

    uv run python scripts/mcd_jezero.py --raw-dir data/raw/mcd_jezero_raw

One GET request per (Ls, local time): variable tsurf, climatology average solar scenario (dust=1), flat form defaults
otherwise. Ls and local-time steps come from config/targets.yaml mars_climate. Writes
  docs/evidence/mcd_v6_2_jezero_tsurf_2026-11-14.csv       one row per request (ls_deg, local_time_h, tsurf_k, kind)
  docs/evidence/mcd_v6_2_jezero_tsurf_2026-11-14.meta.json request template, version line, counts, run time
and every raw HTML response into --raw-dir (an empty or new folder, untrusted text, only parsed with a regex).
Every row has kind `point`; `targets/mars.py mcd_stats` reduces the table. (A first run also sent diumean=on requests as a
cross-check; for a single point the service ignores that flag and returns the local-time-0 value, so they were dropped.)
The package called `mcd` on PyPI is a speech-processing tool, not this database, and the full MCD is a Fortran
distribution that needs a request to LMD; the documented web interface is used instead.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from gsop.config import load_all
from gsop.provenance import ROOT
from gsop.targets.mars import MCD_COLS, parse_mcd_tsurf

CGI = "https://www-mars.lmd.jussieu.fr/mcd_python/cgi-bin/mcdcgi.py"
OUT = ROOT / "docs" / "evidence" / "mcd_v6_2_jezero_tsurf_2026-11-14"


def request_url(lat: float, lon_e: float, ls: float, lt: float, diumean: bool = False) -> str:
    q = {"var1": "tsurf", "var2": "none", "var3": "none", "var4": "none", "datekeyhtml": "1", "ls": f"{ls:g}",
         "localtime": f"{lt:g}", "latitude": f"{lat:g}", "longitude": f"{lon_e:g}", "altitude": "0", "zkey": "3",
         "spacecraft": "none", "isfixedlt": "off", "dust": "1", "hrkey": "1", "averaging": "off", "zonmean": "off",
         "diumean": "on" if diumean else "off", "animation": "off", "dpi": "80", "islog": "off", "iswind": "off"}
    return f"{CGI}?{urllib.parse.urlencode(q)}"


def fetch(url: str, retries: int = 3) -> str:
    for k in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read().decode("utf-8", errors="replace")
        except OSError:
            if k == retries - 1:
                raise
            time.sleep(2.0 * (k + 1))
    raise RuntimeError("unreachable")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path, required=True, help="new or empty folder for the raw responses")
    ap.add_argument("--pause-s", type=float, default=0.15)
    a = ap.parse_args()
    a.raw_dir.mkdir(parents=True, exist_ok=True)
    if any(a.raw_dir.iterdir()):
        raise SystemExit(f"{a.raw_dir} is not empty")
    cfg = load_all()
    t = cfg["targets"]["mars"]["jezero"]
    mc = cfg["targets"]["mars_climate"]
    ls_list = [float(x) for x in range(0, 360, int(mc["ls_step_deg"]))]
    lt_list = [float(x) for x in range(0, 24, int(mc["local_time_step_h"]))]
    rows, versions = [], set()
    t0 = time.time()
    jobs = [(ls, lt, False) for ls in ls_list for lt in lt_list]
    for i, (ls, lt, dm) in enumerate(jobs):
        html = fetch(request_url(t["lat"], t["lon_e"], ls, lt, dm))
        (a.raw_dir / f"ls{ls:05.1f}_lt{lt:04.1f}_{'diumean' if dm else 'point'}.html").write_text(html, encoding="utf-8")
        v, head = parse_mcd_tsurf(html)
        versions.add(head.split(" Ls")[0].strip())
        rows.append({"ls_deg": ls, "local_time_h": lt, "tsurf_k": v, "kind": "service_diurnal_mean" if dm else "point"})
        time.sleep(a.pause_s)
        if i % 100 == 0:
            print(f"{i}/{len(jobs)} requests, {time.time() - t0:.0f} s")
    df = pd.DataFrame(rows, columns=MCD_COLS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT.with_suffix(".csv"), index=False, float_format="%.5f")
    meta = {"script": "scripts/mcd_jezero.py", "cgi": CGI, "lat": t["lat"], "lon_e": t["lon_e"],
            "request_example": request_url(t["lat"], t["lon_e"], 0, 12), "versions_seen": sorted(versions),
            "n_requests": len(jobs), "ls_deg": ls_list, "local_time_h": lt_list,
            "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seconds": round(time.time() - t0, 1)}
    OUT.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    print(f"[PASS] {len(df)} rows -> {OUT.with_suffix('.csv')}; versions {sorted(versions)}")


if __name__ == "__main__":
    main()
