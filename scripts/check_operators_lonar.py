"""Compare the Earth Engine terrain operator with the numpy operator on the Lonar box (GitHub issue 2, one window).

    uv run python scripts/check_operators_lonar.py [--force-download]

Steps:
  1. download the 33.333 m mean DEM (z33 of gee_export.terrain_bands) for the tile region of
     data/raw/earth_test_lonar plus a 1 km margin on every side (one GeoTIFF, data/raw/earth_test/);
  2. run gsop.operators.tile_features on that array;
  3. read the Earth Engine tile features from data/raw/earth_test_lonar and join on tile_id;
  4. per feature: tiles compared, median and 95th percentile relative difference, max absolute difference.
A feature passes when the median relative difference is under 10 percent. The threshold is not tuned.
Relative difference is |EE - numpy| / |numpy|, taken over tiles where both values are finite and numpy is not 0.
Also written, for diagnosis only: signed median difference (EE - numpy) and the share of tiles with a NaN on one side.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
from gsop.config import load_all  # noqa: E402
from gsop.earth import gee_export as GE  # noqa: E402
from gsop.earth.local_loaders import build_earth_table  # noqa: E402
from gsop.grid import Grid  # noqa: E402
from gsop.operators import tile_features  # noqa: E402
from gsop.provenance import ROOT  # noqa: E402

FEATURES = ("slope_med", "slope_p90", "relief", "rough_a", "rough_b")
THRESHOLD = 0.10          # median relative difference, project threshold from issue 2
MARGIN_M = 1000.0
RES_M = GE.DEM_SCALE
EE_DIR = ROOT / "data" / "raw" / "earth_test_lonar"
DEM_TIF = ROOT / "data" / "raw" / "earth_test" / "lonar_z33.tif"
OUT_JSON = ROOT / "results" / "operator_check.json"


def download_dem(region: list[int], force: bool = False) -> Path:
    """z33 over the tile region plus the margin, as one GeoTIFF on the 33.333 m grid."""
    if DEM_TIF.exists() and not force:
        return DEM_TIF
    import requests
    g = Grid()
    ix0, iy0, w, h = region
    xl, yt = g.x0 + ix0 * g.cell_m - MARGIN_M, g.y_top - iy0 * g.cell_m + MARGIN_M
    wm, hm = w * g.cell_m + 2 * MARGIN_M, h * g.cell_m + 2 * MARGIN_M
    geom = GE.ee.Geometry.Rectangle([xl, yt - hm, xl + wm, yt], proj=GE.CRS_WKT, geodesic=False)
    z33 = GE._agg(GE.dem(), GE.ee.Reducer.mean(), GE.DEM_SCALE, 64).rename("z33").toFloat()
    url = z33.getDownloadURL({"region": geom, "crs": GE.CRS_WKT, "crs_transform": [RES_M, 0, xl, 0, -RES_M, yt],
                              "format": "GEO_TIFF"})
    r = requests.get(url, timeout=1800)
    if not r.ok:
        raise RuntimeError(f"Earth Engine download failed {r.status_code}: {r.text[:1500]}")
    DEM_TIF.parent.mkdir(parents=True, exist_ok=True)
    DEM_TIF.write_bytes(r.content)
    return DEM_TIF


def numpy_table(tif: Path, region: list[int]) -> pd.DataFrame:
    import rasterio
    g = Grid()
    ix0, iy0, w, h = region
    with rasterio.open(tif) as ds:
        z = ds.read(1).astype(np.float64)
        if ds.nodata is not None:
            z[z == ds.nodata] = np.nan
        tf = ds.transform
    xl, yt = g.x0 + ix0 * g.cell_m - MARGIN_M, g.y_top - iy0 * g.cell_m + MARGIN_M
    n_w, n_h = int(round((w * g.cell_m + 2 * MARGIN_M) / RES_M)), int(round((h * g.cell_m + 2 * MARGIN_M) / RES_M))
    if abs(tf.c - xl) > 1e-3 or abs(tf.f - yt) > 1e-3 or abs(tf.a - RES_M) > 1e-6:
        raise ValueError(f"DEM origin or cell size does not match the tile grid: {tf}")
    if z.shape[0] < n_h or z.shape[1] < n_w:
        raise ValueError(f"DEM is {z.shape}, need {(n_h, n_w)}")
    z = z[:n_h, :n_w]
    feats = tile_features(z, RES_M, tile_m=g.cell_m, slope_baseline_m=500.0, rough_baselines_m=(100.0, 1000.0),
                          margin_m=MARGIN_M)
    ny, nx = feats["slope_med"].shape
    if (ny, nx) != (h, w):
        raise ValueError(f"numpy gave {(ny, nx)} tiles, expected {(h, w)}")
    jj, ii = np.mgrid[0:ny, 0:nx]
    df = pd.DataFrame({"tile_id": g.tile_id(ii.ravel() + ix0, jj.ravel() + iy0)})
    for k, v in feats.items():
        df[k] = v.ravel()
    return df


def compare(ee_df: pd.DataFrame, np_df: pd.DataFrame) -> dict:
    m = ee_df[["tile_id", *FEATURES]].merge(np_df, on="tile_id", suffixes=("_ee", "_np"))
    out = {}
    for f in FEATURES:
        a, b = m[f + "_ee"].to_numpy(float), m[f + "_np"].to_numpy(float)
        both = np.isfinite(a) & np.isfinite(b)
        use = both & (b != 0)
        d = a[use] - b[use]
        rel = np.abs(d) / np.abs(b[use])
        row = {
            "n_joined": int(len(m)),
            "n_compared": int(use.sum()),
            "n_nan_one_side": int((np.isfinite(a) != np.isfinite(b)).sum()),
            "median_rel_diff": float(np.median(rel)) if rel.size else None,
            "p95_rel_diff": float(np.percentile(rel, 95)) if rel.size else None,
            "max_abs_diff": float(np.abs(d).max()) if d.size else None,
            "median_signed_diff_ee_minus_np": float(np.median(d)) if d.size else None,
            "median_value_np": float(np.median(b[use])) if d.size else None,
        }
        row["pass"] = bool(rel.size and row["median_rel_diff"] < THRESHOLD)
        out[f] = row
    return out


def main() -> int:
    force = "--force-download" in sys.argv
    cfg = load_all()
    region = json.loads((EE_DIR / "bands.json").read_text())["region"]
    GE.init()
    tif = download_dem(region, force)
    np_df = numpy_table(tif, region)
    ee_df = build_earth_table(EE_DIR, ROOT / "data" / "interim" / "earth_test_lonar.parquet",
                              add_solar=True, solar_cfg=cfg["features"])
    res = compare(ee_df, np_df)
    payload = {"window": {"centre_lonlat": [76.51, 19.98], "region_ix0_iy0_w_h": region, "margin_m": MARGIN_M,
                          "dem_file": str(tif.relative_to(ROOT)), "ee_tiles": str(EE_DIR.relative_to(ROOT))},
               "threshold_median_rel_diff": THRESHOLD, "features": res}
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2))
    print(f"{'feature':10s} {'n':>4s} {'median rel':>11s} {'p95 rel':>9s} {'max abs':>10s} {'signed med':>11s} {'result':>6s}")
    for f, r in res.items():
        if r["n_compared"] == 0:
            print(f"{f:10s} {0:4d} {'n/a':>11s}")
            continue
        print(f"{f:10s} {r['n_compared']:4d} {r['median_rel_diff'] * 100:10.2f}% {r['p95_rel_diff'] * 100:8.2f}% "
              f"{r['max_abs_diff']:10.4g} {r['median_signed_diff_ee_minus_np']:11.4g} {'PASS' if r['pass'] else 'FAIL'}")
    return 0 if all(r["pass"] for r in res.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
