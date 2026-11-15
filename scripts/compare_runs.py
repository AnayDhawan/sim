"""Compare a full run with a latitude-band robustness run (DECISIONS E29).

    uv run python scripts/compare_runs.py results/moon results/moon_lat20-40 [--out compare_lat_band.json]

Per target and profile (every `<target>__<profile>` folder with base_scores.parquet in both runs):
  top 1 percent   tiles of the highest base score, 1 percent of each run's own gated tiles (at least 1 tile)
                  jaccard_top1pct         full top 1 percent against band top 1 percent
                  jaccard_top1pct_inband  full top 1 percent restricted to tiles inside the band, against band top 1 percent
  robust          tiles with robust = true in mc_summary.parquet; same two Jaccard values
  top-20 robust   the full run's 20 best robust tiles (by mc_median); those outside the band cannot be checked by the band
                  run and are listed with lat/lon
The band is read from RUN_B/run_meta.json (`lat_band_abs_deg`), or given with --band LOW HIGH.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from gsop.grid import Grid


def tile_lat(tile_id: int) -> float:
    """Latitude of a tile centre from its id (tile_id = iy * ncols + ix on the EPSG:6933 grid)."""
    g = Grid()
    _, lat = g.centre_lonlat(int(tile_id) % g.ncols, int(tile_id) // g.ncols)
    return float(lat)


def jaccard(a: set, b: set) -> float | None:
    u = a | b
    return None if not u else len(a & b) / len(u)


def top_frac(base: pd.DataFrame, frac: float = 0.01) -> set:
    n = max(1, int(round(frac * len(base))))
    return set(base.nlargest(n, "score")["tile_id"].astype(np.int64))


def compare(run_a: Path, run_b: Path, band: tuple[float, float] | None = None, top_n: int = 20) -> dict:
    if band is None:
        meta = json.loads((run_b / "run_meta.json").read_text(encoding="utf-8"))
        band = tuple(meta["lat_band_abs_deg"])
    lo, hi = float(band[0]), float(band[1])
    out = {"run_full": str(run_a), "run_band": str(run_b), "lat_band_abs_deg": [lo, hi], "jobs": {}}
    for d in sorted(run_a.glob("*__*/base_scores.parquet")):
        name = d.parent.name
        if not (run_b / name / "base_scores.parquet").exists():
            out["jobs"][name] = {"note": "not in the band run"}
            continue
        ba = pd.read_parquet(d)
        bb = pd.read_parquet(run_b / name / "base_scores.parquet")
        ma = pd.read_parquet(run_a / name / "mc_summary.parquet")
        mb = pd.read_parquet(run_b / name / "mc_summary.parquet")
        inband = lambda ids: {t for t in ids if lo <= abs(tile_lat(t)) <= hi}  # noqa: E731
        ta, tb = top_frac(ba), top_frac(bb)
        ra = set(ma.loc[ma["robust"], "tile_id"].astype(np.int64))
        rb = set(mb.loc[mb["robust"], "tile_id"].astype(np.int64))
        best = ma[ma["robust"]].nlargest(top_n, "mc_median")
        outside = best[(best["lat"].abs() < lo) | (best["lat"].abs() > hi)]
        out["jobs"][name] = {
            "n_gated_full": int(len(ba)), "n_gated_band": int(len(bb)),
            "jaccard_top1pct": jaccard(ta, tb), "jaccard_top1pct_inband": jaccard(inband(ta), tb),
            "n_robust_full": len(ra), "n_robust_band": len(rb),
            "jaccard_robust": jaccard(ra, rb), "jaccard_robust_inband": jaccard(inband(ra), rb),
            "top20_robust_full_outside_band": [{"tile_id": int(r.tile_id), "lat": float(r.lat), "lon": float(r.lon),
                                                "mc_median": float(r.mc_median)} for r in outside.itertuples()],
            "n_top20_robust_full_inside_band": int(len(best) - len(outside)),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_full", type=Path)
    ap.add_argument("run_band", type=Path)
    ap.add_argument("--band", type=float, nargs=2, default=None)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    res = compare(a.run_full, a.run_band, tuple(a.band) if a.band else None)
    fmt = lambda v: "n/a" if v is None else f"{v:.3f}"  # noqa: E731
    print(f"band {res['lat_band_abs_deg'][0]:g} to {res['lat_band_abs_deg'][1]:g} deg (absolute)")
    for name, j in res["jobs"].items():
        if "note" in j:
            print(f"{name}: {j['note']}")
            continue
        print(f"{name}: top1% J {fmt(j['jaccard_top1pct'])} (in band {fmt(j['jaccard_top1pct_inband'])}); robust J "
              f"{fmt(j['jaccard_robust'])} (in band {fmt(j['jaccard_robust_inband'])}); top-20 robust inside band "
              f"{j['n_top20_robust_full_inside_band']}, outside {len(j['top20_robust_full_outside_band'])}")
    out = a.out or (a.run_band / "compare_with_full.json")
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"written {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
