"""Gate statistics from a folder of downloaded gate GeoTIFFs (output of scripts/ee_gate_export.py, Drive folder gsop_gate).

    uv run python scripts/ee_gate_stats.py PATH_TO_FOLDER [--json OUT.json]

Each GeoTIFF has the four bands land_frac, water_ice_frac, ndvi_median, built_crop_frac (in that order; band descriptions
are used when present). Prints, per file and in total: cells, land tiles (land_frac >= 0.5), passing tiles (land and
ndvi_median <= 0.2 and water_ice_frac <= 0.5 and built_crop_frac <= 0.2, all four bands finite) and p = passing / land.
Cells where any gate band is nodata count as neither land nor passing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

BANDS = ["land_frac", "water_ice_frac", "ndvi_median", "built_crop_frac"]
LAND_MIN, NDVI_MAX, WATER_MAX, BUILT_MAX = 0.5, 0.2, 0.5, 0.2


def read_bands(path: Path) -> dict[str, np.ndarray]:
    import rasterio

    with rasterio.open(path) as ds:
        data = ds.read().astype("float64")
        nodata = ds.nodata
        desc = list(ds.descriptions)
    if data.shape[0] != len(BANDS):
        raise ValueError(f"{path.name}: expected {len(BANDS)} bands, found {data.shape[0]}")
    if nodata is not None and not np.isnan(nodata):
        data[data == nodata] = np.nan
    names = desc if set(desc) == set(BANDS) else BANDS
    return {n: data[i] for i, n in enumerate(names)}


def file_stats(path: Path) -> dict:
    b = read_bands(path)
    finite = np.ones(b["land_frac"].shape, bool)
    for n in BANDS:
        finite &= np.isfinite(b[n])
    land = finite & (b["land_frac"] >= LAND_MIN)
    ok = land & (b["ndvi_median"] <= NDVI_MAX) & (b["water_ice_frac"] <= WATER_MAX) & (b["built_crop_frac"] <= BUILT_MAX)
    return {"file": path.name, "cells": int(finite.size), "finite_cells": int(finite.sum()),
            "land_tiles": int(land.sum()), "pass_tiles": int(ok.sum())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    files = sorted(args.folder.glob("*.tif"))
    if not files:
        print(f"no .tif files in {args.folder}", file=sys.stderr)
        return 2
    rows = [file_stats(f) for f in files]
    tot = {k: sum(r[k] for r in rows) for k in ("cells", "finite_cells", "land_tiles", "pass_tiles")}
    tot["p"] = tot["pass_tiles"] / tot["land_tiles"] if tot["land_tiles"] else None
    for r in rows:
        print(f"{r['file']}: cells {r['cells']} finite {r['finite_cells']} land {r['land_tiles']} pass {r['pass_tiles']}")
    print(f"TOTAL: files {len(rows)} cells {tot['cells']} land_tiles {tot['land_tiles']} pass_tiles {tot['pass_tiles']} p {tot['p']}")
    if args.json:
        args.json.write_text(json.dumps({"files": rows, "total": tot}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
