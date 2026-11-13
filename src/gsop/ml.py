"""ML second opinion (D9). The ML never produces the score.

(a) Terrain archetypes: k-means on standardised gated Earth tiles, k by silhouette on a sample; reports the archetype
    of each primary site and of each robust tile.
(b) Classifier (logistic regression and a small random forest): primary known sites vs random gated tiles,
    leave-one-site-out, spatial-block rule (tiles within block_km of the held-out site are excluded from training).
    There are very few positives. The result says so, and says "no added signal" unless it earns otherwise.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from .grid import haversine_km


def _site_tiles(lat, lon, site, radius_km):
    return np.flatnonzero(haversine_km(site["lat"], site["lon"], lat, lon) <= radius_km)


def archetypes(Z: np.ndarray, lat, lon, sites: dict[str, dict], robust_idx: np.ndarray, radius_km: float,
               seed: int = 0, k_range=range(3, 9), sample: int = 20_000) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(Z), size=min(sample, len(Z)), replace=False)
    best_k, best_s = None, -1.0
    sil_idx = idx[:min(5000, len(idx))]
    for k in k_range:
        km = KMeans(n_clusters=k, n_init=3, random_state=seed).fit(Z[idx])
        s = silhouette_score(Z[sil_idx], km.predict(Z[sil_idx]))
        if s > best_s:
            best_k, best_s = k, s
    km = KMeans(n_clusters=best_k, n_init=5, random_state=seed).fit(Z[idx])
    lab = km.predict(Z)
    site_lab = {}
    for n, s in sites.items():
        t = _site_tiles(lat, lon, s, radius_km)
        site_lab[n] = int(np.bincount(lab[t]).argmax()) if t.size else None
    rob = np.bincount(lab[robust_idx], minlength=best_k).tolist() if robust_idx.size else [0] * best_k
    return {"k": int(best_k), "silhouette": float(best_s), "site_archetype": site_lab,
            "robust_tiles_per_archetype": rob, "archetype_sizes": np.bincount(lab, minlength=best_k).tolist()}


def classifier(Z: np.ndarray, lat, lon, sites: dict[str, dict], cols: list[str], base_score: np.ndarray,
               site_radius_km: float, block_km: float, n_neg: int, seed: int = 0,
               min_sites: int = 3, min_mean_auc: float = 0.6) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    pos = {n: _site_tiles(lat, lon, s, site_radius_km) for n, s in sites.items()}
    pos = {n: t for n, t in pos.items() if t.size}
    out: dict[str, Any] = {"n_sites_with_tiles": len(pos),
                           "n_positive_tiles": {n: int(t.size) for n, t in pos.items()},
                           "caveat": f"Only {len(pos)} positive sites. Treat every number below as weak."}
    if len(pos) < 2:
        out.update({"added_signal": False, "verdict": "no added signal: fewer than 2 positive sites on the grid"})
        return out
    all_pos = np.concatenate(list(pos.values()))
    d_any = np.min(np.stack([haversine_km(sites[n]["lat"], sites[n]["lon"], lat, lon) for n in pos]), axis=0)
    neg_pool = np.flatnonzero(d_any > block_km)
    test_neg = rng.choice(neg_pool, size=min(n_neg, neg_pool.size), replace=False)
    train_pool = np.setdiff1d(neg_pool, test_neg)
    aucs: dict[str, Any] = {}
    for held, t_pos in pos.items():
        d_held = haversine_km(sites[held]["lat"], sites[held]["lon"], lat, lon)
        tr_pos = np.concatenate([t for n, t in pos.items() if n != held])
        tr_neg_pool = train_pool[d_held[train_pool] > block_km]
        tr_neg = rng.choice(tr_neg_pool, size=min(n_neg, tr_neg_pool.size), replace=False)
        Xtr = np.vstack([Z[tr_pos], Z[tr_neg]])
        ytr = np.r_[np.ones(len(tr_pos)), np.zeros(len(tr_neg))]
        Xte = np.vstack([Z[t_pos], Z[test_neg]])
        yte = np.r_[np.ones(len(t_pos)), np.zeros(len(test_neg))]
        res = {}
        for name, mdl in (("logreg", LogisticRegression(max_iter=1000, class_weight="balanced")),
                          ("rf", RandomForestClassifier(n_estimators=200, max_depth=6, class_weight="balanced",
                                                        random_state=seed, n_jobs=1))):
            mdl.fit(Xtr, ytr)
            res[name] = float(roc_auc_score(yte, mdl.predict_proba(Xte)[:, 1]))
        aucs[held] = res
    mean_auc = {m: float(np.mean([a[m] for a in aucs.values()])) for m in ("logreg", "rf")}
    # full model for importances and the correlation with the index
    neg_all = rng.choice(neg_pool, size=min(n_neg, neg_pool.size), replace=False)
    Xf = np.vstack([Z[all_pos], Z[neg_all]])
    yf = np.r_[np.ones(len(all_pos)), np.zeros(len(neg_all))]
    rf = RandomForestClassifier(n_estimators=200, max_depth=6, class_weight="balanced", random_state=seed,
                                n_jobs=1).fit(Xf, yf)
    lr = LogisticRegression(max_iter=1000, class_weight="balanced").fit(Xf, yf)
    samp = rng.choice(len(Z), size=min(50_000, len(Z)), replace=False)
    rho = {"rf": float(spearmanr(rf.predict_proba(Z[samp])[:, 1], base_score[samp]).statistic),
           "logreg": float(spearmanr(lr.predict_proba(Z[samp])[:, 1], base_score[samp]).statistic)}
    signal = len(pos) >= min_sites and max(mean_auc.values()) >= min_mean_auc
    out.update({"loso_auc": aucs, "mean_auc": mean_auc, "feature_importance_rf": dict(zip(cols, rf.feature_importances_.tolist())),
                "spearman_with_index": rho, "added_signal": bool(signal),
                "verdict": ("classifier agrees with a signal above the threshold" if signal else
                            "no added signal: too few positive sites or mean leave-one-site-out AUC below threshold")})
    return out


def run_ml(X: np.ndarray, cols: list[str], lat: np.ndarray, lon: np.ndarray, base_score: np.ndarray,
           robust_idx: np.ndarray, sites: dict[str, dict], ml_cfg: dict[str, Any], seed: int = 0) -> dict[str, Any]:
    Z = StandardScaler().fit_transform(X.T.astype(np.float64))
    return {"archetypes": archetypes(Z, lat, lon, sites, robust_idx, ml_cfg["site_radius_km"], seed),
            "classifier": classifier(Z, lat, lon, sites, cols, base_score, ml_cfg["site_radius_km"],
                                     ml_cfg["block_km"], ml_cfg["n_negatives"], seed,
                                     ml_cfg["min_sites_for_signal"], ml_cfg["min_mean_auc"]),
            "role": "second opinion only; never produces the score"}
