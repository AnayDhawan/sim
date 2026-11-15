"""Chunks of the paused terrain queue that hold (almost) no gate-passing tiles, from downloaded gate GeoTIFFs.

    uv run python scripts/ee_terrain90_skip.py GATE_FOLDER [--min-pass 50] [--out skip_chunks.json]

Builds a global tile mask (grid rows x cols, 255 unknown, 0 fail, 1 pass; gates as in ee_gate_stats.py), then for every
paused SRTM or stage 2 task in results/ee_terrain90_state.json counts passing tiles inside its cells. A chunk is skipped only
when at least 90 percent of its tiles have known gate values and fewer than --min-pass pass. Chunks with unknown gate
values (gate file not downloaded yet) are always kept. Writes the skip list (JSON array of task names) and prints a summary.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from gsop.provenance import ROOT

X_LEFT = -17367530.445161372
Y_TOP = 7342230.136498678
CELL = 6000.0
NCOLS, NROWS = 5790, 2448
LAND_MIN, NDVI_MAX, WATER_MAX, BUILT_MAX = 0.5, 0.2, 0.5, 0.2


def build_mask(folder: Path) -> np.ndarray:
    import rasterio

    mask = np.full((NROWS, NCOLS), 255, dtype=np.uint8)
    n = 0
    for f in sorted(folder.rglob("*.tif")):
        with rasterio.open(f) as ds:
            data = ds.read().astype("float64")
            nodata = ds.nodata
            tr = ds.transform
        if nodata is not None and not np.isnan(nodata):
            data[data == nodata] = np.nan
        land, water, ndvi, built = data[0], data[1], data[2], data[3]
        finite = np.isfinite(land) & np.isfinite(water) & np.isfinite(ndvi) & np.isfinite(built)
        ok = finite & (land >= LAND_MIN) & (ndvi <= NDVI_MAX) & (water <= WATER_MAX) & (built <= BUILT_MAX)
        # 1 pass, 0 land that fails a gate, 2 no gate data in the file (ocean); 255 stays for cells no file covers
        val = np.where(finite, np.where(ok, 1, 0), 2).astype(np.uint8)
        c0 = int(round((tr.c - X_LEFT) / CELL))
        r0 = int(round((Y_TOP - tr.f) / CELL))
        h, w = val.shape
        if c0 < 0 or r0 < 0 or c0 + w > NCOLS or r0 + h > NROWS:
            raise ValueError(f"{f.name}: placement {c0},{r0},{w},{h} outside the grid")
        mask[r0:r0 + h, c0:c0 + w] = val
        n += 1
    print(f"placed {n} gate files; known cells {(mask != 255).sum()} of {mask.size}", flush=True)
    return mask


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--min-pass", type=int, default=50)
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "skip_chunks.json")
    a = ap.parse_args()
    mask = build_mask(a.folder)
    np.save(a.out.with_suffix(".mask.npy"), mask)
    st = json.loads((ROOT / "results" / "ee_terrain90_state.json").read_text())
    skip, keep_unknown, keep_pass = [], [], []
    surv_tot = 0
    for name, t in st["tasks"].items():
        if not t.get("paused"):
            continue
        x0, y0, w, h = t["cells"]
        sub = mask[y0:y0 + h, x0:x0 + w]
        known = (sub != 255).mean()
        npass = int((sub == 1).sum())
        surv_tot += npass
        if known < 0.9:
            keep_unknown.append(name)
        elif npass < a.min_pass:
            skip.append(name)
        else:
            keep_pass.append(name)
    a.out.write_text(json.dumps(skip, indent=1))
    a.out.with_name("first_chunks.json").write_text(json.dumps(keep_pass, indent=1))
    print(f"paused tasks: skip {len(skip)}, keep (survivors) {len(keep_pass)}, keep (gate unknown) {len(keep_unknown)}; "
          f"known survivors inside paused chunks {surv_tot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
