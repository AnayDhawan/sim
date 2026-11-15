"""ROLE D scoring (PREREG_D). Tile-level metrics only. Stages:
  prep   <layer.parquet> <workdir>   build universes, terrain and thermal score arrays, units; engine check
  real   <workdir>                   metrics for M0..M3 on the real thermal layer, AUC bootstrap
  shuffle <workdir> <ndraws> <nproc> shuffled-feature chance baseline
The model score is (1 - g) * T + g * 100 * H (PREREG_D). Nothing here is tuned after a result."""
from __future__ import annotations

import copy
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from gsop import gates as G  # noqa: E402
from gsop import pipeline as P  # noqa: E402
from gsop import similarity as S  # noqa: E402
from gsop.config import load_all  # noqa: E402
from gsop.grid import Grid  # noqa: E402

V1 = ROOT / "data" / "raw" / "v1" / "gsop_v1"
SEED = 20261114
GRID5 = [0.0, 0.25, 0.5, 0.75, 1.0]
MOON_T = ["connecting_ridge_c1", "shackleton_rim"]
THERMAL = {"moon": ["th_mean", "th_max"], "mars": ["th_ti"]}
ILLUM_COLS = ["sun_max_elev", "sun_low_share"]
FLAG = {"fpr": 75.0, "r5": 95.0, "r10": 90.0, "r25": 75.0}


def midrank_col(x: np.ndarray, valid: np.ndarray) -> np.ndarray:
    out = np.full(x.size, np.nan)
    s = np.sort(x[valid])
    lo, hi = np.searchsorted(s, x[valid], "left"), np.searchsorted(s, x[valid], "right")
    out[valid] = 100.0 * (lo + 0.5 * (hi - lo)) / s.size
    return out


def load_earth(layer_path: Path) -> tuple[pd.DataFrame, dict]:
    e = pd.read_parquet(V1 / "data" / "processed" / "earth_features_6km.parquet")
    L = pd.read_parquet(layer_path, columns=["tile_id", "th_mean_K", "th_max_K", "th_dn_K", "th_valid_mean", "th_valid_max", "th_valid_dn"])
    assert len(L) == len(e) and np.array_equal(L["tile_id"].to_numpy(), e["tile_id"].to_numpy()), "layer tile order differs from v1"
    info = {}
    for name, k, v, sign in (("th_mean", "th_mean_K", "th_valid_mean", 1.0), ("th_max", "th_max_K", "th_valid_max", 1.0),
                             ("th_ti", "th_dn_K", "th_valid_dn", -1.0)):
        x = sign * L[k].to_numpy(dtype=float)
        valid = np.isfinite(x) & (L[v].to_numpy(dtype=float) >= 0.5)
        e[name] = midrank_col(x, valid)
        info[name] = {"n_valid": int(valid.sum()), "n_tiles": int(len(e))}
    lat = e["lat"].to_numpy()
    band = (lat >= -55) & (lat <= 60)
    info["share_valid_th_mean_lat_-55_60"] = float(np.isfinite(e["th_mean"].to_numpy())[band].mean())
    return e, info


def sites_units(cfg: dict) -> dict:
    ks, grid = cfg["known_sites"], Grid()
    pos = {n: s for n, s in ks["primary"].items() if "mars" in s["bodies"]}
    neg_sites = {n: ks["negative_controls"][n] for n in ("namib_sand_sea", "rub_al_khali")}
    out = {}
    for grp, d in (("pos", pos), ("negsite", neg_sites)):
        for n, s in d.items():
            ix, iy = grid.cell_of_lonlat(s["lon"], s["lat"])
            out[n] = {"group": grp, "lat": s["lat"], "lon": s["lon"], "tile_id": int(grid.tile_id(ix, iy))}
    return out


def cfg_variant(cfg: dict, moon_drop_illum: bool) -> dict:
    c = copy.deepcopy(cfg)
    if moon_drop_illum:
        d = c["run"]["drop_columns"]
        d["moon"] = list(d["moon"]) + ILLUM_COLS
    return c


def target_profiles() -> dict:
    return {"moon": P.load_target_profiles(V1 / "data" / "processed" / "targets_moon.parquet"),
            "mars": P.load_target_profiles(V1 / "data" / "processed" / "targets_mars.parquet")}


