"""ROLE A, PREREG_A addendum 1, section 2: own-tile percentile, best-of-radius percentile and chance level for every labelled site.

  python scripts/a_secondary.py <variant> [<variant> ...]      variants: baseline B3 S0 H S1 S2 S3
Reads results/a_<variant>/<body>/<target>__base/base_scores.parquet and gates__base.parquet. Writes results/a_<variant>/secondary.json.
Chance level: shuffle seed 20261114, 1000 draws. Permuting feature rows jointly is the same as drawing n scores without replacement from the
view's score vector, because a tile's score depends only on its own row. One generator per view, sites in alphabetical order.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from gsop.config import load_all  # noqa: E402
from gsop.grid import haversine_km  # noqa: E402

V1E = ROOT / "data/raw/v1/gsop_v1/data/processed/earth_features_6km.parquet"
SEED, DRAWS = 20261114, 1000
TARGETS = {"moon": ["connecting_ridge_c1", "shackleton_rim"], "mars": ["jezero"]}


def sites_for(ks: dict, body: str) -> dict[str, dict]:
    out = {}
    for n, s in ks["primary"].items():
        if body in s["bodies"]:
            out[n] = {**s, "role": "positive"}
    for n, s in ks["negative_controls"].items():
        if body in s.get("bodies", [body]):
            out[n] = {**s, "role": "control"}
    return dict(sorted(out.items()))


def draw_unique(rng, n_pop: int, n: int, draws: int) -> np.ndarray:
    idx = rng.integers(0, n_pop, size=(draws, n))
    for _ in range(50):
        srt = np.sort(idx, axis=1)
        dup = np.flatnonzero((srt[:, 1:] == srt[:, :-1]).any(axis=1)) if n > 1 else np.array([], int)
        if dup.size == 0:
            break
        idx[dup] = rng.integers(0, n_pop, size=(dup.size, n))
    return idx


def summ(a: np.ndarray) -> dict:
    return {"mean": float(a.mean()), "p2.5": float(np.percentile(a, 2.5)), "p97.5": float(np.percentile(a, 97.5)),
            "min": float(a.min()), "max": float(a.max())}


def main(variants: list[str]) -> None:
    cfg = load_all()
    radius = float(cfg["run"]["site_match_radius_km"])
    e = pd.read_parquet(V1E, columns=["tile_id", "lat", "lon"])
    tid, lat, lon = e["tile_id"].to_numpy(), e["lat"].to_numpy(), e["lon"].to_numpy()
    for v in variants:
        out = {"variant": v, "seed": SEED, "draws": DRAWS, "radius_km": radius, "bodies": {}}
        for body, tgts in TARGETS.items():
            bdir = ROOT / "results" / f"a_{v}" / body
            if not (bdir / "gates__base.parquet").exists():
                continue
            sites = sites_for(cfg["known_sites"], body)
            per_site: dict[str, dict] = {n: {"role": s["role"], "targets": {}} for n, s in sites.items()}
            for t in tgts:
                sp = bdir / f"{t}__base" / "base_scores.parquet"
                if not sp.exists():
                    continue
                sc = pd.read_parquet(sp)
                scores = sc["score"].to_numpy(np.float64)
                ser = pd.Series(scores, index=sc["tile_id"].to_numpy())
                srt = np.sort(scores)
                n_all = srt.size
                pct = lambda x: 100.0 * np.searchsorted(srt, x, side="left") / n_all  # noqa: E731
                rng = np.random.default_rng(SEED)
                for name, s in sites.items():                       # alphabetical
                    d = haversine_km(s["lat"], s["lon"], lat, lon)
                    near = tid[d <= float(s.get("radius_km", radius))]
                    gated = ser.reindex(near).dropna()
                    i = int(np.argmin(d))
                    own_t = int(tid[i])
                    rec = {"n_gated_in_radius": int(gated.size), "own_tile": own_t, "own_km": float(d[i])}
                    if gated.size:
                        rec["best_of_radius_pct"] = float(pct(float(gated.max())))
                        idx = draw_unique(rng, n_all, int(gated.size), DRAWS)
                        rec["chance_best"] = summ(pct(scores[idx].max(axis=1)))
                    else:
                        rec["best_of_radius_pct"] = None
                        rec["chance_best"] = None
                        rng.integers(0, 2, 1)
                    if own_t in ser.index:
                        rec["own_tile_pct"] = float(pct(float(ser.loc[own_t])))
                        rec["own_status"] = "scored"
                    else:
                        rec["own_tile_pct"], rec["own_status"] = None, "gated_out"
                    rec["chance_own"] = summ(pct(scores[rng.integers(0, n_all, DRAWS)]))
                    rec["n_gated_view"] = int(n_all)
                    per_site[name]["targets"][t] = rec
            for name, d in per_site.items():
                ts = d["targets"]
                for key in ("best_of_radius_pct", "own_tile_pct"):
                    vals = [r[key] for r in ts.values() if r.get(key) is not None]
                    d[f"mean_{key}"] = float(np.mean(vals)) if len(vals) == len(ts) and vals else None
                d["chance_best_mean_over_targets"] = float(np.mean([r["chance_best"]["mean"] for r in ts.values() if r.get("chance_best")])) if ts and all(r.get("chance_best") for r in ts.values()) else None
                d["chance_own_mean_over_targets"] = float(np.mean([r["chance_own"]["mean"] for r in ts.values()])) if ts else None
            out["bodies"][body] = per_site
        (ROOT / "results" / f"a_{v}").mkdir(parents=True, exist_ok=True)
        (ROOT / "results" / f"a_{v}" / "secondary.json").write_text(json.dumps(out, indent=1))
        print("wrote", v, flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
