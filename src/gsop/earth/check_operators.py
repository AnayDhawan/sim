"""`gsop check-operators` (issue #2): Earth Engine terrain operator against the numpy operator on one small window.

NOT RUN yet: needs an authenticated Earth Engine session (see gee_export.py). The numpy side is the same code every body
uses (gsop.operators). Both sides start from the same bilinear-resampled 25 m EPSG:6933 surface: the Earth Engine side
computes it, the numpy side downloads exactly that surface with computePixels. The result is a per-feature relative
difference; any feature above the threshold (10 percent) fails the check, and the threshold is not to be loosened.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import numpy as np

from .. import operators as O
from ..grid import Grid
from ..provenance import write_json
from . import gee_export as GX
from . import gee_operators as GO
from . import open_data as OD

FEATURES = ("slope_med", "relief", "rough_a")       # the issue's minimum; the others are reported too
ALL = ("slope_med", "slope_p90", "relief", "rough_a", "rough_b")
THRESHOLD = 0.10


def relative_difference(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    """Mean absolute difference over mean absolute numpy value, on tiles where both are finite."""
    ok = np.isfinite(a) & np.isfinite(b)
    if not ok.any():
        return {"n": 0, "rel_diff": float("nan"), "max_abs_diff": float("nan")}
    d = np.abs(a[ok] - b[ok])
    return {"n": int(ok.sum()), "rel_diff": float(d.mean() / max(np.abs(b[ok]).mean(), 1e-12)),
            "max_abs_diff": float(d.max())}


def run(center_lonlat: tuple[float, float] = (76.51, 19.98), n_tiles: int = 5, work_cell_m: float = 25.0,
        project: str | None = None, out: Path | str = "results/operator_check.json", op_cfg: dict[str, Any] | None = None
        ) -> dict[str, Any]:
    ee = GX.init(project)
    grid = Grid()
    from ..config import load_all
    op_cfg = op_cfg or load_all()["features"]["operator"]
    if (op_cfg["rough_a_baseline_m"] / work_cell_m) % 1 or (op_cfg["rough_b_baseline_m"] / work_cell_m) % 1:
        raise ValueError(f"work cell {work_cell_m} m does not divide the roughness baselines")
    ix, iy = grid.cell_of_lonlat(np.array([center_lonlat[0]]), np.array([center_lonlat[1]]))
    ix0, iy0 = int(ix[0]) - n_tiles // 2, int(iy[0]) - n_tiles // 2
    win = (ix0, iy0, ix0 + n_tiles, iy0 + n_tiles)
    base = float(op_cfg["slope_baseline_m"])
    layers = GX.load_layers()
    dem = GX.dem_image(ee, layers)

    # Earth Engine side: the five features on the 6 km tile grid
    img = GO.ee_tile_terrain(dem, grid, win, ee, work_cell_m, base,
                             (op_cfg["rough_a_baseline_m"], op_cfg["rough_b_baseline_m"]))
    ee_arr = ee.data.computePixels({
        "expression": img, "fileFormat": "NUMPY_NDARRAY",
        "grid": {"dimensions": {"width": n_tiles, "height": n_tiles}, "crsCode": grid.crs,
                 "affineTransform": {"scaleX": grid.cell_m, "shearX": 0, "translateX": grid.x0 + ix0 * grid.cell_m,
                                     "shearY": 0, "scaleY": -grid.cell_m, "translateY": grid.y_top - iy0 * grid.cell_m}}})
    # numpy side: the same working surface plus one slope-baseline cell of margin
    wdem = GO.ee_work_dem(dem, grid, win, ee, work_cell_m)
    m = int(round(base / work_cell_m))
    size = int(round(n_tiles * grid.cell_m / work_cell_m)) + 2 * m
    z_arr = ee.data.computePixels({
        "expression": wdem.select("elevation"), "fileFormat": "NUMPY_NDARRAY",
        "grid": {"dimensions": {"width": size, "height": size}, "crsCode": grid.crs,
                 "affineTransform": {"scaleX": work_cell_m, "shearX": 0, "translateX": grid.x0 + ix0 * grid.cell_m - base,
                                     "shearY": 0, "scaleY": -work_cell_m, "translateY": grid.y_top - iy0 * grid.cell_m + base}}})
    z = np.asarray(z_arr["elevation"], dtype=np.float64)
    kx = OD.ground_scale_rows(grid, iy0, iy0 + n_tiles, base)
    np_feats = O.tile_features(z, work_cell_m, grid.cell_m, grid.cell_m, base,
                               (op_cfg["rough_a_baseline_m"], op_cfg["rough_b_baseline_m"]), margin_m=base, kx_rows=kx)
    rows = {}
    for k in ALL:
        r = relative_difference(np.asarray(ee_arr[k], dtype=np.float64), np_feats[k])
        r["ok"] = bool(r["n"] > 0 and r["rel_diff"] <= THRESHOLD)
        rows[k] = r
    ok_all = all(rows[k]["ok"] for k in FEATURES)
    report = {"ok": ok_all, "threshold": THRESHOLD, "features": rows, "window_tiles": win, "center_lonlat": center_lonlat,
              "work_cell_m": work_cell_m, "dem": [layers["dem"]["primary"]["id"], layers["dem"]["fallback"]["id"]],
              "date": dt.date.today().isoformat(),
              "note": "mean abs difference over mean abs numpy value; checked features: " + ", ".join(FEATURES)}
    write_json(Path(out), report)
    return report