def engine_check(cfg: dict, e: pd.DataFrame, tp: dict) -> dict:
    """My terrain score on the v1 universe against the v1 base_scores.parquet of each target."""
    res = {}
    for body, targets in (("moon", MOON_T), ("mars", ["jezero"])):
        for t in targets:
            job = P.prepare_job(body, t, "base", cfg, e, tp[body][t])
            sc, _, _ = P.base_score(job)
            v1 = pd.read_parquet(V1 / "results" / body / f"{t}__base" / "base_scores.parquet").set_index("tile_id")["score"]
            mine = pd.Series(sc, index=e["tile_id"].to_numpy()[job.gated_rows])
            same_idx = mine.index.equals(v1.index)
            d = float(np.max(np.abs(mine.to_numpy() - v1.reindex(mine.index).to_numpy()))) if same_idx else float("nan")
            res[f"{body}/{t}"] = {"same_tile_set": bool(same_idx), "n": int(len(mine)), "max_abs_diff": d, "ok": bool(same_idx and d <= 1e-3)}
    res["all_ok"] = all(v["ok"] for v in res.values())
    return res


def thermal_sims(e: pd.DataFrame, rows: np.ndarray, body: str, ref: dict, tgt: str) -> tuple[np.ndarray, dict]:
    sims, meta = [], {}
    for c in THERMAL[body]:
        x = e[c].to_numpy(dtype=np.float32)[rows]
        if body == "moon":
            site = ref["moon"]["cols"][c]["sites"][tgt]
        else:
            site = ref["mars"]["jezero"]
        tval, spread = site["rank_median"], site["rank_spread_iqr_1349"]
        sigma = S.sigma_rule(spread, None, S.iqr(x))
        sims.append(S.column_similarity(x, tval, sigma))
        meta[c] = {"target_rank": tval, "target_spread": spread, "sigma": sigma}
    return (np.mean(sims, axis=0).astype(np.float32), meta)


