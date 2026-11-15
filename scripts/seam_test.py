"""DEM seam at 60 N: SRTM90 (used up to 60 N) against Copernicus GLO30 (used above), same tiles, same graph (E22, E23, E27).

    uv run python scripts/seam_test.py --lon 8.0 --lat 59.0 --half-km 60 --out results/seam_test_59N.json
    uv run python scripts/seam_test.py --analyse-only DIR_SRTM DIR_GLO30     # re-run the statistics on saved downloads

Downloads one small box (default 20 x 20 tiles of 6 km) twice with Earth Engine getDownloadURL (interactive, no export, no
Drive): once with terrain_bands(100.0, "srtm90", (3, 10)) and once with terrain_bands(100.0, "glo30", (3, 10)), both on the
6 km grid of the production exports. Only tiles with all six terrain values in both DEMs count. For each feature it prints
the median difference (glo30 minus srtm90), the median relative difference (difference over the srtm90 value, tiles where
that value is above a small floor), and the Pearson and Spearman correlations over tiles. Pick a box where both DEMs have
data (58 to 60 N); above 60 N SRTM has none, so a box north of 60 N cannot be tested.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

FEATURES = ["slope_med", "slope_p90", "relief", "elev_mean", "rough_a", "rough_b"]
REL_FLOOR = {"slope_med": 0.05, "slope_p90": 0.05, "relief": 1.0, "elev_mean": 1.0, "rough_a": 0.01, "rough_b": 0.01}


def _rank(a: np.ndarray) -> np.ndarray:
    order = a.argsort(kind="mergesort")
    r = np.empty(len(a))
    r[order] = np.arange(len(a))
    return r


def compare(srtm: dict[str, np.ndarray], glo: dict[str, np.ndarray]) -> dict:
    """srtm and glo: feature name to 2-D array (NaN where masked), same shape. Returns per-feature statistics."""
    ok = np.ones(next(iter(srtm.values())).shape, dtype=bool)
    for f in FEATURES:
        ok &= np.isfinite(srtm[f]) & np.isfinite(glo[f])
    out = {"tiles_both": int(ok.sum()), "tiles_srtm": int(np.isfinite(srtm["slope_med"]).sum()),
           "tiles_glo30": int(np.isfinite(glo["slope_med"]).sum()), "features": {}}
    for f in FEATURES:
        s, g = srtm[f][ok].astype(float), glo[f][ok].astype(float)
        d = g - s
        m = np.abs(s) > REL_FLOOR[f]
        rel = d[m] / np.abs(s[m])
        out["features"][f] = {
            "median_srtm": float(np.median(s)), "median_glo30": float(np.median(g)),
            "median_diff": float(np.median(d)), "median_rel_diff": float(np.median(rel)) if m.any() else None,
            "p05_p95_rel_diff": [float(np.percentile(rel, 5)), float(np.percentile(rel, 95))] if m.any() else None,
            "pearson": float(np.corrcoef(s, g)[0, 1]), "spearman": float(np.corrcoef(_rank(s), _rank(g))[0, 1]),
            "tiles_rel": int(m.sum())}
    return out


def read_dir(folder: Path) -> dict[str, np.ndarray]:
    import rasterio
    out = {}
    one = sorted(folder.glob("download.tif"))
    if one:                                     # Earth Engine returns one multi-band file; bands are in terrain_bands order
        with rasterio.open(one[0]) as ds:
            if ds.count != len(FEATURES):
                raise RuntimeError(f"{one[0]}: {ds.count} bands, expected {len(FEATURES)}")
            for i, f in enumerate(FEATURES, start=1):
                out[f] = ds.read(i, masked=True).astype("float64").filled(np.nan)
        return out
    for f in FEATURES:
        hits = sorted(folder.glob(f"*.{f}.tif"))
        if len(hits) != 1:
            raise RuntimeError(f"{folder}: expected one file for {f}, found {[h.name for h in hits]}")
        with rasterio.open(hits[0]) as ds:
            out[f] = ds.read(1, masked=True).astype("float64").filled(np.nan)
    return out


def download(source: str, lon: float, lat: float, half_km: float, folder: Path) -> None:
    import io
    import zipfile

    import requests

    from gsop.earth import gee_export as GE
    img = GE.terrain_bands(100.0, source, (3, 10)).toFloat()
    ix0, iy0, w, h = GE.lonlat_box_to_cells(lon, lat, half_km)
    geom, tf = GE.chunk_region(ix0, iy0, w, h)
    url = img.getDownloadURL({"region": geom, "crs": GE.CRS_WKT, "crs_transform": tf, "format": "ZIPPED_GEO_TIFF",
                              "filePerBand": True})
    r = requests.get(url, timeout=1800)
    if not r.ok:
        raise RuntimeError(f"Earth Engine download failed for {source}: {r.status_code} {r.text[:1500]}")
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        z.extractall(folder)
    (folder / "cells.json").write_text(json.dumps({"cells": [ix0, iy0, w, h], "source": source, "lon": lon, "lat": lat}))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lon", type=float, default=8.0)
    ap.add_argument("--lat", type=float, default=59.0)
    ap.add_argument("--half-km", type=float, default=60.0)
    ap.add_argument("--out", type=Path, default=Path("results/seam_test.json"))
    ap.add_argument("--keep", type=Path, default=None, help="folder to keep the downloaded GeoTIFFs in (default: temporary)")
    ap.add_argument("--analyse-only", nargs=2, type=Path, metavar=("DIR_SRTM", "DIR_GLO30"))
    a = ap.parse_args()
    if a.analyse_only:
        res = compare(read_dir(a.analyse_only[0]), read_dir(a.analyse_only[1]))
    else:
        from gsop.earth import gee_export as GE
        GE.init()
        base = a.keep or Path(tempfile.mkdtemp(prefix="gsop_seam_"))
        for src in ("srtm90", "glo30"):
            download(src, a.lon, a.lat, a.half_km, base / src)
        res = compare(read_dir(base / "srtm90"), read_dir(base / "glo30"))
        ix0, iy0, w, h = GE.lonlat_box_to_cells(a.lon, a.lat, a.half_km)
        res["box"] = {"lon": a.lon, "lat": a.lat, "half_km": a.half_km, "cells": [ix0, iy0, w, h]}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
