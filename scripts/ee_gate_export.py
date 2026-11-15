"""Global gate-only export to Google Drive: landcover_bands() (4 gate bands) for the whole 6 km grid, 10 x 4 chunks.

    uv run python scripts/ee_gate_export.py --plan        # print the plan, start nothing
    uv run python scripts/ee_gate_export.py --calibrate   # start 3 chunks (ocean, polar, continental), poll, extrapolate
    uv run python scripts/ee_gate_export.py --rest        # if the extrapolation is <= 60,000 EECU-s, start the other 37
    uv run python scripts/ee_gate_export.py --poll        # resume polling the tasks recorded in the results file

Drive folder gsop_gate, one GeoTIFF per chunk. Polling every 60 s. Safety stop: if the summed batch_eecu_usage_seconds of
finished tasks exceeds STOP_EECU, the unfinished tasks are cancelled with ee.data.cancelTask. Nothing here starts the full
stack, climate or terrain export. Results go to results/ee_gate_export.json (gitignored). The Drive files are read with
scripts/ee_gate_stats.py after download.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings

import numpy as np

warnings.filterwarnings("ignore")
import ee  # noqa: E402

from gsop.earth import gee_export as GE  # noqa: E402
from gsop.grid import Grid  # noqa: E402
from gsop.provenance import ROOT  # noqa: E402

POLL_S = 60
CAP_S = 120 * 60
STOP_EECU = 60_000.0
DECISION_EECU = 60_000.0
PREDICTION = 44_439.0
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "CANCEL_REQUESTED"}
OUT = ROOT / "results" / "ee_gate_export.json"
LAND_JSON = ROOT / "results" / "gate_chunk_land_share.json"
# Grid rows are 90N-30N, 30N-0, 0-30S, 30S-90S; columns are 36 degrees of longitude from 180W.
CALIBRATION = {
    "ocean": "gate_6km_r01_c00",         # 0-30N, 180W-144W: central Pacific, Hawaii
    "polar": "gate_6km_r03_c05",         # 30S-90S, 0-36E: Antarctica (Queen Maud Land), Southern Ocean, South Africa tip
    "continental": "gate_6km_r01_c05",   # 0-30N, 0-36E: Sahara, Sahel, northern Congo basin
}


def base_of(name: str) -> str:
    """Chunk name of a task name (row 0 chunks are exported in pieces named <chunk>_p0 ...)."""
    import re

    return re.match(r"gate_6km_r\d\d_c\d\d", name).group(0)


def task_entry(c: dict) -> dict:
    return {"id": c["id"], "chunk": c["chunk"], "cells": c["cells"], "exported_cells": c["exported_cells"]}


def save(res: dict) -> None:
    OUT.write_text(json.dumps(res, indent=1))


def load() -> dict:
    return json.loads(OUT.read_text())


def finished_eecu(res: dict) -> float:
    return sum((t.get("final") or {}).get("batch_eecu_usage_seconds") or 0.0 for t in res["tasks"].values())


def latest_eecu(res: dict) -> float:
    return sum((t.get("last") or {}).get("batch_eecu_usage_seconds") or 0.0 for t in res["tasks"].values())


def poll(res: dict) -> str:
    """Poll every unfinished task. Returns done, stopped (safety stop), failed or cap."""
    t0 = time.time()
    while time.time() - t0 < CAP_S:
        active = [n for n, v in res["tasks"].items() if v.get("final") is None]
        if not active:
            return "failed" if res.get("failed") else "done"
        for name in active:
            try:
                st = ee.data.getTaskStatus(res["tasks"][name]["id"])[0]
            except Exception as e:  # noqa: BLE001  (transient network error: keep polling)
                print(f"{time.strftime('%H:%M:%S')} status call failed for {name}: {str(e)[:100]}", flush=True)
                continue
            rec = {"polled_unix": time.time(), **{k: st.get(k) for k in (
                "state", "creation_timestamp_ms", "start_timestamp_ms", "update_timestamp_ms",
                "batch_eecu_usage_seconds", "error_message")}}
            res["tasks"][name]["last"] = rec
            if rec["state"] in TERMINAL:
                res["tasks"][name]["final"] = rec
        states: dict = {}
        for v in res["tasks"].values():
            s = (v.get("last") or {}).get("state")
            states[s] = states.get(s, 0) + 1
        fe = finished_eecu(res)
        print(f"{time.strftime('%H:%M:%S')} states={states} finished_eecu={fe:.1f} latest_eecu={latest_eecu(res):.1f}",
              flush=True)
        save(res)
        bad = {n: v["final"].get("error_message") for n, v in res["tasks"].items()
               if v.get("final") and v["final"]["state"] in ("FAILED", "CANCELLED")}
        if bad and res.get("failed") != bad:
            res["failed"] = bad
            save(res)
            print("task FAILED or CANCELLED (nothing new is started, the other tasks keep being polled):", bad, flush=True)
        if fe > STOP_EECU:
            cancelled = []
            for n, v in res["tasks"].items():
                if v.get("final") is None:
                    ee.data.cancelTask(v["id"])
                    cancelled.append(n)
            res["safety_stop"] = {"finished_eecu": fe, "limit": STOP_EECU, "cancelled": cancelled}
            save(res)
            print(f"SAFETY STOP: finished EECU {fe:.1f} > {STOP_EECU}; cancelled {len(cancelled)} tasks", flush=True)
            return "stopped"
        if all(v.get("final") for v in res["tasks"].values()):
            return "failed" if res.get("failed") else "done"
        time.sleep(POLL_S)
    res["note"] = f"still running at the {CAP_S // 60} min polling cap; not cancelled"
    save(res)
    return "cap"


def chunk_land_share() -> dict[str, float]:
    """Land share per chunk from the MCD12Q1 land mask (class 17 is water) sampled on a 12 km grid, interactive and cheap.
    Used only to describe the mix of chunks, not to decide which tiles pass the gate."""
    if LAND_JSON.exists():
        return json.loads(LAND_JSON.read_text())
    lc = ee.ImageCollection(GE.IDS["lc"]).filterDate(GE.LC_YEAR, "2024-01-01").first().select("LC_Type1")
    land = lc.neq(17).updateMask(lc.mask()).rename("land")
    g = Grid()
    out = {}
    for ch in GE.global_chunks():
        ix0, iy0, w, h = ch["cells"]
        xl, yt = g.x0 + ix0 * g.cell_m, g.y_top - iy0 * g.cell_m
        yb = yt - h * g.cell_m
        for clip in (0.0, 0.5e6, 1.0e6, 1.5e6, 2.0e6):   # polar chunks: MODIS sinusoidal cannot be sampled at the very pole
            geom = ee.Geometry.Rectangle([xl, yb + clip, xl + w * g.cell_m, yt], proj=GE.CRS_WKT, geodesic=False)
            try:
                d = land.reduceRegion(ee.Reducer.mean(), geom, crs=GE.CRS_WKT,
                                      crsTransform=[12000, 0, xl, 0, -12000, yt], maxPixels=int(1e9)).getInfo()
                break
            except ee.EEException:
                d = None
        if d is None:
            out[ch["name"]] = None
        elif clip:
            # the clipped band is polar ice (class 15, counted as land); weight it in as land
            frac = clip / (h * g.cell_m)
            out[ch["name"]] = (d.get("land") or 0.0) * (1 - frac) + frac
        else:
            out[ch["name"]] = d.get("land")
        print(ch["name"], out[ch["name"]], f"clip={clip if d is not None else 'failed'}", flush=True)
    LAND_JSON.write_text(json.dumps(out, indent=1))
    return out


def extrapolate(res: dict, land: dict[str, float]) -> dict:
    """Total for all 40 chunks from the measured chunks. Model 1: per-chunk cost = a + b x land share, fitted to the
    measured chunks (least squares). Model 2: mean of the measured chunk costs x 40. Model 3 (upper bound): the most
    expensive measured chunk x 40. The decision uses the model-1 total, with model 3 reported beside it."""
    by_chunk: dict[str, list] = {}
    for n, v in res["tasks"].items():
        by_chunk.setdefault(base_of(n), []).append(v)
    meas = {c: sum(v["final"]["batch_eecu_usage_seconds"] for v in vs) for c, vs in by_chunk.items()
            if all(v.get("final") and v["final"]["state"] == "COMPLETED" for v in vs)}
    names = sorted(meas)
    if len(names) < 2:
        return {"measured": meas, "note": "fewer than 2 completed chunks, no extrapolation"}
    x = np.array([land[n] for n in names], float)
    y = np.array([meas[n] for n in names], float)
    b, a = np.polyfit(x, y, 1)
    all_names = [c["name"] for c in GE.global_chunks()]
    fit = {n: float(max(a + b * land[n], 0.0)) for n in all_names}
    # measured chunks use their measured cost
    est = {n: float(meas.get(n, fit[n])) for n in all_names}
    return {"measured": meas, "land_share_measured": {n: land[n] for n in names},
            "fit_intercept_per_chunk": float(a), "fit_slope_per_unit_land_share": float(b),
            "model1_land_share_fit_total": float(sum(est.values())),
            "model2_mean_x40": float(np.mean(y) * 40), "model3_max_x40": float(y.max() * 40),
            "est_per_chunk": est, "land_share_all": {n: land[n] for n in all_names},
            "note": f"{len(names)} completed chunks, the fit has 2 parameters; it is a rough guide"}


RUN2_STOP_EECU = 62_000.0
RUN2_CAP_S = 180 * 60
MAX_INFLIGHT = 6


def run2_eecu(res: dict) -> float:
    """Summed batch usage of the tasks started in this run (finished tasks and failed or retried attempts)."""
    names = set(res["run2"]["names"])
    tot = sum((v.get("final") or {}).get("batch_eecu_usage_seconds") or 0.0 for n, v in res["tasks"].items() if n in names)
    tot += sum((v.get("final") or {}).get("batch_eecu_usage_seconds") or 0.0
               for n, v in res.get("failed_attempts", {}).items() if n in names)
    return tot


def run_rest(res: dict) -> str:
    """Start the not yet exported chunks (throttled to MAX_INFLIGHT unfinished tasks), poll every 60 s, retry a failed chunk
    once with its failed pieces split in two, stop on RUN2_STOP_EECU, give up at RUN2_CAP_S without cancelling."""
    r2 = res.setdefault("run2", {})
    if "queue" not in r2:
        have = {base_of(t) for t in res["tasks"]}
        todo = [c["name"] for c in GE.global_chunks() if c["name"] not in have]
        pcs = GE.plan_gate_pieces(only=todo)
        pcs.sort(key=lambda p: (p["chunk"][9:12] != "r00", p["name"]))      # top row first: it is the riskiest
        r2.update({"started_unix": time.time(), "queue": pcs, "names": [], "retried": {}, "gave_up": {}})
        save(res)
    img = None
    t0 = time.time()
    while True:
        active = [n for n, v in res["tasks"].items() if v.get("final") is None]
        for name in active:
            try:
                st = ee.data.getTaskStatus(res["tasks"][name]["id"])[0]
            except Exception as e:  # noqa: BLE001  (transient network error: keep polling)
                print(f"{time.strftime('%H:%M:%S')} status call failed for {name}: {str(e)[:100]}", flush=True)
                continue
            rec = {"polled_unix": time.time(), **{k: st.get(k) for k in (
                "state", "creation_timestamp_ms", "start_timestamp_ms", "update_timestamp_ms",
                "batch_eecu_usage_seconds", "error_message")}}
            res["tasks"][name]["last"] = rec
            if rec["state"] in TERMINAL:
                res["tasks"][name]["final"] = rec
        # failures: one retry per chunk, with the failed pieces split in two
        failed = [n for n, v in res["tasks"].items() if n in r2["names"] and (v.get("final") or {}).get("state") == "FAILED"]
        for chunk in sorted({base_of(n) for n in failed}):
            fl = [n for n in failed if base_of(n) == chunk]
            for n in fl:
                res.setdefault("failed_attempts", {})[n] = res["tasks"].pop(n)
            errs = [res["failed_attempts"][n]["final"].get("error_message") for n in fl]
            if r2["retried"].get(chunk):
                r2["gave_up"][chunk] = errs
                print(f"GAVE UP on {chunk}: {errs}", flush=True)
                continue
            r2["retried"][chunk] = True
            retry = []
            for n in fl:
                att = res["failed_attempts"][n]
                retry += GE.split_piece({"name": n, "chunk": chunk, "cells": att["cells"],
                                         "exported_cells": att["exported_cells"]})
            r2["queue"] = retry + r2["queue"]
            print(f"RETRY {chunk}: {[p['name'] for p in retry]} after {errs}", flush=True)
        spent = run2_eecu(res)
        if spent > RUN2_STOP_EECU:
            cancelled = []
            for n, v in res["tasks"].items():
                if v.get("final") is None:
                    ee.data.cancelTask(v["id"])
                    cancelled.append(n)
            r2["safety_stop"] = {"run2_eecu": spent, "limit": RUN2_STOP_EECU, "cancelled": cancelled,
                                 "not_started": [p["name"] for p in r2["queue"]]}
            r2["queue"] = []
            save(res)
            print(f"SAFETY STOP: run EECU {spent:.1f} > {RUN2_STOP_EECU}; cancelled {len(cancelled)}", flush=True)
            return "safety_stop"
        active = [n for n, v in res["tasks"].items() if v.get("final") is None]
        while r2["queue"] and len(active) < MAX_INFLIGHT:
            pc = r2["queue"].pop(0)
            img = img if img is not None else GE.landcover_bands().toFloat()
            GE.start_gate_piece(pc, img=img)
            res["tasks"][pc["name"]] = task_entry(pc)
            r2["names"].append(pc["name"])
            active.append(pc["name"])
        states: dict = {}
        for n, v in res["tasks"].items():
            if n in r2["names"]:
                s_ = (v.get("last") or {}).get("state", "NEW")
                states[s_] = states.get(s_, 0) + 1
        print(f"{time.strftime('%H:%M:%S')} queue={len(r2['queue'])} run_states={states} run_eecu={spent:.1f}", flush=True)
        save(res)
        if not r2["queue"] and not [n for n, v in res["tasks"].items() if v.get("final") is None]:
            return "done"
        if time.time() - t0 > RUN2_CAP_S:
            r2["cap_note"] = f"cap of {RUN2_CAP_S // 60} min reached; unfinished tasks left running, queue not started"
            save(res)
            return "cap"
        time.sleep(POLL_S)


def main() -> int:
    ap = argparse.ArgumentParser()
    g_ = ap.add_mutually_exclusive_group(required=True)
    for f in ("plan", "calibrate", "rest", "poll"):
        g_.add_argument(f"--{f}", action="store_true")
    g_.add_argument("--start", nargs="+", metavar="CHUNK", help="start the named chunks again (a failed one is archived)")
    args = ap.parse_args()
    GE.init()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if args.plan:
        pieces = GE.start_gate_export(start=False)
        print(f"plan: {len({p['chunk'] for p in pieces})} chunks as {len(pieces)} tasks, ee.batch.Export.image.toDrive "
              f"GeoTIFF, folder {GE.GATE_FOLDER}, 4 gate bands, grid {Grid().ncols} x {Grid().nrows}; "
              f"{GE.POLE_TRIM_ROWS} rows trimmed at each pole, top chunk row split in {GE.ROW0_SPLIT}")
        print("calibration chunks:", CALIBRATION)
        return 0
    if args.start:
        res = load()
        skip = set()
        for n in args.start:
            for tn in [t for t in res["tasks"] if base_of(t) == n]:
                old = res["tasks"].pop(tn)
                if (old.get("final") or {}).get("state") == "COMPLETED":
                    res["tasks"][tn] = old
                    skip.add(n)
                else:
                    res.setdefault("failed_attempts", {})[tn] = old
        started = GE.start_gate_export(only=[n for n in args.start if n not in skip])
        for c in started:
            res["tasks"][c["name"]] = task_entry(c)
        res.pop("failed", None)
        save(res)
        print(f"started {len(started)} tasks", flush=True)
    elif args.calibrate:
        if OUT.exists() and load().get("tasks"):
            print("results file already has tasks; use --poll or --rest", flush=True)
            return 2
        started = GE.start_gate_export(only=list(CALIBRATION.values()))
        res = {"folder": GE.GATE_FOLDER, "started_unix": time.time(), "calibration": CALIBRATION,
               "tasks": {c["name"]: task_entry(c) for c in started}}
        save(res)
        print(f"started {len(started)} calibration chunks", flush=True)
    else:
        res = load()
    if args.rest:
        outcome = run_rest(res)
        res["outcome2"] = outcome
        res["total_eecu_all_tasks"] = sum((v.get("final") or {}).get("batch_eecu_usage_seconds") or 0.0
                                          for v in list(res["tasks"].values()) + list(res.get("failed_attempts", {}).values()))
        res["run2_eecu"] = run2_eecu(res)
        save(res)
        print(json.dumps({"outcome": outcome, "run2_eecu": res["run2_eecu"], "all_tasks_eecu": res["total_eecu_all_tasks"],
                          "gave_up": res["run2"]["gave_up"], "retried": res["run2"]["retried"]}, indent=1))
        return 0 if outcome == "done" else 1
    outcome = poll(res)
    res["outcome"] = outcome
    res["total_eecu_finished"] = finished_eecu(res)
    res["vs_prediction_44439"] = res["total_eecu_finished"] / PREDICTION
    if (args.calibrate or args.poll or args.start) and outcome in ("done", "failed") and (args.start or "extrapolation" not in res):
        res["extrapolation"] = extrapolate(res, chunk_land_share())
    save(res)
    summary = {"outcome": outcome, "finished_eecu": res["total_eecu_finished"],
               "failed_attempts_eecu": sum((v.get("final") or {}).get("batch_eecu_usage_seconds") or 0.0
                                           for v in res.get("failed_attempts", {}).values()),
               "task_eecu": {n: (v.get("final") or {}).get("batch_eecu_usage_seconds") for n, v in res["tasks"].items()}}
    if "model1_land_share_fit_total" in res.get("extrapolation", {}):
        e = res["extrapolation"]
        summary["extrapolated"] = {k: e[k] for k in ("model1_land_share_fit_total", "model2_mean_x40", "model3_max_x40")}
        summary["land_share_measured"] = e["land_share_measured"]
    print(json.dumps(summary, indent=1))
    return 0 if outcome == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
