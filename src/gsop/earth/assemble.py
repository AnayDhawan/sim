"""Assemble the Earth feature table from the Earth Engine Drive downloads (SPEC section 3e, DECISIONS E27).

Inputs (folders of GeoTIFFs, searched recursively, EPSG:6933, 6000 m cells, placed by their own affine transform):
  gate      gsop_gate         gate_6km_r??_c??[_p?][_s?].tif   4 bands land_frac, water_ice_frac, ndvi_median, built_crop_frac
  srtm      gsop_terrain90    terrain90_r??_c??[_r?].tif       6 bands slope_med, slope_p90, relief, elev_mean, rough_a, rough_b
  glo30     gsop_terrain90_hi terrain90_stage1_<site>_*.tif, terrain90_stage2_*.tif   same 6 bands
Band names come from the band descriptions when the file has them (they must then match the expected order exactly);
a file without descriptions is read in the expected order (the order of gee_export.landcover_bands / terrain_bands).

Missing values: NaN, -9999 and a declared nodata value are all missing.
Overlaps inside one source (Earth Engine writes one extra edge row or column that the neighbouring chunk also covers;
split retries `_r0`/`_r1` and Drive duplicates `name (1).tif` cover the same cells again): the finite value wins over a
missing one; two finite values must agree within RTOL/ATOL or the build stops with an error naming both files. A tile is
counted once however many files cover it.
Precedence between terrain sources: SRTM for tiles whose centre is at or below 60N, GLO30 above 60N; where the preferred
source is missing the other one is used if it has a value (GLO30 stage-1 boxes south of 56S, SRTM margin rows).
Output: one row per land tile (land_frac >= 0.5), tile_id = iy * ncols + ix, gate layers, the six terrain columns, lon/lat,
and (add_solar) sun_max_elev, sun_low_share, insol_annual, air_density. Tiles with no terrain stay NaN, so the
missing_data gate rejects them. A coverage report is returned, printed by the CLI and saved next to the table.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..grid import Grid
from ..provenance import write_json

GATE_BANDS = ["land_frac", "water_ice_frac", "ndvi_median", "built_crop_frac"]
TERRAIN_BANDS = ["slope_med", "slope_p90", "relief", "elev_mean", "rough_a", "rough_b"]
NODATA = -9999.0
LAND_MIN = 0.5
GLO30_ABOVE_LAT = 60.0
RTOL, ATOL = 1e-5, 1e-6
GATE_RE = re.compile(r"^gate_6km_r\d+_c\d+(_p\d+)?(_s\d+)*( \(\d+\))?$")
SRTM_RE = re.compile(r"^terrain90_r\d+_c\d+(_r\d+)*( \(\d+\))?$")
GLO30_RE = re.compile(r"^terrain90_stage[12]_.+$")


class OverlapError(ValueError):
    pass


def _files(folder: Path | None, pattern: re.Pattern) -> tuple[list[Path], list[str]]:
    if folder is None:
        return [], []
    folder = Path(folder)
    if not folder.exists():
        raise FileNotFoundError(f"{folder} does not exist")
    files, skipped = [], []
    for f in sorted(folder.rglob("*.tif")):
        if pattern.match(f.stem):
            files.append(f)
        else:
            skipped.append(f.name)
    return files, skipped


def _read(f: Path, expected: list[str], grid: Grid) -> tuple[np.ndarray, int, int]:
    """(bands x h x w float32 with NaN for missing, column offset, row offset) in the global grid."""
    import rasterio

    with rasterio.open(f) as ds:
        if ds.crs is None or ds.crs.to_epsg() != 6933:
            raise ValueError(f"{f}: expected EPSG:6933, got {ds.crs}")
        tf = ds.transform
        if abs(tf.a - grid.cell_m) > 1e-6 or abs(tf.e + grid.cell_m) > 1e-6 or tf.b or tf.d:
            raise ValueError(f"{f}: expected {grid.cell_m} m north-up cells, got {tf.a} x {tf.e}")
        if ds.count != len(expected):
            raise ValueError(f"{f}: {ds.count} bands, expected {len(expected)} ({', '.join(expected)})")
        desc = list(ds.descriptions)
        if any(desc) and desc != expected:
            raise ValueError(f"{f}: band descriptions {desc} differ from the expected order {expected}")
        a = ds.read().astype(np.float32)
        nod = ds.nodata
    c = (tf.c - grid.x0) / grid.cell_m
    r = (grid.y_top - tf.f) / grid.cell_m
    c0, r0 = int(round(c)), int(round(r))
    if abs(c - c0) > 1e-6 or abs(r - r0) > 1e-6:
        raise ValueError(f"{f}: origin is not on the 6 km grid (column {c:.4f}, row {r:.4f})")
    h, w = a.shape[1:]
    if c0 < 0 or r0 < 0 or c0 + w > grid.ncols or r0 + h > grid.nrows:
        raise ValueError(f"{f}: placement column {c0}, row {r0}, {w} x {h} falls outside the {grid.ncols} x {grid.nrows} grid")
    a[a == NODATA] = np.nan
    if nod is not None and np.isfinite(nod):
        a[a == np.float32(nod)] = np.nan
    return a, c0, r0


def _merge_into(dst: np.ndarray, owner: np.ndarray, src: np.ndarray, fid: int, names: list[str], files: list[Path],
                where: str) -> None:
    """dst, src: (bands, n) values; owner: (n,) index of the file that gave dst (-1 none). Finite beats missing; two
    finite values must agree."""
    have, new = np.isfinite(dst), np.isfinite(src)
    both = have & new
    if both.any():
        bad = both & ~np.isclose(dst, src, rtol=RTOL, atol=ATOL)
        if bad.any():
            b, i = (int(v[0]) for v in np.nonzero(bad))
            other = files[owner[i]].name if owner[i] >= 0 else "?"
            raise OverlapError(f"{where}: {files[fid].name} and {other} both have {names[b]} for the same tile with "
                               f"different values ({src[b, i]} vs {dst[b, i]})")
    take = new & ~have
    dst[take] = src[take]
    owner[take.any(axis=0) & (owner < 0)] = fid


def mosaic_gate(folder: Path, grid: Grid) -> tuple[np.ndarray, dict[str, Any]]:
    """Global (4, nrows, ncols) float32 gate mosaic, NaN where no file has a value."""
    files, skipped = _files(folder, GATE_RE)
    if not files:
        raise FileNotFoundError(f"no gate GeoTIFF (gate_6km_*.tif) under {folder}")
    m = np.full((len(GATE_BANDS), grid.nrows, grid.ncols), np.nan, dtype=np.float32)
    owner = np.full((grid.nrows, grid.ncols), -1, dtype=np.int32)
    for fid, f in enumerate(files):
        a, c0, r0 = _read(f, GATE_BANDS, grid)
        h, w = a.shape[1:]
        sub = m[:, r0:r0 + h, c0:c0 + w].reshape(len(GATE_BANDS), -1)
        own = owner[r0:r0 + h, c0:c0 + w].reshape(-1)
        _merge_into(sub, own, a.reshape(len(GATE_BANDS), -1), fid, GATE_BANDS, files, "gate")
        m[:, r0:r0 + h, c0:c0 + w] = sub.reshape(len(GATE_BANDS), h, w)
        owner[r0:r0 + h, c0:c0 + w] = own.reshape(h, w)
    known = np.isfinite(m[0])
    return m, {"files": len(files), "skipped_names": skipped, "cells_with_land_frac": int(known.sum()),
               "grid_cells": int(known.size)}


# Two terrain files of the SAME product can both carry a tile on their shared border (a Copernicus stage 2 chunk and a
# stage 1 validation box, or two neighbouring chunks). The slope baseline (500 m) and the roughness windows reach a few
# cells beyond a tile, so a tile on a file's edge sees less context and its value differs a little from the same tile
# in the interior of the other file. Such a difference up to CONFLICT_MAX (relative, plus a small absolute term) is
# resolved by taking the file where the tile lies farther from the file's edge (the largest relative difference seen is
# reported); a difference above CONFLICT_MAX means the two files hold different data and still stops the build.
CONFLICT_MAX = 0.50


def _merge_terrain(vals: np.ndarray, edist: np.ndarray, owner: np.ndarray, r: np.ndarray, src: np.ndarray,
                   ed_src: np.ndarray, fid: int, names: list[str], files: list[Path], where: str) -> int:
    """Merge one file's (bands, k) values `src` into vals[:, r]. Finite beats missing; a small disagreement is resolved
    by the larger distance to the file edge; a large one raises OverlapError. Returns the number of tiles resolved."""
    dst = vals[:, r]
    have, new = np.isfinite(dst), np.isfinite(src)
    both = have & new
    resolved = 0
    better = np.zeros(r.size, dtype=bool)
    if both.any():
        diff = both & ~np.isclose(dst, src, rtol=RTOL, atol=ATOL)
        if diff.any():
            tol = CONFLICT_MAX * np.maximum(np.abs(dst), np.abs(src)) + 1e-3
            big = diff & (np.abs(dst - src) > tol)
            if big.any():
                b, i = (int(v[0]) for v in np.nonzero(big))
                o = owner[r[i]]
                other = files[o].name if o >= 0 else "?"
                raise OverlapError(f"{where}: {files[fid].name} and {other} both have {names[b]} for the same tile "
                                   f"with values {src[b, i]} and {dst[b, i]} (more than {CONFLICT_MAX:.0%} apart)")
            tiles = diff.any(axis=0)
            better = tiles & (ed_src > edist[r])
            resolved = int(tiles.sum())
    take = new & ~have
    out = dst.copy()
    out[take] = src[take]
    sel = better[None, :] & new
    out[sel] = src[sel]
    vals[:, r] = out
    moved = take.any(axis=0) | better
    upd = moved & ((owner[r] < 0) | better | (ed_src > edist[r]))
    owner[r[upd]] = fid
    edist[r[upd]] = ed_src[upd]
    return resolved


def terrain_for_tiles(folder: Path | None, pattern: re.Pattern, idx: np.ndarray, n: int, grid: Grid,
                      label: str) -> tuple[np.ndarray, dict[str, Any]]:
    """(6, n) terrain values for the land tiles; idx is the global (nrows, ncols) map cell -> land row (-1 not land)."""
    vals = np.full((len(TERRAIN_BANDS), n), np.nan, dtype=np.float32)
    owner = np.full(n, -1, dtype=np.int32)
    edist = np.full(n, -1, dtype=np.int32)
    files, skipped = _files(folder, pattern)
    resolved = 0
    for fid, f in enumerate(files):
        a, c0, r0 = _read(f, TERRAIN_BANDS, grid)
        h, w = a.shape[1:]
        rows = idx[r0:r0 + h, c0:c0 + w].reshape(-1)
        land = rows >= 0
        if not land.any():
            continue
        hh, ww = np.arange(h)[:, None], np.arange(w)[None, :]
        ed = np.minimum(np.minimum(hh, h - 1 - hh), np.minimum(ww, w - 1 - ww)).reshape(-1).astype(np.int32)
        resolved += _merge_terrain(vals, edist, owner, rows[land], a.reshape(len(TERRAIN_BANDS), -1)[:, land],
                                   ed[land], fid, TERRAIN_BANDS, files, label)
    return vals, {"files": len(files), "skipped_names": skipped, "edge_overlap_tiles_resolved": resolved}


def assemble(gate_dir: Path | str, srtm_dir: Path | str | None, glo30_dir: Path | str | None,
             grid: Grid | None = None, add_solar: bool = True, solar_cfg: dict | None = None
             ) -> tuple[pd.DataFrame, dict[str, Any]]:
    grid = grid or Grid()
    gate, gate_rep = mosaic_gate(Path(gate_dir), grid)
    land = np.isfinite(gate[0]) & (gate[0] >= LAND_MIN)
    jj, ii = np.nonzero(land)                      # row-major, so tile_id ascending
    n = int(jj.size)
    idx = np.full((grid.nrows, grid.ncols), -1, dtype=np.int64)
    idx[jj, ii] = np.arange(n)
    lon, lat = grid.centre_lonlat(ii, jj)
    df = pd.DataFrame({"tile_id": grid.tile_id(ii, jj).astype(np.int64), "ix": ii.astype(np.int64),
                       "iy": jj.astype(np.int64), "lon": np.asarray(lon, dtype=np.float64),
                       "lat": np.asarray(lat, dtype=np.float64)})
    for k, name in enumerate(GATE_BANDS[1:], 1):
        df[name] = gate[k][jj, ii].astype(np.float32)
    del gate
    srtm, srep = terrain_for_tiles(Path(srtm_dir) if srtm_dir else None, SRTM_RE, idx, n, grid, "srtm")
    glo, grep_ = terrain_for_tiles(Path(glo30_dir) if glo30_dir else None, GLO30_RE, idx, n, grid, "glo30")
    del idx
    s_ok, g_ok = np.isfinite(srtm).all(axis=0), np.isfinite(glo).all(axis=0)
    north = df["lat"].to_numpy() > GLO30_ABOVE_LAT
    use_glo = np.where(north, g_ok, g_ok & ~s_ok)
    use_srtm = ~use_glo & s_ok
    terr = np.full_like(srtm, np.nan)
    terr[:, use_srtm] = srtm[:, use_srtm]
    terr[:, use_glo] = glo[:, use_glo]
    # a tile where neither source has all six bands still takes what the preferred source has (partial NaN)
    rest = ~use_srtm & ~use_glo
    pref = np.where(north[rest], 1, 0)
    if rest.any():
        terr[:, rest] = np.where(pref[None, :] == 1, glo[:, rest], srtm[:, rest])
    for k, name in enumerate(TERRAIN_BANDS):
        df[name] = terr[k]
    if add_solar:
        from ..astro import add_earth_derived
        df = add_earth_derived(df, solar_cfg)
    complete = np.isfinite(terr).all(axis=0)
    gate_ok = np.isfinite(df[GATE_BANDS[1:]].to_numpy()).all(axis=1)
    rep = {
        "grid": {"ncols": grid.ncols, "nrows": grid.nrows, "cell_m": grid.cell_m},
        "gate": gate_rep, "srtm": srep, "glo30": grep_,
        "land_tiles": n,
        "land_tiles_with_all_gate_layers": int(gate_ok.sum()),
        "tiles_terrain_from_srtm": int(use_srtm.sum()),
        "tiles_terrain_from_glo30": int(use_glo.sum()),
        "tiles_in_both_sources": int((s_ok & g_ok).sum()),
        "tiles_with_complete_terrain": int(complete.sum()),
        "tiles_with_nan_terrain": int((~complete).sum()),
        "share_of_land_tiles_with_terrain": round(float(complete.mean()) if n else 0.0, 6),
        "tiles_north_of_60_without_terrain": int((north & ~complete).sum()),
        "tiles_south_of_56s_without_terrain": int(((df["lat"].to_numpy() < -56.0) & ~complete).sum()),
    }
    return df, rep


def write_outputs(df: pd.DataFrame, rep: dict[str, Any], out_path: Path | str, grid: Grid | None = None) -> None:
    grid = grid or Grid()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    write_json(out_path.parent / "grid.json", {"crs": grid.crs, "cell_m": grid.cell_m, "ncols": grid.ncols,
                                               "nrows": grid.nrows, "x0": grid.x0, "y_top": grid.y_top,
                                               "n_tiles": int(len(df)), "land_min_frac": LAND_MIN})
    write_json(out_path.parent / "earth_coverage.json", rep)


def format_report(rep: dict[str, Any]) -> list[str]:
    g = rep["gate"]
    return [
        f"gate files {g['files']}, grid cells with land_frac {g['cells_with_land_frac']:,} of {g['grid_cells']:,} "
        f"({g['cells_with_land_frac'] / g['grid_cells']:.1%} of the grid known)",
        f"land tiles (land_frac >= {LAND_MIN}) {rep['land_tiles']:,}; with all three gate layers "
        f"{rep['land_tiles_with_all_gate_layers']:,}",
        f"terrain files: srtm {rep['srtm']['files']}, glo30 {rep['glo30']['files']}",
        f"terrain source per tile: srtm {rep['tiles_terrain_from_srtm']:,}, glo30 {rep['tiles_terrain_from_glo30']:,} "
        f"(covered by both {rep['tiles_in_both_sources']:,})",
        f"land tiles with complete terrain {rep['tiles_with_complete_terrain']:,} "
        f"({rep['share_of_land_tiles_with_terrain']:.1%}); NaN terrain {rep['tiles_with_nan_terrain']:,} "
        f"(north of 60N {rep['tiles_north_of_60_without_terrain']:,}, south of 56S {rep['tiles_south_of_56s_without_terrain']:,})",
    ] + [f"skipped (name does not match): {k} {', '.join(rep[k]['skipped_names'][:10])}"
         for k in ("gate", "srtm", "glo30") if rep[k]["skipped_names"]]
