"""Terrain masking and single climate band cost probes, 400-tile boxes (60 km half-width), Drive folder gsop_probe.

    uv run python scripts/ee_terrain_probe.py terrain   # Lonar terrain unmasked + masked, Atacama terrain masked, Atacama water_index
    uv run python scripts/ee_terrain_probe.py climate   # t_mean, t_coldest, ti_proxy, dust_index, silica_index on Atacama, one task each
    uv run python scripts/ee_terrain_probe.py <stage> --resume   # poll recorded tasks only

Polls every 30 s, cap 60 min (queue wait included), writes results/ee_terrain_probe.json (gitignored). Total spend guard: SPEND_CAP EECU-s over all
recorded probes; the polling loop cancels still-running tasks if the reported usage of finished ones passes the cap.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings

warnings.filterwarnings("ignore")
import ee  # noqa: E402

from gsop.earth import gee_export as GE  # noqa: E402
from gsop.provenance import ROOT  # noqa: E402

BOXES = {"lonar": (76.51, 19.98), "atacama": (-68.2, -23.5)}
HALF_KM = 60.0
FOLDER = "gsop_probe"
POLL_S = 30
CAP_S = 60 * 60
SPEND_CAP = 4000.0
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "CANCEL_REQUESTED"}
OUT = ROOT / "results" / "ee_terrain_probe.json"


def plan(stage: str) -> dict[str, tuple[str, ee.Image]]:
    if stage == "terrain":
        mask = GE.gate_pass_mask()
        return {
            "P1_lonar_terrain_unmasked": ("lonar", GE.terrain_bands()),
            "P1_lonar_terrain_masked": ("lonar", GE.terrain_bands(tile_mask=mask)),
            "P2_atacama_terrain_masked": ("atacama", GE.terrain_bands(tile_mask=mask)),
            "P3_atacama_water_index": ("atacama", GE.water_index_band()),
        }
    if stage == "climate":
        c = GE.climate_bands()
        return {f"P3_atacama_{b}": ("atacama", c.select([b] if b != "ti_proxy" else ["ti_proxy", "ti_is_fallback"]))
                for b in ("t_mean", "t_coldest", "ti_proxy", "dust_index", "silica_index")}
    raise SystemExit(f"unknown stage {stage}")


def start(stage: str, res: dict) -> None:
    for name, (box, img) in plan(stage).items():
        lon, lat = BOXES[box]
        ix0, iy0, w, h = GE.lonlat_box_to_cells(lon, lat, HALF_KM)
        geom, tf = GE.chunk_region(ix0, iy0, w, h)
        img = img.toFloat()
        t = ee.batch.Export.image.toDrive(image=img, description=f"probe_{name}", folder=FOLDER,
                                          fileNamePrefix=f"probe_{name}", region=geom, crs=GE.CRS_WKT,
                                          crsTransform=tf, maxPixels=int(1e10), fileFormat="GeoTIFF")
        t.start()
        res["tasks"][name] = {"id": t.id, "box": box, "cells": [ix0, iy0, w, h], "tiles": w * h,
                              "bands": img.bandNames().getInfo(), "stage": stage, "history": []}
        print(f"started {name} id={t.id}", flush=True)


def spent(res: dict) -> float:
    return sum(((v.get("last") or {}).get("batch_eecu_usage_seconds") or 0.0) for v in res["tasks"].values())


def poll(res: dict, stage: str) -> None:
    t0 = time.time()
    active = {k for k, v in res["tasks"].items() if v["stage"] == stage and v.get("final") is None}
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
        if spent(res) > SPEND_CAP:
            for name in sorted(active):
                ee.data.cancelTask(res["tasks"][name]["id"])
                res["tasks"][name]["note"] = "cancelled: spend cap"
            print("spend cap hit, cancelled running tasks", flush=True)
            break
        if active:
            time.sleep(POLL_S)
    for name in active:
        res["tasks"][name].setdefault("note", f"still running at the {CAP_S // 60} min polling cap; not cancelled")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["terrain", "climate"])
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    GE.init()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    res = json.loads(OUT.read_text()) if OUT.exists() else {"folder": FOLDER, "tasks": {}}
    if not args.resume:
        start(args.stage, res)
        OUT.write_text(json.dumps(res, indent=1))
    poll(res, args.stage)
    for v in res["tasks"].values():
        e = (v.get("last") or {}).get("batch_eecu_usage_seconds")
        v["eecu_per_tile"] = e / v["tiles"] if e is not None else None
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: {"state": (v.get("last") or {}).get("state"),
                          "eecu": (v.get("last") or {}).get("batch_eecu_usage_seconds"),
                          "per_tile": v.get("eecu_per_tile"), "err": (v.get("last") or {}).get("error_message")}
                      for k, v in res["tasks"].items()}, indent=1))
    print("total reported EECU-s", spent(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
