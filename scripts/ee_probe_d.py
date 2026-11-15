"""Probe D: split the Earth export cost on one barren 60 km box (Atacama), three separate batch tasks.

    D1  terrain_bands() at the default 33.333 m only
    D2  climate_bands() only
    D3  landcover_bands() only (the 4 gate bands)

    uv run python scripts/ee_probe_d.py            # start D1, D2, D3, poll every 30 s for at most 25 min, write results
    uv run python scripts/ee_probe_d.py --resume   # poll the tasks recorded in results/ee_probe_d.json, do not start

Drive folder gsop_probe. Results go to results/ee_probe_d.json (gitignored).
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import warnings
import zipfile

import numpy as np

warnings.filterwarnings("ignore")
import ee  # noqa: E402

from gsop.earth import gee_export as GE  # noqa: E402
from gsop.provenance import ROOT  # noqa: E402

LON, LAT, HALF_KM = -68.2, -23.5, 60.0
FOLDER = "gsop_probe"
POLL_S = 30
CAP_S = 25 * 60
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "CANCEL_REQUESTED"}
OUT = ROOT / "results" / "ee_probe_d.json"
GATES = {"ndvi_median": 0.2, "water_ice_frac": 0.5, "built_crop_frac": 0.2}


def start_probes() -> dict:
    ix0, iy0, w, h = GE.lonlat_box_to_cells(LON, LAT, HALF_KM)
    geom, tf = GE.chunk_region(ix0, iy0, w, h)
    images = {
        "D1_terrain_33m": GE.terrain_bands().toFloat(),
        "D2_climate": GE.climate_bands().toFloat(),
        "D3_landcover_gate": GE.landcover_bands().toFloat(),
    }
    tasks = {}
    for name, img in images.items():
        t = ee.batch.Export.image.toDrive(image=img, description=f"probe_{name}", folder=FOLDER,
                                          fileNamePrefix=f"probe_{name}", region=geom, crs=GE.CRS_WKT,
                                          crsTransform=tf, maxPixels=int(1e10), fileFormat="GeoTIFF")
        t.start()
        tasks[name] = {"id": t.id, "bands": img.bandNames().getInfo(), "history": []}
        print(f"started {name} id={t.id}", flush=True)
    return {"box": {"lon": LON, "lat": LAT, "half_km": HALF_KM, "cells": [ix0, iy0, w, h], "tiles": w * h},
            "folder": FOLDER, "started_unix": time.time(), "tasks": tasks}


def poll(res: dict) -> None:
    t0 = time.time()
    active = {k for k, v in res["tasks"].items() if v.get("final") is None}
    while active and time.time() - t0 < CAP_S:
        for name in sorted(active):
            st = ee.data.getTaskStatus(res["tasks"][name]["id"])[0]
            rec = {"polled_unix": time.time(), **{k: st.get(k) for k in (
                "state", "creation_timestamp_ms", "start_timestamp_ms", "update_timestamp_ms",
                "batch_eecu_usage_seconds", "error_message")}}
            res["tasks"][name]["history"].append(rec)
            res["tasks"][name]["last"] = rec
            print(f"{time.strftime('%H:%M:%S')} {name} {rec['state']} eecu={rec['batch_eecu_usage_seconds']}", flush=True)
            if rec["state"] in TERMINAL:
                res["tasks"][name]["final"] = rec
                active.discard(name)
        OUT.write_text(json.dumps(res, indent=1))
        if active:
            time.sleep(POLL_S)
    for name in active:
        res["tasks"][name]["note"] = f"still running at the {CAP_S // 60} min polling cap; not cancelled"
        print(f"{name}: still running at cap, stopped polling (not cancelled)", flush=True)


def gate_share() -> dict:
    """Share of the box tiles passing the three gates, from a direct download of the 4 gate bands (400 pixels)."""
    import rasterio
    import requests

    ix0, iy0, w, h = GE.lonlat_box_to_cells(LON, LAT, HALF_KM)
    geom, tf = GE.chunk_region(ix0, iy0, w, h)
    img = GE.landcover_bands().toFloat()
    url = img.getDownloadURL({"region": geom, "crs": GE.CRS_WKT, "crs_transform": tf, "format": "ZIPPED_GEO_TIFF",
                              "filePerBand": True})
    r = requests.get(url, timeout=600)
    r.raise_for_status()
    names = img.bandNames().getInfo()
    arrs = {}
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        tifs = [n for n in z.namelist() if n.endswith(".tif")]
        for n in tifs:
            with rasterio.open(io.BytesIO(z.read(n))) as ds:
                data = ds.read().astype("float64")
                nodata = ds.nodata
            if nodata is not None and not np.isnan(nodata):
                data[data == nodata] = np.nan
            if len(tifs) == 1:
                arrs.update({b: data[i] for i, b in enumerate(names)})
            else:
                arrs[next(b for b in names if f".{b}." in n)] = data[0]
    shape = next(iter(arrs.values())).shape
    valid = np.ones(shape, bool)
    for b in GATES:
        valid &= np.isfinite(arrs[b])
    ok = valid & (arrs["ndvi_median"] <= 0.2) & (arrs["water_ice_frac"] <= 0.5) & (arrs["built_crop_frac"] <= 0.2)
    return {"tiles": int(ok.size), "valid_tiles": int(valid.sum()), "pass": int(ok.sum()),
            "pass_share_of_all": float(ok.sum() / ok.size),
            "per_gate_pass": {b: int(np.nansum(arrs[b] <= GATES[b])) for b in GATES},
            "finite_per_band": {b: int(np.isfinite(a).sum()) for b, a in arrs.items()},
            "median_per_band": {b: float(np.nanmedian(a)) for b, a in arrs.items()},
            "gates": {k: f"<= {v}" for k, v in GATES.items()}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    GE.init()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if args.resume:
        res = json.loads(OUT.read_text())
    else:
        res = start_probes()
        OUT.write_text(json.dumps(res, indent=1))
    poll(res)
    tiles = res["box"]["tiles"]
    for v in res["tasks"].values():
        e = (v.get("last") or {}).get("batch_eecu_usage_seconds")
        v["eecu_per_tile"] = e / tiles if e is not None else None
    if "gate_share" not in res:
        res["gate_share"] = gate_share()
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: {"state": (v.get("last") or {}).get("state"),
                          "eecu": (v.get("last") or {}).get("batch_eecu_usage_seconds"),
                          "per_tile": v.get("eecu_per_tile")} for k, v in res["tasks"].items()}, indent=1))
    print(json.dumps(res["gate_share"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
