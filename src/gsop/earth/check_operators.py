"""`gsop check-operators` (issue #2): Earth Engine terrain operator against the numpy operator on one small window.

NOT RUN yet: needs an authenticated Earth Engine session (see gee_export.py). The numpy side is the same code every body
uses (gsop.operators). Both sides start from the same bilinear-resampled 25 m EPSG:6933 surface: the Earth Engine side
computes it, the numpy side downloads exactly that surface with computePixels. The result is a per-feature relative
difference; any checked feature above the configured threshold fails the check.
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
# threshold, work cell, window size and centre live in config/run.yaml `operator_check`; the threshold is not to be loosened.


def relative_difference(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    """Mean absolute difference over mean absolute numpy value, on tiles where both are finite."""
    ok = np.isfinite(a) & np.isfinite(b)
    if not ok.any():
        return {"n": 0, "rel_diff": float("nan"), "max_abs_diff": float("nan")}
    d = np.abs(a[ok] - b[ok])
    return {"n": int(ok.sum()), "rel_diff": float(d.mean() / max(np.abs(b[ok]).mean(), 1e-12)),
            "max_abs_diff": float(d.max())}


def run(center_lonlat: tuple[float, float] | None = None, n_tiles: int | None = None,
        project: str | None = None, out: Path | str = "results/operator_check.json", cfg: dict[str, Any] | None = None
        ) -> dict[str, Any]:
    """Window, threshold: config/run.yaml `operator_check`. Working grid: config/features.yaml `operator.work_cell_m`, the same
    setting the production export reads (it is deliberately not a parameter here, so the check cannot test a different grid).
    Earth Engine errors (`ee.EEException`, which is not a RuntimeError) are re-raised as RuntimeError so the CLI prints [FAIL]."""
    from ..config import load_all
    cfg = cfg or load_all()
    chk = cfg["run"]["operator_check"]
    center_lonlat = tuple(center_lonlat or chk["center_lonlat"])
    n_tiles = int(n_tiles or chk["n_tiles"])
    op_cfg = cfg["features"]["operator"]
    work_cell_m = float(op_cfg["work_cell_m"])
    threshold = float(chk["threshold"])
    ee = GX.init(project)
    grid = Grid()
    if (op_cfg["rough_a_baseline_m"] / work_cell_m) % 1 or (op_cfg["rough_b_baseline_m"] / work_cell_m) % 1:
        raise ValueError(f"work cell {work_cell_m} m does not divide the roughness baselines")
    ix, iy = grid.cell_of_lonlat(np.array([center_lonlat[0]]), np.array([center_lonlat[1]]))
    ix0, iy0 = int(ix[0]) - n_tiles // 2, int(iy[0]) - n_tiles // 2
    win = (ix0, iy0, ix0 + n_tiles, iy0 + n_tiles)
    base = float(op_cfg["slope_baseline_m"])
    layers = GX.load_layers()
    dem = GX.dem_image(ee, layers)

    try:
        # Earth Engine side: the five features on the 6 km tile grid
        img = GO.ee_tile_terrain(dem, grid, win, ee, work_cell_m, base,
                                 (op_cfg["rough_a_baseline_m"], op_cfg["rough_b_baseline_m"]))
        ee_arr = ee.data.computePixels({
            "expression": img, "fileFormat": "NUMPY_NDARRAY",
            "grid": {"dimensions": {"width": n_tiles, "height": n_tiles}, "crsWkt": GO.ee_crs(),
                     "affineTransform": {"scaleX": grid.cell_m, "shearX": 0, "translateX": grid.x0 + ix0 * grid.cell_m,
                                         "shearY": 0, "scaleY": -grid.cell_m, "translateY": grid.y_top - iy0 * grid.cell_m}}})
        # numpy side: the same working surface plus one slope-baseline cell of margin
        wdem = GO.ee_work_dem(dem, grid, win, ee, work_cell_m)
        m = int(round(base / work_cell_m))
        size = int(round(n_tiles * grid.cell_m / work_cell_m)) + 2 * m
        z_arr = ee.data.computePixels({
            "expression": wdem.select("elevation"), "fileFormat": "NUMPY_NDARRAY",
            "grid": {"dimensions": {"width": size, "height": size}, "crsWkt": GO.ee_crs(),
                     "affineTransform": {"scaleX": work_cell_m, "shearX": 0, "translateX": grid.x0 + ix0 * grid.cell_m - base,
                                         "shearY": 0, "scaleY": -work_cell_m, "translateY": grid.y_top - iy0 * grid.cell_m + base}}})
    except ee.EEException as e:
        raise RuntimeError(f"Earth Engine rejected the request: {e}") from e
    z = np.asarray(z_arr["elevation"], dtype=np.float64)
    kx = OD.ground_scale_rows(grid, iy0, iy0 + n_tiles, base)
    np_feats = O.tile_features(z, work_cell_m, grid.cell_m, grid.cell_m, base,
                               (op_cfg["rough_a_baseline_m"], op_cfg["rough_b_baseline_m"]), margin_m=base, kx_rows=kx)
    rows = {}
    for k in ALL:
        r = relative_difference(np.asarray(ee_arr[k], dtype=np.float64), np_feats[k])
        r["ok"] = bool(r["n"] > 0 and r["rel_diff"] <= threshold)
        rows[k] = r
    ok_all = all(rows[k]["ok"] for k in FEATURES)
    report = {"ok": ok_all, "threshold": threshold, "features": rows, "window_tiles": win, "center_lonlat": center_lonlat,
              "work_cell_m": work_cell_m, "dem": [layers["dem"]["primary"]["id"], layers["dem"]["fallback"]["id"]],
              "date": dt.date.today().isoformat(),
              "note": "mean abs difference over mean abs numpy value; checked features: " + ", ".join(FEATURES)}
    write_json(Path(out), report)
    return report
