"""ROLE D step 0: build the negative set from NON-THERMAL columns of the v1 Earth feature file (PREREG_D, section Negative set).
Writes runs/v2/negative_set_d.csv and prints its sha256. No thermal column is read."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from gsop.grid import haversine_km  # noqa: E402

EARTH = ROOT / "data" / "raw" / "v1" / "gsop_v1" / "data" / "processed" / "earth_features_6km.parquet"
SEED = 20261114
N_NEG = 200
TERRAIN = ["slope_med", "slope_p90", "relief", "elev_mean", "rough_a", "rough_b", "sun_max_elev", "sun_low_share",
           "insol_annual", "air_density"]


def main() -> None:
    ks = yaml.safe_load(open(ROOT / "config" / "known_sites.yaml", encoding="utf-8"))
    df = pd.read_parquet(EARTH, columns=["tile_id", "lat", "lon", "water_ice_frac", "ndvi_median", "built_crop_frac"] + TERRAIN)
    ok = (df["lat"].abs() <= 30) & (df["elev_mean"] <= 1000) & (df["ndvi_median"] <= 0.10)
    ok &= (df["water_ice_frac"] + df["built_crop_frac"]) <= 0.20
    ok &= df[TERRAIN].notna().all(axis=1)
    n_rule = int(ok.sum())
    lat, lon = df["lat"].to_numpy(), df["lon"].to_numpy()
    near = np.zeros(len(df), bool)
    for name, s in ks["primary"].items():
        near |= haversine_km(s["lat"], s["lon"], lat, lon) <= 100.0
    elig = df[ok & ~near].sort_values("tile_id").reset_index(drop=True)
    rng = np.random.default_rng(SEED)
    pick = np.sort(rng.choice(len(elig), size=N_NEG, replace=False))
    neg = elig.iloc[pick][["tile_id", "lat", "lon", "elev_mean", "ndvi_median", "water_ice_frac", "built_crop_frac"]]
    out = ROOT / "runs" / "v2" / "negative_set_d.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    neg.to_csv(out, index=False, float_format="%.6f", lineterminator="\n")
    h = hashlib.sha256(out.read_bytes()).hexdigest()
    print("tiles meeting the cover, latitude and elevation rule:", n_rule)
    print("eligible after the 100 km exclusion:", len(elig), "sampled:", len(neg))
    print("lat range", neg["lat"].min(), neg["lat"].max(), "elev max", neg["elev_mean"].max())
    print("sha256", h)


if __name__ == "__main__":
    main()
