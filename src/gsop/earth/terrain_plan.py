"""Terrain export on survivors: plan generation, no Earth Engine calls.

Input: the gate GeoTIFFs of a gate export (Drive folder gsop_gate, four bands land_frac, water_ice_frac, ndvi_median,
built_crop_frac, same conventions as scripts/ee_gate_stats.py). Output: a list of rectangular task regions in 6 km grid
cells [ix0, iy0, w, h] that cover every surviving tile, so the terrain operator can be exported per region instead of
for the whole grid (see docs/EE_COST.md, "Terrain on survivors and cheap climate bands").

Steps: survivors -> blocks of BLOCK x BLOCK cells (10 cells = 60 km) holding at least one survivor -> rectangles by
merging neighbouring blocks (zero waste first, then cheapest extra empty area) until at most MAX_REGIONS remain.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..grid import Grid

BANDS = ["land_frac", "water_ice_frac", "ndvi_median", "built_crop_frac"]
LAND_MIN, NDVI_MAX, WATER_MAX, BUILT_MAX = 0.5, 0.2, 0.5, 0.2
BLOCK = 10          # cells per block side: 60 km
MAX_REGIONS = 150
MAX_SIDE = 60       # cells: longest side of a merged region (360 km), keeps one task's raster and reprojection bounded


def survivor_cells(folder: Path | str, g: Grid | None = None) -> np.ndarray:
    """Global (ix, iy) of every surviving tile, shape (n, 2), from all *.tif in `folder`. A tile survives when all four
    gate bands are finite, land_frac >= 0.5 and the three gates pass (the rule of scripts/ee_gate_stats.py)."""
    import rasterio

    g = g or Grid()
    out = []
    files = sorted(Path(folder).glob("*.tif"))
    if not files:
        raise FileNotFoundError(f"no .tif files in {folder}")
    for f in files:
        with rasterio.open(f) as ds:
            data = ds.read().astype("float64")
            nodata, tf, desc = ds.nodata, ds.transform, list(ds.descriptions)
        if data.shape[0] != len(BANDS):
            raise ValueError(f"{f.name}: expected {len(BANDS)} bands, found {data.shape[0]}")
        if nodata is not None and not np.isnan(nodata):
            data[data == nodata] = np.nan
        b = dict(zip(desc if set(desc) == set(BANDS) else BANDS, data))
        ok = np.ones(data.shape[1:], bool)
        for n in BANDS:
            ok &= np.isfinite(b[n])
        ok &= (b["land_frac"] >= LAND_MIN) & (b["ndvi_median"] <= NDVI_MAX)
        ok &= (b["water_ice_frac"] <= WATER_MAX) & (b["built_crop_frac"] <= BUILT_MAX)
        rows, cols = np.nonzero(ok)
        ix = np.rint((tf.c - g.x0) / g.cell_m).astype(np.int64) + cols
        iy = np.rint((g.y_top - tf.f) / g.cell_m).astype(np.int64) + rows
        out.append(np.stack([ix, iy], axis=1))
    return np.unique(np.concatenate(out), axis=0) if out else np.zeros((0, 2), np.int64)


def blocks_of(cells: np.ndarray, block: int = BLOCK) -> np.ndarray:
    """Unique occupied blocks (bx, by) for survivor cells."""
    if len(cells) == 0:
        return np.zeros((0, 2), np.int64)
    return np.unique(cells // block, axis=0)


def _runs_and_stack(rects: list[list[int]]) -> list[list[int]]:
    """Zero-waste merge of rectangles [x0, y0, x1, y1] (exclusive ends): join horizontal neighbours with the same y span,
    then vertical neighbours with the same x span, until nothing changes."""
    changed = True
    while changed:
        changed = False
        for axis in (0, 1):
            o = 1 - axis
            rects.sort(key=lambda r: (r[o], r[o + 2], r[axis]))
            merged: list[list[int]] = []
            for r in rects:
                m = merged[-1] if merged else None
                if m and m[o] == r[o] and m[o + 2] == r[o + 2] and m[axis + 2] == r[axis]:
                    m[axis + 2] = r[axis + 2]
                    changed = True
                else:
                    merged.append(list(r))
            rects = merged
    return rects


def _area(r: list[int]) -> int:
    return (r[2] - r[0]) * (r[3] - r[1])


def merge_rects(rects: list[list[int]], max_regions: int = MAX_REGIONS, max_side: int = MAX_SIDE) -> list[list[int]]:
    """Reduce to at most max_regions rectangles by merging the pairs whose union bounding box adds the least empty area.
    Candidate pairs come from the 8 nearest centres; each round merges the cheapest disjoint pairs. Merged sides are
    limited to max_side cells; when no pair may merge under that limit and more than max_regions remain, the limit is
    dropped (the region count wins over the region size)."""
    from scipy.spatial import cKDTree

    rects = _runs_and_stack([list(r) for r in rects])
    while len(rects) > max_regions:
        arr = np.array(rects, dtype=np.int64)
        centres = np.stack([(arr[:, 0] + arr[:, 2]) / 2, (arr[:, 1] + arr[:, 3]) / 2], axis=1)
        k = min(9, len(rects))
        _, nn = cKDTree(centres).query(centres, k=k)
        cand = []
        for i in range(len(rects)):
            for j in nn[i][1:]:
                j = int(j)
                if j <= i and i in nn[j][1:]:
                    continue
                a, b = rects[i], rects[j]
                u = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                if u[2] - u[0] > max_side or u[3] - u[1] > max_side:
                    continue
                cand.append((_area(u) - _area(a) - _area(b), i, j, u))
        if not cand:
            if max_side >= 10**9:
                break
            max_side = 10**9
            continue
        cand.sort(key=lambda c: c[0])
        used: set[int] = set()
        new: list[list[int]] = []
        need = len(rects) - max_regions
        done = 0
        for _, i, j, u in cand:
            if i in used or j in used:
                continue
            used.update((i, j))
            new.append(u)
            done += 1
            if done >= max(1, min(need, len(rects) // 4)):
                break
        rects = new + [r for i, r in enumerate(rects) if i not in used]
        rects = _runs_and_stack(rects)
    return rects


def plan_regions(cells: np.ndarray, block: int = BLOCK, max_regions: int = MAX_REGIONS, max_side: int = MAX_SIDE,
                 g: Grid | None = None) -> dict[str, Any]:
    """Task regions covering all survivor cells. Returns {regions: [[ix0, iy0, w, h], ...], stats: {...}} with the number of
    survivors, occupied blocks, regions, exported cells, the exported share of the grid and the waste factor
    (exported cells per survivor)."""
    g = g or Grid()
    bl = blocks_of(cells, block)
    rects = [[int(bx * block), int(by * block), int((bx + 1) * block), int((by + 1) * block)] for bx, by in bl]
    merged = merge_rects(rects, max_regions, max_side) if rects else []
    regions = []
    for x0, y0, x1, y1 in merged:
        # shrink to the bounding box of the survivors inside (the block grid is aligned to cell 0, survivors are not)
        sel = cells[(cells[:, 0] >= x0) & (cells[:, 0] < x1) & (cells[:, 1] >= y0) & (cells[:, 1] < y1)]
        if len(sel) == 0:
            continue
        x0, y0 = int(sel[:, 0].min()), int(sel[:, 1].min())
        x1, y1 = int(sel[:, 0].max()) + 1, int(sel[:, 1].max()) + 1
        regions.append([x0, y0, x1 - x0, y1 - y0])
    exported = int(sum(w * h for _, _, w, h in regions))
    n_unique = len(cells)
    stats = {"survivors": n_unique, "blocks": int(len(bl)), "block_cells": block, "regions": len(regions),
             "exported_cells": exported, "block_cells_total": int(len(bl) * block * block),
             "grid_cells": g.ncols * g.nrows,
             "waste_factor": exported / n_unique if n_unique else None,
             "all_survivors_covered": bool(_all_covered(cells, regions))}
    return {"regions": regions, "stats": stats}


def _all_covered(cells: np.ndarray, regions: list[list[int]]) -> bool:
    if len(cells) == 0:
        return True
    hit = np.zeros(len(cells), bool)
    for x0, y0, w, h in regions:
        hit |= (cells[:, 0] >= x0) & (cells[:, 0] < x0 + w) & (cells[:, 1] >= y0) & (cells[:, 1] < y0 + h)
    return bool(hit.all())
