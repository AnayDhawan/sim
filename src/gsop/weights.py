"""Family weights: derivation, purpose multipliers, Monte Carlo draws, alternative sets."""

from __future__ import annotations

from typing import Any

import numpy as np


def families(body_cfg: dict[str, Any]) -> list[str]:
    return list(body_cfg.keys())


def derive_weights(body_cfg: dict[str, Any]) -> dict[str, float]:
    """derived = (paper_score / sum(paper_score)) * matchability, rescaled to sum 1."""
    tot = sum(f["paper_score"] for f in body_cfg.values())
    raw = {k: f["paper_score"] / tot * f["matchability"] for k, f in body_cfg.items()}
    s = sum(raw.values())
    return {k: v / s for k, v in raw.items()}


def check_against_published(body_cfg: dict[str, Any], tol: float) -> dict[str, float]:
    """Absolute difference derived vs published per family. Caller compares with tol."""
    d = derive_weights(body_cfg)
    return {k: abs(d[k] - body_cfg[k]["published"]) for k in d}


def normalise(w: dict[str, float]) -> dict[str, float]:
    s = sum(w.values())
    if s <= 0:
        raise ValueError("weights sum to zero")
    return {k: v / s for k, v in w.items()}


def profile_multipliers(purposes_cfg: dict[str, Any], profile: str, body: str) -> dict[str, float]:
    if profile == "base":
        return {}
    if profile not in purposes_cfg["profiles"][body]:
        raise ValueError(f"profile {profile!r} is not defined for {body}")
    p = purposes_cfg["purposes"][profile]
    return {k: float(v) for k, v in p["multipliers"].items()}


def apply_multipliers(w: dict[str, float], mult: dict[str, float]) -> dict[str, float]:
    return normalise({k: v * mult.get(k, 1.0) for k, v in w.items()})


def profile_weights(body_cfg: dict[str, Any], purposes_cfg: dict[str, Any], profile: str, body: str) -> dict[str, float]:
    return apply_multipliers(derive_weights(body_cfg), profile_multipliers(purposes_cfg, profile, body))


def draw_weights(rng: np.random.Generator, ranges: dict[str, tuple[float, float]],
                 mult: dict[str, float], return_raw: bool = False):
    """Draw each family weight uniformly within its range (one scalar per family, in `ranges` order), renormalise to
    sum 1, apply the purpose multipliers (a missing one is 1), renormalise again. `return_raw=True` also returns the
    raw draws, before any renormalisation."""
    u = {k: float(rng.uniform(lo, hi)) for k, (lo, hi) in ranges.items()}
    w = apply_multipliers(normalise(u), mult)
    return (w, u) if return_raw else w


def alt_weight_sets(body: str, weights_cfg: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Alternative weight sets (primary base weights are the reference). Families not listed get weight 0."""
    body_cfg = weights_cfg[body]
    base = derive_weights(body_cfg)
    out: dict[str, dict[str, float]] = {}
    for name, spec in weights_cfg["alt_weight_sets"][body].items():
        if "weights" in spec:
            w = {k: float(spec["weights"].get(k, 0.0)) for k in body_cfg}
            out[name] = normalise(w)
        elif name == "no_illumination":
            w = dict(base)
            for fam in ("illumination", "sunlight"):
                if fam in w:
                    w[fam] = 0.0
            out[name] = normalise(w)
        elif name == "equal":
            out[name] = {k: 1.0 / len(body_cfg) for k in body_cfg}
        else:
            raise ValueError(f"unknown alt weight rule {name!r}")
    return out
