"""Build the Earth feature table from 6 km rasters (a Google Earth Engine export, or the open-data fallback).

Input: a GeoTIFF or a folder of GeoTIFFs in EPSG:6933 with 6000 m cells. Band names are found in this order:
  1. the band description inside the file (the open-data fallback writes these);
  2. for a single-band file named `<id>.<band>.tif` (Earth Engine's per-band download), the `<band>` part of the name;
  3. for a multiband file with no descriptions (an Earth Engine Drive export), the `band_order` of the
     `<name>_export_plan.json` that `gee_export` wrote, matched by the file's name (the plan lists each task's file name). The
     plan is looked for in the file's own folder, or is given explicitly (`plan=`, CLI `--plan`);
  4. for a single-band file, its stem (`land_frac.tif`).
Anything else is an error: a band is never guessed.
Files that share one grid are merged (one file per column, or one multiband file). Files on different grids are separate
blocks of one export (the global export is chunked): each block gives its tiles, and all blocks must have the same columns.
The tile id comes from each raster's own transform, so a regional export and a global export give the same ids for the same
cell. Required band: land_frac (share of the cell that is land). Gate layers: water_ice_frac, ndvi_median, built_crop_frac.
A band that is absent stays absent (the column is missing): the missing-data gate then rejects, and the run says why.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..grid import Grid
from ..provenance import write_json

LAND_MIN = 0.5


def plan_band_order(f: Path, plan_path: Path | None = None) -> list[str] | None:
    """band_order of the gee_export plan that lists this file (matched by task description). The plan is `plan_path` if
    given, otherwise any `*_export_plan.json` in the file's own folder."""
    for plan in ([Path(plan_path)] if plan_path else sorted(f.parent.glob("*_export_plan.json"))):
        try:
            p = json.loads(plan.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if any(t.get("description") == f.stem for t in p.get("tasks", [])):
            return list(p["band_order"])
    return None


def _band_names(f: Path, ds, plan_path: Path | None = None) -> list[str]:
    names = []
    plan = None
    for i in range(1, ds.count + 1):
        name = ds.descriptions[i - 1]
        if not name and ds.count == 1 and "." in f.stem:
            name = f.stem.rsplit(".", 1)[1]                       # <id>.<band>.tif
        if not name and ds.count > 1:
            plan = plan if plan is not None else (plan_band_order(f, plan_path) or [])
            name = plan[i - 1] if len(plan) == ds.count else None
        if not name and ds.count == 1:
            name = f.stem
        if not name:
            raise ValueError(f"{f}: band {i} has no description, is not named <id>.<band>.tif, and no export plan lists "
                             "this file (put the plan JSON in the same folder or pass --plan); refusing to guess its name")
        names.append(name)
    return names


def _read_groups(src: Path, plan_path: Path | None = None) -> list[tuple[dict[str, np.ndarray], object, tuple[int, int]]]:
    """One (bands, transform, shape) per grid. Files on the same grid are merged."""
    import rasterio
    files = [src] if src.is_file() else sorted(src.glob("*.tif"))
    if not files:
        raise FileNotFoundError(f"no GeoTIFF found at {src}")
    groups: dict[tuple, tuple[dict[str, np.ndarray], object, tuple[int, int]]] = {}
    for f in files:
        with rasterio.open(f) as ds:
            if ds.crs is None or ds.crs.to_epsg() != 6933:
                raise ValueError(f"{f}: expected EPSG:6933, got {ds.crs}")
            if abs(ds.transform.a - 6000.0) > 1e-6 or abs(ds.transform.e + 6000.0) > 1e-6:
                raise ValueError(f"{f}: expected 6000 m cells, got {ds.transform.a} x {ds.transform.e}")
            key = (tuple(ds.transform)[:6], ds.height, ds.width)
            bands, _, _ = groups.setdefault(key, ({}, ds.transform, (ds.height, ds.width)))
            for i, name in enumerate(_band_names(f, ds, plan_path), 1):
                if name in bands:
                    raise ValueError(f"{f}: band {name!r} appears twice on the same grid")
                a = ds.read(i).astype(np.float64)
                if ds.nodata is not None:
                    a[a == ds.nodata] = np.nan
                bands[name] = a
    return list(groups.values())


def _block_table(bands: dict[str, np.ndarray], tf, grid: Grid) -> pd.DataFrame:
    if "land_frac" not in bands:
        raise ValueError("a land_frac band is required (share of the 6 km cell that is land)")
    ix0 = int(round((tf.c - grid.x0) / grid.cell_m))
    iy0 = int(round((grid.y_top - tf.f) / grid.cell_m))
    land = bands["land_frac"] >= LAND_MIN
    jj, ii = np.nonzero(land)
    ix, iy = ii + ix0, jj + iy0
    lon, lat = grid.centre_lonlat(ix, iy)
    df = pd.DataFrame({"tile_id": grid.tile_id(ix, iy), "ix": ix, "iy": iy, "lon": lon, "lat": lat})
    for name, a in bands.items():
        if name != "land_frac":
            df[name] = a[jj, ii].astype(np.float32)
    return df


def build_earth_table(src: Path | str, out_path: Path | str, grid: Grid | None = None,
                      add_solar: bool = False, solar_cfg: dict | None = None, plan: Path | str | None = None) -> pd.DataFrame:
    grid = grid or Grid()
    blocks = [_block_table(b, tf, grid) for b, tf, _ in _read_groups(Path(src), Path(plan) if plan else None)]
    cols = [set(b.columns) for b in blocks]
    if any(c != cols[0] for c in cols[1:]):
        raise ValueError("blocks of one export must have the same columns; found "
                         + "; ".join(sorted({",".join(sorted(c ^ cols[0])) for c in cols[1:] if c != cols[0]})))
    df = pd.concat(blocks, ignore_index=True)
    if df["tile_id"].duplicated().any():
        raise ValueError(f"{int(df['tile_id'].duplicated().sum())} tiles appear in more than one block: the blocks overlap")
    if add_solar:
        # computed from latitude only (earth/solar.py); a band that the raster already has is never overwritten
        from .solar import sun_features
        for k, v in sun_features(df["lat"].to_numpy(), solar_cfg).items():
            if k not in df.columns:
                df[k] = v.astype(np.float32)
    df = df.sort_values("tile_id").reset_index(drop=True)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    write_json(out_path.parent / "grid.json", {"crs": grid.crs, "cell_m": grid.cell_m, "ncols": grid.ncols,
                                               "nrows": grid.nrows, "x0": grid.x0, "y_top": grid.y_top,
                                               "n_tiles": int(len(df)), "land_min_frac": LAND_MIN})
    return df
