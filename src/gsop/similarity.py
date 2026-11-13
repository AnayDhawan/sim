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


def sigma_terms(target_spread: float | None, measurement_unc: float | None, iqr_earth: float) -> dict[str, float | str]:
    """The three terms of the sigma rule, the resulting sigma and which term binds (ties go to the first listed)."""
    spread = float(target_spread) if target_spread is not None and np.isfinite(target_spread) else None
    meas = float(measurement_unc) if measurement_unc is not None and np.isfinite(measurement_unc) else None
    iq = IQR_FACTOR * iqr_earth
    cand = {"target_spread": spread if spread is not None else 0.0, "measurement_uncertainty": meas if meas is not None else 0.0,
            "iqr_floor": iq}
    sigma = sigma_rule(target_spread, measurement_unc, iqr_earth)
    binding = next((k for k, v in cand.items() if v == max(cand.values())), "iqr_floor") if max(cand.values()) > SIGMA_MIN \
        else "minimum"
    return {"target_spread": spread, "measurement_uncertainty": meas, "iqr_earth": float(iqr_earth),
            "iqr_floor": float(iq), "sigma": float(sigma), "binding": binding}


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
    """100 * sum_f w_f * S_f. A family with weight 0 is skipped, so NaN in an unused family does not poison the tile.
    NaN in a used family gives a NaN score: the tile is missing, never scored as if the value were 0."""
    acc = None
    for f, s in fam.items():
        w = weights.get(f, 0.0)
        if w == 0.0:
            continue
        acc = s * np.float32(w) if acc is None else acc + s * np.float32(w)
    if acc is None:
        raise ValueError("all family weights are zero")
    out = np.float32(100.0) * acc
    np.minimum(out, np.float32(100.0), out=out)       # float32 rounding of weights that sum to 1 can give 100.00001
    return out


def score_block(X: np.ndarray, col_index: Mapping[str, int], fam_cols: Mapping[str, list[str]],
                weights: Mapping[str, float], target: Mapping[str, float], sigma: Mapping[str, float],
                return_families: bool = False):
    """The one scoring function, for a single run and for the Monte Carlo inner loop.

    X: (n_cols, n) array, row `col_index[c]` is column c (a slice of a chunk is fine). `weights` and `target` are
    arguments, so the Monte Carlo passes the per-run draw and jittered target and a single run passes the derived
    weights and the target profile. Returns float32 scores (n,), and with `return_families=True` also the dict of
    per-family similarities (needed for "which features drive the match" and illumination_match).
    NaN in any used column marks the tile missing (NaN score); `valid_mask` says which tiles are scored."""
    fam = family_scores({c: X[col_index[c]] for cols in fam_cols.values() for c in cols}, target, sigma, fam_cols)
    score = tile_score(fam, weights)
    return (score, fam) if return_families else score


def valid_mask(score: np.ndarray) -> np.ndarray:
    """True where the tile has a score (no NaN in any used column)."""
    return np.isfinite(score)


def throughput(n_tiles: int = 1_000_000, n_cols: int = 15, seed: int = 0, repeats: int = 3) -> dict[str, float]:
    """Tiles scored per second on one core (this process), best of `repeats`, on uniform random float32 data with the
    columns split into families of two."""
    import time
    rng = np.random.default_rng(seed)
    X = rng.random((n_cols, n_tiles), dtype=np.float32)
    cols = [f"c{i}" for i in range(n_cols)]
    idx = {c: i for i, c in enumerate(cols)}
    fam_cols = {f"f{i // 2}": cols[i:i + 2] for i in range(0, n_cols, 2)}
    w = {f: 1.0 / len(fam_cols) for f in fam_cols}
    t = {c: 0.5 for c in cols}
    sg = {c: 0.2 for c in cols}
    best = float("inf")
    for _ in range(repeats):
        t0 = time.perf_counter()
        score_block(X, idx, fam_cols, w, t, sg)
        best = min(best, time.perf_counter() - t0)
    return {"n_tiles": n_tiles, "n_cols": n_cols, "seconds": best, "tiles_per_second": n_tiles / best}
