"""Latitude-only solar geometry for Earth tiles: sun_max_elev, sun_low_share, insol_annual.

These three columns are computed, not measured. DEVIATION from SPEC section 3 ("from latitude, obliquity, slope and
aspect"): this version uses latitude and obliquity only, a flat horizon and a circular orbit. Slope and aspect are not
used. Elevation of the Sun: sin(h) = sin(lat) sin(dec) + cos(lat) cos(dec) cos(H), with dec the solar declination
over the year (obliquity from config, uniform in solar longitude) and H the hour angle sampled every 5 minutes.
  sun_max_elev   highest Sun elevation over the year (deg)
  sun_low_share  share of daylight samples (h > 0) with the Sun under `sun_low_threshold_deg` (5 deg in config)
  insol_annual   annual mean top-of-atmosphere irradiance on a horizontal surface, S0 * max(sin h, 0) averaged over all
                 samples, S0 from config (1361 W/m2; no atmosphere, no eccentricity). Mars also has no thick atmosphere, which is why
                 this is used for the Mars `sunlight` family.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def sun_features(lat_deg, cfg: dict[str, Any] | None = None) -> dict[str, np.ndarray]:
    """cfg is the `features` config (config/features.yaml): `solar` (obliquity_deg, s0_w_m2, n_days, n_hours) and
    `sun_low_threshold_deg`. Nothing is hard-coded here."""
    if cfg is None:
        from ..config import load_all
        cfg = load_all()["features"]
    sol = cfg["solar"]
    obliq, s0, n_days, n_hours = float(sol["obliquity_deg"]), float(sol["s0_w_m2"]), int(sol["n_days"]), int(sol["n_hours"])
    low_deg = float(cfg["sun_low_threshold_deg"])
    lat = np.atleast_1d(np.asarray(lat_deg, dtype=np.float64))
    uniq, inv = np.unique(np.round(lat, 4), return_inverse=True)
    lam = 2 * np.pi * (np.arange(n_days) + 0.5) / n_days
    dec = np.arcsin(np.sin(np.radians(obliq)) * np.sin(lam))[:, None]            # (days, 1)
    hh = 2 * np.pi * (np.arange(n_hours) + 0.5) / n_hours                                  # (hours,)
    cosH = np.cos(hh)[None, :]
    mx, lo, ins = (np.empty(uniq.size) for _ in range(3))
    for i, phi in enumerate(np.radians(uniq)):
        sin_h = np.sin(phi) * np.sin(dec) + np.cos(phi) * np.cos(dec) * cosH             # (days, hours)
        h = np.degrees(np.arcsin(np.clip(sin_h, -1.0, 1.0)))
        day = h > 0
        mx[i] = h.max()
        n_day = day.sum()
        lo[i] = ((h > 0) & (h < low_deg)).sum() / n_day if n_day else np.nan
        ins[i] = s0 * np.clip(sin_h, 0.0, None).mean()
    return {"sun_max_elev": mx[inv].reshape(lat.shape), "sun_low_share": lo[inv].reshape(lat.shape),
            "insol_annual": ins[inv].reshape(lat.shape)}
