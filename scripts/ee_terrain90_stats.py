"""Statistics of a downloaded folder of 90 m terrain GeoTIFFs (Drive folder gsop_terrain90, scripts/ee_terrain90_export.py).

    uv run python scripts/ee_terrain90_stats.py PATH_TO_FOLDER [--ref PROBE_C.tif ...] [--json OUT.json]

Per file: grid cells of the chunk, bands, share of invalid cells (NaN, the nodata tag, or -9999 = masked terrain). Total
over all files. With --ref (Probe C GeoTIFFs of the Lonar box, same six bands, any file with the same cell grid) it
compares slope_med cell by cell at the global cells both files cover and prints the median absolute difference.
Band order: slope_med, slope_p90, relief, elev_mean, rough_a, rough_b (band descriptions are used when present).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from gsop.grid import Grid

BANDS = ["slope_med", "slope_p90", "relief", "elev_mean", "rough_a", "rough_b"]
NODATA = -9999.0


def read(path: Path, g: Grid | None = None) -> dict:
    """Bands as float arrays with invalid cells set to NaN, plus the global cell of the top-left pixel."""
    import rasterio

    g = g or Grid()
    with rasterio.open(path) as ds:
        data = ds.read().astype("float64")
        nodata, tf, desc = ds.nodata, ds.transform, list(ds.descriptions)
    if data.shape[0] != len(BANDS):
        raise ValueError(f"{path.name}: expected {len(BANDS)} bands, found {data.shape[0]}")
    data[data == NODATA] = np.nan
    if nodata is not None and not np.isnan(nodata):
        data[data == nodata] = np.nan
    names = desc if set(desc) == set(BANDS) else BANDS
    ix0 = int(round((tf.c - g.x0) / g.cell_m))
    iy0 = int(round((g.y_top - tf.f) / g.cell_m))
    return {"bands": dict(zip(names, data)), "ix0": ix0, "iy0": iy0, "shape": data.shape[1:]}


def file_stats(path: Path) -> dict:
    r = read(path)
    h, w = r["shape"]
    invalid = {b: float(np.isnan(a).mean()) for b, a in r["bands"].items()}
    return {"file": path.name, "ix0": r["ix0"], "iy0": r["iy0"], "w": w, "h": h, "bands": list(r["bands"]),
            "nan_share": invalid, "all_nan_cells": int(np.isnan(np.stack(list(r["bands"].values()))).all(axis=0).sum()),
            "cells": w * h}


def compare_ref(folder_files: list[Path], refs: list[Path]) -> dict:
    """slope_med of the reference tiles against the same global cells in the export folder."""
    exp = [read(f) for f in folder_files]
    diffs, n_ref = [], 0
    for ref in refs:
        r = read(ref)
        rs = r["bands"]["slope_med"]
        n_ref += int(np.isfinite(rs).sum())
        for e in exp:
            es = e["bands"]["slope_med"]
            h, w = rs.shape
            for j in range(h):
                for i in range(w):
                    x, y = r["ix0"] + i - e["ix0"], r["iy0"] + j - e["iy0"]
                    if 0 <= y < es.shape[0] and 0 <= x < es.shape[1] and np.isfinite(rs[j, i]) and np.isfinite(es[y, x]):
                        diffs.append(abs(rs[j, i] - es[y, x]))
    return {"ref_cells": n_ref, "compared": len(diffs),
            "median_abs_diff_slope_med_deg": float(np.median(diffs)) if diffs else None,
            "max_abs_diff_slope_med_deg": float(np.max(diffs)) if diffs else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--ref", type=Path, nargs="*", default=[])
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    files = sorted(args.folder.glob("*.tif"))
    if not files:
        print(f"no .tif files in {args.folder}", file=sys.stderr)
        return 2
    rows = [file_stats(f) for f in files]
    for r in rows:
        nan = " ".join(f"{b}={v:.3f}" for b, v in r["nan_share"].items())
        print(f"{r['file']}: cells {r['cells']} ({r['w']}x{r['h']}) at {r['ix0']},{r['iy0']} bands {len(r['bands'])} nan {nan}")
    cells = sum(r["cells"] for r in rows)
    valid = sum(r["cells"] * (1 - r["nan_share"]["slope_med"]) for r in rows)
    out = {"files": rows, "total_cells": cells, "slope_med_valid_cells": int(round(valid)),
           "slope_med_nan_share": 1 - valid / cells}
    print(f"TOTAL: files {len(rows)} cells {cells} slope_med valid {out['slope_med_valid_cells']} nan share {out['slope_med_nan_share']:.3f}")
    if args.ref:
        out["ref"] = compare_ref(files, args.ref)
        print("REF:", json.dumps(out["ref"]))
    if args.json:
        args.json.write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
