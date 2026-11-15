"""Measure the real Earth Engine batch cost of the Earth export, and of two cheaper variants, on one 60 km box.

Probes (same box, same grid, Drive folder gsop_probe):
    A  full stack, gee_export.full_stack()
    B  gate layers only, gee_export.landcover_bands()
    C  terrain from a 90 m DEM (CGIAR/SRTM90_V4) on a 100 m working grid, 500 m slope baseline, roughness windows of 3
       and 10 cells (300 m and 1000 m)

    uv run python scripts/ee_cost_probe.py            # start A, B, C, poll every 30 s for at most 20 min, write results
    uv run python scripts/ee_cost_probe.py --resume   # poll tasks recorded in results/ee_cost_probe.json, do not start

Only three small export tasks are started. Nothing is cancelled. Results go to results/ee_cost_probe.json (gitignored).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
import ee  # noqa: E402

from gsop.earth import gee_export as GE  # noqa: E402
from gsop.provenance import ROOT  # noqa: E402

LON, LAT, HALF_KM = 76.51, 19.98, 60.0
FOLDER = "gsop_probe"
POLL_S = 30
CAP_S = 20 * 60
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "CANCEL_REQUESTED"}
OUT = ROOT / "results" / "ee_cost_probe.json"
GATES = {"ndvi_median": ("<=", 0.2), "water_ice_frac": ("<=", 0.5), "built_crop_frac": ("<=", 0.2)}


def dem90_catalog() -> dict:
    """Which 90 m DEM ids resolve live, with band names and nominal scale."""
    out = {}
    for asset_id in ("COPERNICUS/DEM/GLO90", "CGIAR/SRTM90_V4"):
        try:
            a = ee.data.getAsset(asset_id)
            img = ee.Image(asset_id) if a.get("type") == "IMAGE" else ee.ImageCollection(asset_id).first()
            out[asset_id] = {"resolves": True, "type": a.get("type"), "bands": img.bandNames().getInfo(),
                             "nominal_scale_m": img.select(0).projection().nominalScale().getInfo()}
        except Exception as e:  # noqa: BLE001
            out[asset_id] = {"resolves": False, "detail": str(e)[:200]}
    return out


def start_probes() -> dict:
    ix0, iy0, w, h = GE.lonlat_box_to_cells(LON, LAT, HALF_KM)
    geom, tf = GE.chunk_region(ix0, iy0, w, h)
    images = {
        "A_full_stack": GE.full_stack(),
        "B_gate_layers": GE.landcover_bands().toFloat(),
        "C_terrain_90m": GE.terrain_bands(100.0, "srtm90", (3, 10)).toFloat(),
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
    """Share of the box tiles that pass the cheap gates, from a direct download of the 4 gate bands (400 pixels)."""
    import io
    import zipfile

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
            if len(tifs) == 1:                    # one multiband file: bands are in the order of img.bandNames()
                arrs.update({b: data[i] for i, b in enumerate(names)})
            else:
                band = next(b for b in names if f".{b}." in n)
                arrs[band] = data[0]
    ok = np.ones(next(iter(arrs.values())).shape, bool)
    valid = np.ones_like(ok)
    for b in GATES:
        valid &= np.isfinite(arrs[b])
    ok &= valid
    ok &= arrs["ndvi_median"] <= 0.2
    ok &= arrs["water_ice_frac"] <= 0.5
    ok &= arrs["built_crop_frac"] <= 0.2
    return {"tiles": int(ok.size), "valid_tiles": int(valid.sum()), "pass": int(ok.sum()),
            "pass_share_of_all": float(ok.sum() / ok.size),
            "per_gate_pass": {b: int(np.nansum(arrs[b] <= GATES[b][1])) for b in GATES},
            "bands_read": sorted(arrs),
            "finite_per_band": {b: int(np.isfinite(a).sum()) for b, a in arrs.items()},
            "median_per_band": {b: float(np.nanmedian(a)) for b, a in arrs.items()}, "gates": {k: f"{op} {v}" for k, (op, v) in GATES.items()}}


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
        res["dem90_catalog"] = dem90_catalog()
        OUT.write_text(json.dumps(res, indent=1))
    poll(res)
    if "gate_share" not in res:
        res["gate_share"] = gate_share()
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v.get("last") for k, v in res["tasks"].items()}, indent=1))
    print(json.dumps(res["gate_share"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
