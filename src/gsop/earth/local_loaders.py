"""Build the Earth feature table from 6 km rasters (a Google Earth Engine export, or the open-data fallback).

Input: one multiband GeoTIFF in EPSG:6933 with 6000 m cells, band descriptions = column names, or a folder of
single-band <column>.tif files. Rasters may cover only a region (a test box); the tile id comes from the raster's own
transform, so a regional export and a global export give the same ids for the same cell.
Required band: land_frac (share of the cell that is land). Gate layers: water_ice_frac, ndvi_median, built_crop_frac.
A band that is absent stays absent (NaN column): the missing-data gate then rejects, and the run says why.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..grid import Grid
from ..provenance import sha256_file, write_json

LAND_MIN = 0.5


def _sidecar_name(f: Path, i: int) -> str | None:
    """Earth Engine GeoTIFFs may carry no band descriptions. gee_export writes `<name>_export_plan.json` with the band
    order; a `<file>.bands.json` (a list of names) next to the raster is also accepted."""
    side = f.with_name(f.name + ".bands.json")
    if side.exists():
        names = json.loads(side.read_text())
        return names[i - 1] if i - 1 < len(names) else None
    return None


def _read_bands(src: Path) -> tuple[dict[str, np.ndarray], object, tuple[int, int]]:
    import rasterio
    bands: dict[str, np.ndarray] = {}
    tf = None
    shape = None
    files = [src] if src.is_file() else sorted(src.glob("*.tif"))
    if not files:
        raise FileNotFoundError(f"no GeoTIFF found at {src}")
    for f in files:
        with rasterio.open(f) as ds:
            if ds.crs is None or ds.crs.to_epsg() != 6933:
                raise ValueError(f"{f}: expected EPSG:6933, got {ds.crs}")
            if abs(ds.transform.a - 6000.0) > 1e-6 or abs(ds.transform.e + 6000.0) > 1e-6:
                raise ValueError(f"{f}: expected 6000 m cells, got {ds.transform.a} x {ds.transform.e}")
            if tf is None:
                tf, shape = ds.transform, (ds.height, ds.width)
            elif (ds.transform, ds.height, ds.width) != (tf, shape[0], shape[1]):
                raise ValueError(f"{f}: raster is not aligned with the others")
            for i in range(1, ds.count + 1):
                name = ds.descriptions[i - 1] or (f.stem if ds.count == 1 else None) or _sidecar_name(f, i)
                if not name:
                    raise ValueError(f"{f}: band {i} has no description")
                a = ds.read(i).astype(np.float64)
                if ds.nodata is not None:
                    a[a == ds.nodata] = np.nan
                bands[name] = a
    return bands, tf, shape


def build_earth_table(src: Path | str, out_path: Path | str, grid: Grid | None = None,
                      add_solar: bool = False) -> pd.DataFrame:
    grid = grid or Grid()
    bands, tf, shape = _read_bands(Path(src))
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
    if add_solar:
        # computed from latitude only (earth/solar.py); a band that the raster already has is never overwritten
        from .solar import sun_features
        for k, v in sun_features(df["lat"].to_numpy()).items():
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
