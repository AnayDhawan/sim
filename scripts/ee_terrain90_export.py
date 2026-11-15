"""Global 90 m terrain export (Probe C configuration) plus high-latitude GLO30 stages, with a safety monitor.

    uv run python scripts/ee_terrain90_export.py plan            # offline: chunk lists, no Earth Engine call
    uv run python scripts/ee_terrain90_export.py start           # backs up the old state, submits ALL tasks up front, exits
    uv run python scripts/ee_terrain90_export.py poll            # resume polling the recorded tasks

SRTM band: terrain_bands(100.0, "srtm90", (3, 10)) into Drive folder gsop_terrain90 (CGIAR/SRTM90_V4, 100 m working grid,
slope baseline 500 m, roughness windows 300 m and 1000 m). SRTM90 covers about 56S to 60N. Chunk size is adaptive
(gee_export.adaptive_chunks): the source footprint of a task in the 3 arc second lattice must stay under about 2^26 pixels
or Earth Engine fails it with "Reprojection output too large", which gives about 9,600 x cos(lat) tiles per chunk. Chunks
without any SRTM data (open ocean) are skipped, decided by one coarse interactive reduction.

High latitudes, Drive folder gsop_terrain90_hi, same operator on Copernicus GLO30 averaged to the 100 m grid:
  stage1: four validation boxes (haughton, samoylov, mcmurdo_dry_valleys, askja) of 100 x 100 cells, in adaptive chunks
  stage2: land from 60N to 83N outside Greenland (USDOS/LSIB_SIMPLE/2017 country polygon, Iceland stays), adaptive chunks.
          Stage 2 may stay unfinished at the cutoff; only finished chunks are used.
Task descriptions: terrain90_r<band>_c<col>, terrain90_stage1_<site>_r<band>_c<col>, terrain90_stage2_r<band>_c<col>,
terrain90_test_<name> (four size tests, never retried).

Safety, checked every poll (90 s), per stage: stop the stage and cancel its queued tasks when the summed
batch_eecu_usage_seconds of its finished tasks passes the stage cap (srtm 130,000; stage1 15,000; stage2 60,000), or
when more than 20 percent of its chunks have failed after their one retry. A failed chunk is retried once; an error with
"too large" or "memory" splits it in two along the longer side. Running tasks are never cancelled.
State: results/ee_terrain90_state.json (gitignored).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings

warnings.filterwarnings("ignore")

from gsop.earth import gee_export as GE  # noqa: E402
from gsop.provenance import ROOT  # noqa: E402

STATE = ROOT / "results" / "ee_terrain90_state.json"
POLL_S = 90
CAP_S = 30 * 3600
CAPS = {"srtm": 130_000.0, "stage1": 15_000.0, "stage2": 60_000.0, "test": 3_000.0}
FAIL_SHARE = 0.20
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "CANCEL_REQUESTED"}
# two calibration chunks go first in the SRTM queue: a flat all-land chunk (Sahara) and a mountain chunk (Himalaya)
CALIBRATION = {"flat_sahara": (10.0, 25.0), "mountain_himalaya": (85.0, 30.0)}
GREENLAND = "Greenland"
HI_MIN_SHARE = 0.015    # a stage 2 chunk with less data outside Greenland is polygon-edge noise (0.5 and 1.0 percent measured)


def chunk_of(lon: float, lat: float, chunks: list[dict]) -> dict:
    g = GE.Grid()
    ix, iy = (int(v) for v in g.cell_of_lonlat(lon, lat))
    for c in chunks:
        x0, y0, w, h = c["cells"]
        if x0 <= ix < x0 + w and y0 <= iy < y0 + h:
            return c
    raise ValueError("point outside the planned chunks")


def _reduce_share(chunks: list[dict], img) -> dict[str, float]:
    import ee

    feats = []
    for c in chunks:
        geom, _ = GE.chunk_region(*c["cells"])
        feats.append(ee.Feature(geom, {"name": c["name"]}))
    out = img.reduceRegions(collection=ee.FeatureCollection(feats), reducer=ee.Reducer.mean(), scale=5000,
                            crs=GE.CRS_WKT).getInfo()
    return {f["properties"]["name"]: float(f["properties"].get("mean") or 0.0) for f in out["features"]}


def land_check(chunks: list[dict]) -> dict[str, float]:
    """Share of SRTM90 data pixels per chunk from one coarse reduction (scale 5 km). Interactive, not a batch task."""
    import ee

    return _reduce_share(chunks, ee.Image(GE.DEM90_ID).select("elevation").mask().unmask(0).toFloat())


def hi_land_check(chunks: list[dict]) -> dict[str, float]:
    """Share of GLO30 data pixels outside the Greenland country polygon per chunk (scale 5 km, interactive)."""
    import ee

    gl = ee.FeatureCollection("USDOS/LSIB_SIMPLE/2017").filter(ee.Filter.eq("country_na", GREENLAND))
    outside = ee.Image(0).paint(gl, 1).Not()
    data = ee.ImageCollection(GE.IDS["cop30"]).select("DEM").mosaic().mask().unmask(0)
    return _reduce_share(chunks, data.multiply(outside).toFloat())


def save(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1))


def submit(img, st: dict, name: str, cells: list[int], attempt: int, stage: str, parent: str | None = None) -> None:
    folder = GE.TERRAIN90_FOLDER if stage == "srtm" else GE.TERRAIN90_HI_FOLDER
    tid = GE.start_terrain90_task(img, name, cells, folder)
    st["tasks"][name] = {"id": tid, "cells": cells, "attempt": attempt, "parent": parent, "state": "SUBMITTED",
                         "eecu": None, "stage": stage}
    print(f"submitted {name} {tid} attempt {attempt} stage {stage}", flush=True)


def split(cells: list[int]) -> list[list[int]]:
    x0, y0, w, h = cells
    if w >= h:
        a = w // 2
        return [[x0, y0, a, h], [x0 + a, y0, w - a, h]]
    a = h // 2
    return [[x0, y0, w, a], [x0, y0 + a, w, h - a]]


TESTS = [("lat0_n110", 0.0, 110), ("lat0_n130", 0.0, 130), ("lat55_n90", 55.0, 90), ("lat55_n100", 55.0, 100)]


def start() -> dict:
    """Fresh run (the old state file is backed up). Order: two calibration chunks, size tests (4 tasks, stage test),
    stage 1 pieces, the rest of the SRTM band, stage 2. Everything is submitted up front."""
    GE.init()
    if STATE.exists():
        STATE.replace(STATE.with_name(f"ee_terrain90_state_stale_{int(time.time())}.json"))
    chunks = GE.terrain90_chunks()
    share = land_check(chunks)
    keep = [c for c in chunks if share[c["name"]] > 0.0]
    cal = {k: chunk_of(*v, keep)["name"] for k, v in CALIBRATION.items()}
    rest = [c for c in keep if c["name"] not in cal.values()]
    st = {"folder": GE.TERRAIN90_FOLDER, "started_unix": time.time(), "calibration": cal, "tasks": {},
          "planned_chunks": len(chunks), "skipped_ocean": [c["name"] for c in chunks if share[c["name"]] <= 0.0],
          "data_share": share, "stopped_stages": {}}
    img = GE.terrain90_image()
    for c in [c for c in keep if c["name"] in cal.values()]:
        submit(img, st, c["name"], c["cells"], 1, "srtm")
        save(st)
    g = GE.Grid()
    for name, lat, n in TESTS:
        ix, iy = (int(v) for v in g.cell_of_lonlat(20.0, lat))
        submit(img, st, f"terrain90_test_{name}", [ix, iy, n, n], 2, "test")   # attempt 2: never retried
        save(st)
    himg = GE.terrain_glo30_image()
    for b in GE.stage1_boxes():
        submit(himg, st, b["name"], b["cells"], 1, "stage1")
        save(st)
    for c in rest:
        submit(img, st, c["name"], c["cells"], 1, "srtm")
        save(st)
    chunks2 = GE.stage2_chunks()
    share2 = hi_land_check(chunks2)
    keep2 = [c for c in chunks2 if share2[c["name"]] > HI_MIN_SHARE]
    st["stage2_plan"] = {"planned": len(chunks2), "kept": len(keep2),
                         "skipped": [c["name"] for c in chunks2 if share2[c["name"]] <= HI_MIN_SHARE], "data_share": share2}
    for c in keep2:
        submit(himg, st, c["name"], c["cells"], 1, "stage2")
        save(st)
    n = {}
    for t in st["tasks"].values():
        n[t["stage"]] = n.get(t["stage"], 0) + 1
    print(f"submitted {n}, srtm ocean chunks skipped {len(st['skipped_ocean'])}", flush=True)
    return st


def stage_eecu(st: dict, stage: str) -> float:
    return sum((t.get("eecu") or 0.0) for t in st["tasks"].values()
               if t["state"] == "COMPLETED" and t.get("stage", "srtm") == stage)


def stop_stage(st: dict, stage: str, why: str) -> None:
    import ee

    st.setdefault("stopped_stages", {})[stage] = why
    for t in st["tasks"].values():
        if t.get("stage", "srtm") == stage and t["state"] in ("READY", "SUBMITTED"):
            try:
                ee.data.cancelTask(t["id"])
                t["state"] = "CANCEL_REQUESTED"
            except Exception as e:  # noqa: BLE001
                t["cancel_error"] = str(e)[:200]
    print(f"STOP {stage}: {why}", flush=True)


def refresh(st: dict) -> None:
    """Update every non-final task from one task-list call (plus single status calls for ids it does not list)."""
    import ee

    listed = {t["id"]: t for t in ee.data.getTaskList()}
    for t in st["tasks"].values():
        if t["state"] in ("COMPLETED", "CANCELLED", "CANCEL_REQUESTED") or t.get("retried") or \
                (t["state"] == "FAILED" and t["attempt"] == 2):
            continue
        s = listed.get(t["id"]) or ee.data.getTaskStatus(t["id"])[0]
        t.update(state=s["state"], eecu=s.get("batch_eecu_usage_seconds"), error=s.get("error_message"),
                 created_ms=s.get("creation_timestamp_ms"), start_ms=s.get("start_timestamp_ms"),
                 update_ms=s.get("update_timestamp_ms"))


def poll(st: dict) -> None:
    GE.init()
    imgs: dict[str, object] = {}
    t0 = time.time()
    stopped = st.setdefault("stopped_stages", {})
    while time.time() - t0 < CAP_S:
        refresh(st)
        for name, t in list(st["tasks"].items()):
            stage = t.get("stage", "srtm")
            if t["state"] == "FAILED" and t["attempt"] == 1 and not t.get("retried") and stage not in stopped:
                t["retried"] = True
                if stage not in imgs:
                    imgs[stage] = GE.terrain90_image() if stage in ("srtm", "test") else GE.terrain_glo30_image()
                err = (t.get("error") or "").lower()
                parts = split(t["cells"]) if ("too large" in err or "memory" in err) else [t["cells"]]
                for i, cells in enumerate(parts):
                    submit(imgs[stage], st, f"{name}_r{i}", cells, 2, stage, parent=name)
        states: dict[str, dict[str, int]] = {}
        for t in st["tasks"].values():
            d = states.setdefault(t.get("stage", "srtm"), {})
            d[t["state"]] = d.get(t["state"], 0) + 1
        print(f"{time.strftime('%H:%M:%S')} {states} eecu={ {s: round(stage_eecu(st, s)) for s in CAPS} }", flush=True)
        for stage, cap in CAPS.items():
            if stage in stopped:
                continue
            tasks = [t for t in st["tasks"].values() if t.get("stage", "srtm") == stage]
            n1 = sum(1 for t in tasks if t["attempt"] == 1)
            bad = sum(1 for t in tasks if t["attempt"] == 2 and t["state"] == "FAILED")
            if stage_eecu(st, stage) > cap:
                stop_stage(st, stage, f"finished EECU-s {stage_eecu(st, stage):.0f} above {cap:.0f}")
            elif n1 and bad / n1 > FAIL_SHARE:
                stop_stage(st, stage, "more than 20 percent of chunks failed after retry")
        save(st)
        if all(t["state"] in TERMINAL and not (t["state"] == "FAILED" and t["attempt"] == 1 and not t.get("retried"))
               for t in st["tasks"].values()):
            break
        time.sleep(POLL_S)
    save(st)


def reorder(dry: bool) -> None:
    """Put stage 1 and the calibration chunks ahead of the rest of the SRTM band in the FIFO queue.

    Cancels READY SRTM (non-calibration) and stage 2 tasks, then resubmits them in that order, so the queue becomes
    calibration, stage 1, SRTM band, stage 2. Tasks that already started are left alone. Needs no poller running.
    """
    import ee

    GE.init()
    st = json.loads(STATE.read_text())
    refresh(st)
    cal = set(st["calibration"].values())
    move = [n for n, t in st["tasks"].items()
            if t["state"] == "READY" and t["attempt"] == 1
            and ((t.get("stage", "srtm") == "srtm" and n not in cal) or t.get("stage") == "stage2")]
    n_srtm = sum(1 for n in move if st["tasks"][n].get("stage", "srtm") == "srtm")
    print(f"to move: {len(move)} (srtm {n_srtm}, stage2 {len(move) - n_srtm}); calibration kept: {sorted(cal)}", flush=True)
    if dry:
        return
    for n in move:
        ee.data.cancelTask(st["tasks"][n]["id"])
    time.sleep(45)
    refresh(st)
    ready_again = [n for n in move if st["tasks"][n]["state"] not in ("CANCELLED", "CANCEL_REQUESTED")]
    print(f"not cancelled (already running or finished, left as is): {len(ready_again)}", flush=True)
    todo = [n for n in move if n not in ready_again]
    old = {n: dict(st["tasks"][n]) for n in todo}
    img_srtm, img_hi = GE.terrain90_image(), GE.terrain_glo30_image()
    for n in todo:
        stage = old[n].get("stage", "srtm")
        submit(img_srtm if stage == "srtm" else img_hi, st, n, old[n]["cells"], 1, stage)
        save(st)
    print(f"resubmitted {len(todo)} tasks", flush=True)


def resubmit() -> None:
    """After a code fix: cancel every READY task and every FAILED first attempt, then resubmit them in their original
    order with the current graph. Tasks that are RUNNING or COMPLETED are left alone. Needs no poller running."""
    import ee

    GE.init()
    st = json.loads(STATE.read_text())
    refresh(st)
    todo = [n for n, t in st["tasks"].items()
            if (t["state"] == "READY" or (t["state"] == "FAILED" and t["attempt"] == 1 and not t.get("retried")))
            and not t.get("parent")]
    for n in todo:
        if st["tasks"][n]["state"] == "READY":
            ee.data.cancelTask(st["tasks"][n]["id"])
    time.sleep(60)
    refresh(st)
    ready_again = [n for n in todo if st["tasks"][n]["state"] not in ("CANCELLED", "CANCEL_REQUESTED", "FAILED")]
    print(f"to resubmit {len(todo)}, not cancelled (started meanwhile, left alone) {len(ready_again)}", flush=True)
    old = {n: dict(st["tasks"][n]) for n in todo if n not in ready_again}
    imgs = {"srtm": GE.terrain90_image(), "test": GE.terrain90_image()}
    himg = GE.terrain_glo30_image()
    for n, o in old.items():
        submit(imgs.get(o["stage"], himg), st, n, o["cells"], o["attempt"], o["stage"])
        save(st)
    print(f"resubmitted {len(old)}", flush=True)


def pause() -> None:
    """Cancel every READY SRTM and stage 2 task (first attempts) and mark it paused, so the gate export can use the two
    Earth Engine slots. RUNNING and COMPLETED tasks are left alone. Stop the poller first. `resume` brings them back."""
    import ee

    GE.init()
    st = json.loads(STATE.read_text())
    refresh(st)
    n = 0
    for name, t in st["tasks"].items():
        if t["state"] == "READY" and t["attempt"] == 1 and t.get("stage", "srtm") in ("srtm", "stage2"):
            ee.data.cancelTask(t["id"])
            t["paused"] = True
            t["state"] = "CANCEL_REQUESTED"
            n += 1
    save(st)
    print(f"paused {n} tasks", flush=True)


def resume(skip_file: str | None, first_file: str | None = None) -> None:
    """Resubmit the paused tasks except chunk names listed in the JSON file `skip_file`. Order: SRTM chunks named in
    `first_file` (chunks known to hold gate-passing tiles), then the other SRTM chunks, then stage 2 (original order inside
    each group)."""
    GE.init()
    st = json.loads(STATE.read_text())
    refresh(st)
    skip = set(json.loads(open(skip_file).read())) if skip_file else set()
    first = set(json.loads(open(first_file).read())) if first_file else set()
    todo = [(n, dict(t)) for n, t in st["tasks"].items() if t.get("paused")]
    todo.sort(key=lambda it: (0 if (it[1].get("stage", "srtm") == "srtm" and it[0] in first)
                              else (1 if it[1].get("stage", "srtm") == "srtm" else 2)))
    img, himg = GE.terrain90_image(), GE.terrain_glo30_image()
    sent = dropped = 0
    for n, o in todo:
        if n in skip:
            st["tasks"][n]["paused"] = False
            st["tasks"][n]["state"] = "CANCELLED"
            st["tasks"][n]["skipped"] = True
            dropped += 1
            continue
        submit(img if o.get("stage", "srtm") == "srtm" else himg, st, n, o["cells"], 1, o.get("stage", "srtm"))
        sent += 1
        save(st)
    save(st)
    print(f"resubmitted {sent}, left cancelled {dropped}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "start", "poll", "reorder", "resubmit", "pause", "resume"])
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--skip", default=None)
    ap.add_argument("--first", default=None)
    a = ap.parse_args()
    if a.cmd == "pause":
        pause()
        return 0
    if a.cmd == "resume":
        resume(a.skip, a.first)
        return 0
    if a.cmd == "resubmit":
        resubmit()
        return 0
    if a.cmd == "reorder":
        reorder(a.dry)
        return 0
    if a.cmd == "plan":
        ch = GE.terrain90_chunks()
        r0, r1 = GE.terrain90_row_range()
        print(f"srtm band rows {r0}..{r1}, chunks {len(ch)}, tiles per chunk {min(c['cells'][2] * c['cells'][3] for c in ch)} to {max(c['cells'][2] * c['cells'][3] for c in ch)}")
        s1, s2 = GE.stage1_boxes(), GE.stage2_chunks()
        print(f"stage1 pieces {len(s1)}")
        print(f"stage2 chunks {len(s2)}, max tiles per chunk {max(c['cells'][2] * c['cells'][3] for c in s2)}, "
              f"rows {s2[0]['cells'][1]}..{s2[-1]['cells'][1] + s2[-1]['cells'][3]}")
        return 0
    if a.cmd == "start":
        start()             # submits and saves; run the poll command (detached) afterwards
        return 0
    poll(json.loads(STATE.read_text()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
