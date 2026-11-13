"""s1 tiles: the tile universe. Land tiles of the 6 km EPSG:6933 grid -> data/interim/tiles.parquet.

The land flag is the `land_frac` band of the 6 km Earth raster (share of the cell that is land; the Earth Engine export
or the open-data fallback writes it, see earth/local_loaders.py). A tile is land when land_frac >= LAND_MIN (0.5).
Which land-cover product that band comes from is recorded with the raster (docs/PROVENANCE.md); this module does not
choose one. Polar ice is kept here and rejected later by the water/ice gate.

The raster is read in bands of `chunk_rows` rows, so memory stays small however large the raster is. Output columns:
tile_id (int64), lon, lat (centre, degrees), x, y (centre, EPSG:6933 metres), land_frac, ix, iy.
The land-tile count is printed and compared with the plan's expectation (about 4 million); far off is flagged.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .earth.local_loaders import LAND_MIN, _band_names
from .grid import Grid
from .provenance import StageStore, config_hash, sha256_file

log = logging.getLogger("gsop.tiles")
COLUMNS = ["tile_id", "lon", "lat", "x", "y", "land_frac", "ix", "iy"]


def count_report(n: int, expected: int, far_off_frac: float) -> dict[str, Any]:
    ratio = n / expected if expected else float("nan")
    far = not (abs(ratio - 1.0) <= far_off_frac)
    msg = (f"{n:,} land tiles; the plan expects about {expected:,} (ratio {ratio:.2f}); "
           + (f"FAR OFF (more than {far_off_frac:.0%} away): check the land mask, the grid and the raster extent"
              if far else "within the expected range"))
    return {"n_land_tiles": int(n), "expected": int(expected), "ratio": float(ratio), "far_off": bool(far), "message": msg}


def _files(src: Path) -> list[Path]:
    files = [src] if src.is_file() else sorted(src.glob("*.tif"))
    if not files:
        raise FileNotFoundError(f"no GeoTIFF found at {src}")
    return files


def build_tiles(src: Path | str, out_path: Path | str, grid: Grid | None = None, chunk_rows: int = 200,
                expected: int = 4_000_000, far_off_frac: float = 0.30, plan: Path | str | None = None) -> dict[str, Any]:
    """Write the land tiles of `src` (a land_frac raster, or a folder of them) to `out_path`. Returns the count report."""
    import rasterio
    grid = grid or Grid()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".tmp")
    schema = pa.schema([("tile_id", pa.int64()), ("lon", pa.float64()), ("lat", pa.float64()), ("x", pa.float64()),
                        ("y", pa.float64()), ("land_frac", pa.float32()), ("ix", pa.int64()), ("iy", pa.int64())])
    n = 0
    seen_blocks: list[tuple[int, int, int, int]] = []
    writer = pq.ParquetWriter(tmp, schema)
    try:
        for f in _files(Path(src)):
            with rasterio.open(f) as ds:
                if ds.crs is None or ds.crs.to_epsg() != 6933:
                    raise ValueError(f"{f}: expected EPSG:6933, got {ds.crs}")
                if abs(ds.transform.a - grid.cell_m) > 1e-6 or abs(ds.transform.e + grid.cell_m) > 1e-6:
                    raise ValueError(f"{f}: expected {grid.cell_m:.0f} m cells, got {ds.transform.a} x {ds.transform.e}")
                names = _band_names(f, ds, Path(plan) if plan else None)
                if "land_frac" not in names:
                    raise ValueError(f"{f}: no land_frac band (bands: {names})")
                band = names.index("land_frac") + 1
                ix0 = int(round((ds.transform.c - grid.x0) / grid.cell_m))
                iy0 = int(round((grid.y_top - ds.transform.f) / grid.cell_m))
                box = (ix0, iy0, ix0 + ds.width, iy0 + ds.height)
                for b in seen_blocks:
                    if box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3]:
                        raise ValueError(f"{f}: overlaps another raster block {b}; a tile would appear twice")
                seen_blocks.append(box)
                for r0 in range(0, ds.height, chunk_rows):
                    h = min(chunk_rows, ds.height - r0)
                    a = ds.read(band, window=rasterio.windows.Window(0, r0, ds.width, h)).astype(np.float64)
                    if ds.nodata is not None:
                        a[a == ds.nodata] = np.nan
                    jj, ii = np.nonzero(np.nan_to_num(a, nan=0.0) >= LAND_MIN)
                    if jj.size == 0:
                        continue
                    ix, iy = ii + ix0, jj + r0 + iy0
                    lon, lat = grid.centre_lonlat(ix, iy)
                    x, y = grid.centre_xy(ix, iy)
                    writer.write_table(pa.table({"tile_id": grid.tile_id(ix, iy), "lon": lon, "lat": lat, "x": x, "y": y,
                                                 "land_frac": a[jj, ii].astype(np.float32), "ix": ix, "iy": iy},
                                                schema=schema))
                    n += int(jj.size)
        writer.close()
        os.replace(tmp, out_path)
    except BaseException:
        writer.close()
        tmp.unlink(missing_ok=True)
        raise
    rep = count_report(n, expected, far_off_frac)
    rep.update({"path": str(out_path), "land_min_frac": LAND_MIN})
    log.info("s1 tiles: %s", rep["message"])
    return rep


def run_stage(src: Path | str, interim_dir: Path | str, run_cfg: dict[str, Any], force: bool = False,
              plan: Path | str | None = None) -> dict[str, Any]:
    """The s1 stage with the resumable runner's marker: skipped when the raster, the tile settings and the code are
    unchanged and tiles.parquet still exists. Returns the count report (read back from the marker when skipped)."""
    interim = Path(interim_dir)
    store = StageStore(interim)
    files = _files(Path(src))
    tcfg = run_cfg["tiles"]
    inputs = {f"raster:{p.name}": sha256_file(p) for p in files}
    cfg_part = config_hash({"tiles": tcfg, "tile_m": run_cfg["tile_m"], "land_min": LAND_MIN})
    out = interim / "tiles.parquet"
    if not force:
        done, reason = store.check("s1_tiles", cfg_part, inputs)
        if done:
            log.info("[skip] s1_tiles: %s", reason)
            import json
            rep = json.loads((interim / "tiles_report.json").read_text(encoding="utf-8"))
            rep["skipped"] = True
            return rep
    else:
        reason = "forced"
    log.info("[run]  s1_tiles: %s", reason)
    store.invalidate("s1_tiles")
    rep = build_tiles(src, out, Grid(cell_m=float(run_cfg["tile_m"])), int(tcfg["chunk_rows"]),
                      int(tcfg["expected_land_tiles"]), float(tcfg["far_off_frac"]), plan)
    from .provenance import write_json
    write_json(interim / "tiles_report.json", rep)
    store.mark("s1_tiles", cfg_part, inputs, 0.0, [out, interim / "tiles_report.json"])
    rep["skipped"] = False
    return rep
