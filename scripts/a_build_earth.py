"""ROLE A: assemble the Earth thermal blocks onto the v1 tile table and write the rank columns (PREREG_A).

Input : data/interim/a_thermal/blocks/b_<ix0>_<iy0>_<w>_<h>.npy  (6, h, w): th_mean_K, th_max_K, th_dn_K, valid shares
        data/raw/v1/gsop_v1/data/processed/earth_features_6km.parquet (v1 land tiles)
Output: data/processed/earth_features_v2_6km.parquet = v1 columns + th_*_K, th_valid_*, th_mean, th_max, th_ti (rank, 0 to 100)
        data/interim/a_thermal/assemble.json (counts)
Rank of v in set S = 100 * (n_below + 0.5 * n_equal) / n over all v1 land tiles valid for that feature (pre-gating).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "data/raw/v1/gsop_v1/data/processed/earth_features_6km.parquet"
BLK = ROOT / "data/interim/a_thermal/blocks"
OUT = ROOT / "data/processed/earth_features_v2_6km.parquet"
NCOLS, NROWS = 5790, 2448
MIN_VALID = 0.5


def midrank(x: np.ndarray) -> np.ndarray:
    """Mid-rank percentile of each finite element of x within the finite elements of x."""
    out = np.full(x.shape, np.nan, dtype=np.float64)
    ok = np.isfinite(x)
    v = x[ok]
    s = np.sort(v)
    lo = np.searchsorted(s, v, side="left")
    hi = np.searchsorted(s, v, side="right")
    out[ok] = 100.0 * (lo + 0.5 * (hi - lo)) / s.size
    return out


def main() -> dict:
    cube = np.full((6, NROWS, NCOLS), np.nan, dtype=np.float32)
    files = sorted(BLK.glob("b_*.npy"))
    for f in files:
        _, ix0, iy0, w, h = f.stem.split("_")
        ix0, iy0, w, h = int(ix0), int(iy0), int(w), int(h)
        a = np.load(f)
        assert a.shape == (6, h, w), (f, a.shape)
        cube[:, iy0:iy0 + h, ix0:ix0 + w] = a
    e = pd.read_parquet(V1)
    ix, iy = e["ix"].to_numpy(), e["iy"].to_numpy()
    names = ["th_mean_K", "th_max_K", "th_dn_K", "th_valid_mean", "th_valid_max", "th_valid_dn"]
    for k, n in enumerate(names):
        e[n] = cube[k][iy, ix]
    for feat, v in (("th_mean_K", "th_valid_mean"), ("th_max_K", "th_valid_max"), ("th_dn_K", "th_valid_dn")):
        bad = ~(e[v].to_numpy() >= MIN_VALID) | ~np.isfinite(e[feat].to_numpy())
        e.loc[bad, feat] = np.nan
    e["th_mean"] = midrank(e["th_mean_K"].to_numpy(np.float64))
    e["th_max"] = midrank(e["th_max_K"].to_numpy(np.float64))
    e["th_ti"] = midrank(-e["th_dn_K"].to_numpy(np.float64))
    for c in ("th_mean", "th_max", "th_ti"):
        e[c] = e[c].astype(np.float32)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    e.to_parquet(OUT, index=False)
    lat = e["lat"].to_numpy()
    band = (lat >= -55) & (lat <= 60)
    res = {
        "n_files": len(files), "n_v1_land_tiles": int(len(e)),
        "valid_th_mean_K": int(np.isfinite(e["th_mean_K"]).sum()), "valid_th_max_K": int(np.isfinite(e["th_max_K"]).sum()),
        "valid_th_dn_K": int(np.isfinite(e["th_dn_K"]).sum()),
        "valid_all_three": int((np.isfinite(e["th_mean_K"]) & np.isfinite(e["th_max_K"]) & np.isfinite(e["th_dn_K"])).sum()),
        "band_55S_60N_tiles": int(band.sum()), "band_valid_th_mean_K": int(np.isfinite(e["th_mean_K"])[band].sum()),
        "band_valid_share": float(np.isfinite(e["th_mean_K"])[band].mean()),
        "tiles_without_block": int((~np.isfinite(e["th_valid_mean"])).sum()),
    }
    (ROOT / "data/interim/a_thermal/assemble.json").write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
