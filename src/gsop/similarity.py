"""Per-column similarity, family scores and tile scores.

s_k = exp(-0.5 * ((x_tile - x_target) / sigma_k)^2), in [0, 1].
Family score = mean of its columns' similarities. Tile score = 100 * sum_f w_f * S_f.
sigma_k = max(target_spread_k, measurement_uncertainty_k, 0.25 * IQR_of_k_across_all_gated_Earth_tiles).
The IQR term stops the score collapsing to zero everywhere for variables Earth cannot match.
"""

from __future__ import annotations

from typing import Mapping

import numpy as np

SIGMA_MIN = 1e-9
IQR_FACTOR = 0.25


def iqr(x: np.ndarray) -> float:
    q75, q25 = np.nanpercentile(x, [75, 25])
    return float(q75 - q25)


def sigma_rule(target_spread: float | None, measurement_unc: float | None, iqr_earth: float) -> float:
    vals = [v for v in (target_spread, measurement_unc) if v is not None and np.isfinite(v)]
    vals.append(IQR_FACTOR * iqr_earth)
    return max(max(vals), SIGMA_MIN)


def column_similarity(x: np.ndarray, t: float, sigma: float) -> np.ndarray:
    x32 = np.asarray(x, dtype=np.float32)
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        z = (x32 - np.float32(t)) / np.float32(sigma)
        return np.exp(np.float32(-0.5) * z * z)


def family_scores(X: Mapping[str, np.ndarray], target: Mapping[str, float], sigma: Mapping[str, float],
                  fam_cols: Mapping[str, list[str]]) -> dict[str, np.ndarray]:
    out = {}
    for fam, cols in fam_cols.items():
        acc = None
        for c in cols:
            s = column_similarity(X[c], target[c], sigma[c])
            acc = s if acc is None else acc + s
        out[fam] = acc / np.float32(len(cols))
    return out


def tile_score(fam: Mapping[str, np.ndarray], weights: Mapping[str, float]) -> np.ndarray:
    acc = None
    for f, s in fam.items():
        w = weights.get(f, 0.0)
        if w == 0.0:
            continue
        acc = s * np.float32(w) if acc is None else acc + s * np.float32(w)
    if acc is None:
        raise ValueError("all family weights are zero")
    return np.float32(100.0) * acc
