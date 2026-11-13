"""Discovery (s9, minimal): robust tiles far from every known site. Write-ups, zooms and process tags are done by people."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .grid import haversine_km


def known_points(ks: dict[str, Any], body: str) -> list[tuple[str, float, float]]:
    pts = []
    for grp in ("primary", "secondary"):
        for n, s in ks[grp].items():
            pts.append((f"{grp}/{n}", s["lat"], s["lon"]))
    return pts


def discover(mc_summary: pd.DataFrame, ks: dict[str, Any], body: str, min_km: float, top_n: int,
             family_scores: pd.DataFrame | None, gate_margins: pd.DataFrame | None) -> pd.DataFrame:
    """mc_summary: candidates with lat, lon, robust, mc_median. family_scores: per-tile w_f*S_f contributions
    (columns = family names), indexed by tile_id. gate_margins: per-tile closeness to each gate threshold."""
    c = mc_summary[mc_summary["robust"]].copy()
    if c.empty:
        return c
    pts = known_points(ks, body)
    dmin = np.full(len(c), np.inf)
    nearest = [""] * len(c)
    for name, la, lo in pts:
        d = haversine_km(la, lo, c["lat"].to_numpy(), c["lon"].to_numpy())
        upd = d < dmin
        dmin = np.where(upd, d, dmin)
        nearest = [name if u else n for u, n in zip(upd, nearest)]
    c["nearest_known_site"], c["nearest_known_km"] = nearest, dmin
    c = c[c["nearest_known_km"] > min_km].sort_values("mc_median", ascending=False).head(top_n).copy()
    if family_scores is not None and not c.empty:
        contrib = family_scores.reindex(c["tile_id"])
        c["top_drivers"] = [", ".join(contrib.iloc[i].sort_values(ascending=False).index[:2])
                            for i in range(len(c))]
    if gate_margins is not None and not c.empty:
        gm = gate_margins.reindex(c["tile_id"])
        c["close_gates"] = [", ".join(gm.columns[(gm.iloc[i] > 0.8).to_numpy()]) for i in range(len(c))]
    c["process_tag"] = ""        # impact, volcanic, aeolian, periglacial, evaporite: filled by a person
    return c


def gate_margin_table(earth: pd.DataFrame, gates_cfg: dict[str, Any]) -> pd.DataFrame:
    """Share of each gate threshold used by the tile (1.0 = exactly at the threshold). Above 0.8 = close."""
    g = gates_cfg["tile_gates"]
    out = pd.DataFrame({
        "water_ice": earth["water_ice_frac"] / g["open_water_or_ice_frac_max"],
        "ndvi": earth["ndvi_median"].clip(lower=0) / g["ndvi_median_max"],
        "built_crop": earth["built_crop_frac"] / g["built_or_crop_frac_max"],
    })
    out.index = earth["tile_id"].to_numpy()
    return out