def prep(layer_path: Path, work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    cfg = load_all()
    cfg["known_sites"] = cfg["known_sites"]
    ref = json.load(open(ROOT / "data" / "interim" / "d_ref" / "ref_targets_d.json"))
    e, linfo = load_earth(layer_path)
    tp = target_profiles()
    out = {"layer_info": linfo}
    out["engine_check"] = engine_check(cfg, e, tp)
    units = sites_units(cfg)
    neg = pd.read_csv(ROOT / "runs" / "v2" / "negative_set_d.csv")
    tid_all = e["tile_id"].to_numpy()
    arrays, meta = {}, {}
    for body in ("moon", "mars"):
        base_cols = list(dict.fromkeys(c for f in P.active_body_cfg(cfg["weights"][body], P.drop_columns_for(cfg["run"], body, cfg["weights"][body])).values() for c in f["columns"]))
        gate = G.apply_gates(e, cfg["gates"], base_cols + THERMAL[body], None)
        gate_v1 = G.apply_gates(e, cfg["gates"], base_cols, None)
        rows = np.flatnonzero(gate["passed"].to_numpy())
        meta[f"{body}_universe"] = {"n_U": int(rows.size), "n_v1_gated": int(gate_v1["passed"].sum()),
                                    "rejected_by_reason": {k: int(v) for k, v in gate["reason"].value_counts().items() if k != "ok"}}
        pos_of = np.full(int(tid_all.max()) + 1, -1, np.int64)
        pos_of[tid_all[rows]] = np.arange(rows.size)
        variants = {"moon": [("noill", True), ("ill", False)], "mars": [("base", False)]}[body]
        for vname, drop_ill in variants:
            c2 = cfg_variant(cfg, drop_ill)
            tg = MOON_T if body == "moon" else ["jezero"]
            for t in tg:
                job = P.prepare_job(body, t, "base", c2, e, tp[body][t], gate_df=gate)
                assert np.array_equal(job.gated_rows, rows)
                T, _, _ = P.base_score(job)
                arrays[f"T__{body}__{vname}__{t}"] = T.astype(np.float32)
                meta[f"T__{body}__{vname}__{t}"] = {"profile_weights": job.profile_weights, "columns": job.columns,
                                                   "sigma": job.sigma}
        for t in (MOON_T if body == "moon" else ["jezero"]):
            H, hm = thermal_sims(e, rows, body, ref, t)
            arrays[f"H__{body}__{t}"] = H
            meta[f"H__{body}__{t}"] = hm
        # unit tile positions in U
        upos = {}
        for n, u in units.items():
            upos[n] = int(pos_of[u["tile_id"]]) if 0 <= u["tile_id"] <= tid_all.max() else -1
        for i, tid in enumerate(neg["tile_id"].to_numpy()):
            upos[f"neg{i:03d}"] = int(pos_of[tid])
        meta[f"{body}_unit_pos"] = upos
        # reasons for units outside U
        reasons = {}
        idx_of_tile = pd.Series(np.arange(len(tid_all)), index=tid_all)
        for n, p in upos.items():
            if p >= 0:
                continue
            tid = units[n]["tile_id"] if n in units else int(neg["tile_id"].iloc[int(n[3:])])
            if tid not in idx_of_tile.index:
                reasons[n] = "not a v1 land tile"
            else:
                r = int(idx_of_tile[tid])
                if gate_v1["passed"].to_numpy()[r]:
                    reasons[n] = "thermal value invalid"
                else:
                    reasons[n] = str(gate_v1["reason"].iloc[r])
        meta[f"{body}_unit_unscorable"] = reasons
    out["meta"] = meta
    out["units"] = units
    np.savez(work / "arrays.npz", **arrays)
    json.dump(out, open(work / "prep.json", "w"), indent=1, default=float)
    print(json.dumps({"engine_check": out["engine_check"], "layer_info": linfo,
                      "universe": {b: meta[f"{b}_universe"] for b in ("moon", "mars")}}, indent=1, default=float))


# ----------------------------------------------------------------------------------------------- ranking and metrics

class State:
    """Arrays loaded once per process."""
    def __init__(self, work: Path):
        z = np.load(work / "arrays.npz")
        self.A = {k: z[k] for k in z.files}
        pj = json.load(open(work / "prep.json"))
        self.meta = pj["meta"]
        self.units = pj["units"]
        neg = pd.read_csv(ROOT / "runs" / "v2" / "negative_set_d.csv")
        self.pos_names = [n for n, u in self.units.items() if u["group"] == "pos"]
        self.negsite_names = [n for n, u in self.units.items() if u["group"] == "negsite"]
        self.neg_names = [f"neg{i:03d}" for i in range(len(neg))] + self.negsite_names     # 200 tiles then 2 sites
        self.n_negtile = len(neg)
        self.unit_pos = {b: self.meta[f"{b}_unit_pos"] for b in ("moon", "mars")}
        self.n_moon = self.A[f"H__moon__{MOON_T[0]}"].size
        self.n_mars = self.A["H__mars__jezero"].size
        n_th, n_ter_ill, n_ter_noill, n_ter_mars = 2, 7, 5, 6
        self.g_m1 = {"noill": n_th / (n_th + n_ter_noill), "ill": n_th / (n_th + n_ter_ill), "mars": 1 / (1 + n_ter_mars)}
        self.gs = {"noill": GRID5 + [self.g_m1["noill"]], "ill": GRID5 + [self.g_m1["ill"]], "mars": GRID5 + [self.g_m1["mars"]]}


def unit_ranks(st: State, perm: dict | None) -> dict:
    """Rank percentiles of every unit tile: returns {'moon_noill': (6, nneg) , 'moon_ill': ..., 'mars': (6, npos+nneg)}.
    perm: {'moon': perm array, 'mars': perm array} permuting the thermal rows over U, or None for the real layer."""
    out = {}
    pos_names, neg_names = st.pos_names, st.neg_names
    for key, body, vname, targets in (("moon_noill", "moon", "noill", MOON_T), ("moon_ill", "moon", "ill", MOON_T), ("mars", "mars", "base", ["jezero"])):
        names = neg_names if body == "moon" else pos_names + neg_names
        up = np.array([st.unit_pos[body].get(n, -1) for n in names] if body == "mars" else
                      [st.unit_pos["moon"].get(n, -1) for n in names])
        ok = up >= 0
        gkey = {"moon_noill": "noill", "moon_ill": "ill", "mars": "mars"}[key]
        res = np.full((len(st.gs[gkey]), len(names)), np.nan)
        for ti, t in enumerate(targets):
            T = st.A[f"T__{body}__{vname}__{t}"]
            H = st.A[f"H__{body}__{t}"]
            if perm is not None:
                H = H[perm[body]]
            for gi, g in enumerate(st.gs[gkey]):
                s = (np.float32(1.0 - g) * T + np.float32(g) * np.float32(100.0) * H)
                ss = np.sort(s)
                su = s[up[ok]]
                r = 100.0 * np.searchsorted(ss, su, "left") / ss.size
                if ti == 0:
                    res[gi, ok] = r
                else:
                    res[gi, ok] += r
        if body == "moon":
            res[:, ok] /= len(targets)
        out[key] = res
    return out


def auc(pos: np.ndarray, neg: np.ndarray) -> float:
    pos, neg = pos[np.isfinite(pos)], neg[np.isfinite(neg)]
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    ns = np.sort(neg)
    less = np.searchsorted(ns, pos, "left")
    leq = np.searchsorted(ns, pos, "right")
    return float(np.sum(less + 0.5 * (leq - less)) / (pos.size * neg.size))


def fit_loo(moon: np.ndarray, mars: np.ndarray, npos: int, nneg_tiles: int):
    """moon: (6, nneg_units) Moon ranks; mars: (6, npos + nneg_units). Grid columns 0..4. Returns w index per unit
    (positives first, then negatives), plus w_full. Objective and tie rule as in PREREG_D."""
    fpos = (mars[:5, :npos] >= FLAG["r10"]).astype(float)                     # (5, P), recall10 flags
    sc_pos = np.isfinite(mars[:5, :npos])
    fneg = (moon[:5] >= FLAG["fpr"]).astype(float)                            # (5, N)
    sc_neg = np.isfinite(moon[:5])
    fpos = np.where(sc_pos, fpos, 0.0)
    fneg = np.where(sc_neg, fneg, 0.0)
    kp, kn = sc_pos[0].sum(), sc_neg[0].sum()
    wpos = []
    for p in range(npos):
        if not sc_pos[0, p]:
            wpos.append(None)
            continue
        rec = (fpos.sum(1) - fpos[:, p]) / max(kp - 1, 1)
        fpr = fneg.sum(1) / kn
        wpos.append(int(np.argmax(np.round(0.5 * rec + 0.5 * (1 - fpr), 12))))
    wneg = []
    for n in range(moon.shape[1]):
        if not sc_neg[0, n]:
            wneg.append(None)
            continue
        rec = fpos.sum(1) / kp
        fpr = (fneg.sum(1) - fneg[:, n]) / max(kn - 1, 1)
        wneg.append(int(np.argmax(np.round(0.5 * rec + 0.5 * (1 - fpr), 12))))
    full = int(np.argmax(np.round(0.5 * fpos.sum(1) / kp + 0.5 * (1 - fneg.sum(1) / kn), 12)))
    return wpos, wneg, full


def evaluate(st: State, ranks: dict, variant: str, keep: dict | None = None) -> dict:
    """All metrics for M0..M3 of one Moon variant ('noill' or 'ill'). Flat dict of floats."""
    moon = ranks[f"moon_{variant}"]
    mars = ranks["mars"]
    npos = len(st.pos_names)
    nn = len(st.neg_names)
    mars_pos, mars_neg = mars[:, :npos], mars[:, npos:]
    iN, iR = st.neg_names.index("namib_sand_sea"), st.neg_names.index("rub_al_khali")
    out: dict = {}
    wpos, wneg, wfull = fit_loo(moon, mars, npos, st.n_negtile)

    def put(m, moon_r, mars_p, mars_n, tag=""):
        # moon_r (nn,), mars_p (npos,), mars_n (nn,)
        sc = np.isfinite(moon_r)
        k = int(sc.sum())
        fl = (moon_r >= FLAG["fpr"]) & sc
        out[f"{m}{tag}.fpr25_moon_all"] = fl.sum() / k if k else np.nan
        out[f"{m}{tag}.fpr25_moon_all.n"] = k
        sct = sc[:st.n_negtile]
        out[f"{m}{tag}.fpr25_moon_tiles"] = fl[:st.n_negtile].sum() / sct.sum() if sct.sum() else np.nan
        out[f"{m}{tag}.fpr25_moon_tiles.n"] = int(sct.sum())
        out[f"{m}{tag}.namib_rank"] = moon_r[iN]
        out[f"{m}{tag}.rub_rank"] = moon_r[iR]
        ps = np.isfinite(mars_p)
        kp = int(ps.sum())
        for q, key in ((5, "r5"), (10, "r10"), (25, "r25")):
            hit = ((mars_p >= FLAG[key]) & ps).sum()
            out[f"{m}{tag}.recall{q}"] = hit / kp if kp else np.nan
            out[f"{m}{tag}.recall{q}.hits"] = int(hit)
            out[f"{m}{tag}.recall{q}_all6"] = hit / npos
        out[f"{m}{tag}.recall.n"] = kp
        out[f"{m}{tag}.mars_primary_median"] = float(np.median(mars_p[ps])) if kp else np.nan
        out[f"{m}{tag}.auc_mars"] = auc(mars_p, mars_n)
        for pi, pn in enumerate(st.pos_names):
            out[f"{m}{tag}.rank_mars.{pn}"] = mars_p[pi]
        if keep is not None:
            keep[f"{m}{tag}"] = (np.array(mars_p), np.array(mars_n))
        ms = np.isfinite(mars_n)
        out[f"{m}{tag}.fpr25_mars_all"] = (((mars_n >= FLAG["fpr"]) & ms).sum() / ms.sum()) if ms.sum() else np.nan

    for mi, m in ((0, "M0"), (5, "M1"), (2, "M2")):
        put(m, moon[mi], mars_pos[mi], mars_neg[mi])
    # M3 held-out: each unit scored under the w chosen without it
    kp = sum(w is not None for w in wpos)
    if kp >= 2:
        mp = np.array([mars_pos[w, p] if w is not None else np.nan for p, w in enumerate(wpos)])
        moon_r = np.array([moon[w, n] if w is not None else np.nan for n, w in enumerate(wneg)])
        mars_n = np.array([mars_neg[w, n] if w is not None else np.nan for n, w in enumerate(wneg)])
        # negatives that are scorable under Mars only: use the fit w from the full set
        for n in range(nn):
            if wneg[n] is None and np.isfinite(mars_neg[wfull, n]):
                mars_n[n] = mars_neg[wfull, n]
        put("M3", moon_r, mp, mars_n)
        # in-sample (never used for a gate)
        put("M3", moon[wfull], mars_pos[wfull], mars_neg[wfull], tag="_insample")
        out["M3.w_full"] = GRID5[wfull]
        ws = [w for w in wpos + wneg if w is not None]
        for gi, g in enumerate(GRID5):
            out[f"M3.n_folds_w{g}"] = sum(1 for w in ws if w == gi)
    else:
        out["M3.not_tested"] = 1.0
    return out


def run_real(work: Path) -> None:
    st = State(work)
    ranks = unit_ranks(st, None)
    np.savez(work / "ranks_real.npz", **ranks)
    keep: dict = {}
    res = {v: evaluate(st, ranks, v, keep if v == "noill" else None) for v in ("noill", "ill")}
    rng = np.random.default_rng(SEED)
    boot = {}
    for m, (pp, nn_) in keep.items():
        pp, nn_ = pp[np.isfinite(pp)], nn_[np.isfinite(nn_)]
        if pp.size == 0 or nn_.size == 0:
            continue
        a = [auc(rng.choice(pp, pp.size), rng.choice(nn_, nn_.size)) for _ in range(1000)]
        boot[m] = {"lo": float(np.percentile(a, 2.5)), "hi": float(np.percentile(a, 97.5)), "n_pos": int(pp.size), "n_neg": int(nn_.size)}
    res["auc_bootstrap_95"] = boot
    json.dump(res, open(work / "real_metrics.json", "w"), indent=1, default=float)
    print(json.dumps({k: v for k, v in res["noill"].items() if k.startswith(("M0.", "M1.", "M2.", "M3.")) and "insample" not in k and ("fpr25_moon_all" in k or "recall10" in k or "auc" in k)}, indent=1, default=float))
    print(json.dumps(boot))


# ----------------------------------------------------------------------------------------------- shuffle

_ST: State | None = None


def _init(work: str) -> None:
    global _ST
    _ST = State(Path(work))


def _draw(d: int) -> dict:
    st = _ST
    perm = {}
    for body, n in (("moon", st.n_moon), ("mars", st.n_mars)):
        rng = np.random.default_rng([SEED, d, 0 if body == "moon" else 1])
        perm[body] = rng.permutation(n)
    r = unit_ranks(st, perm)
    return {v: evaluate(st, r, v) for v in ("noill", "ill")}


def run_shuffle(work: Path, ndraws: int, nproc: int) -> None:
    t0 = time.time()
    rows = {"noill": [], "ill": []}
    with ProcessPoolExecutor(max_workers=nproc, initializer=_init, initargs=(str(work),)) as ex:
        for i, r in enumerate(ex.map(_draw, range(ndraws), chunksize=4)):
            for v in rows:
                rows[v].append(r[v])
            if i % 50 == 0:
                print(f"draw {i} {time.time() - t0:.0f}s", flush=True)
    out = {}
    for v in rows:
        df = pd.DataFrame(rows[v])
        out[v] = {}
        for c in df.columns:
            x = df[c].to_numpy(dtype=float)
            x = x[np.isfinite(x)]
            out[v][c] = ({"min": float(x.min()), "median": float(np.median(x)), "max": float(x.max()), "n_draws": int(x.size)}
                         if x.size else {"min": None, "median": None, "max": None, "n_draws": 0})
    json.dump(out, open(work / "shuffle_baseline.json", "w"), indent=1)
    print("done", ndraws, "draws", f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    stage = sys.argv[1]
    if stage == "prep":
        prep(Path(sys.argv[2]), Path(sys.argv[3]))
    elif stage == "real":
        run_real(Path(sys.argv[2]))
    elif stage == "shuffle":
        run_shuffle(Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
