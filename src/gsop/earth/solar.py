"""Latitude-only solar geometry for Earth tiles: sun_max_elev, sun_low_share, insol_annual.

These three columns are computed, not measured. DEVIATION from SPEC section 3 ("from latitude, obliquity, slope and
aspect"): this version uses latitude and obliquity only, a flat horizon and a circular orbit. Slope and aspect are not
used. Elevation of the Sun: sin(h) = sin(lat) sin(dec) + cos(lat) cos(dec) cos(H), with dec the solar declination
over the year (obliquity 23.44 deg, uniform in solar longitude) and H the hour angle sampled every 5 minutes.
  sun_max_elev   highest Sun elevation over the year (deg)
  sun_low_share  share of daylight samples (h > 0) with the Sun under `low_deg` (default 5 deg)
  insol_annual   annual mean top-of-atmosphere irradiance on a horizontal surface, S0 * max(sin h, 0) averaged over all
                 samples, S0 = 1361 W/m2 (no atmosphere, no eccentricity). Mars also has no thick atmosphere, which is why
                 this is used for the Mars `sunlight` family.
"""

from __future__ import annotations

import numpy as np

OBLIQUITY_DEG = 23.44
S0 = 1361.0


def sun_features(lat_deg, low_deg: float = 5.0, n_days: int = 365, n_hours: int = 288) -> dict[str, np.ndarray]:
    lat = np.atleast_1d(np.asarray(lat_deg, dtype=np.float64))
    uniq, inv = np.unique(np.round(lat, 4), return_inverse=True)
    lam = 2 * np.pi * (np.arange(n_days) + 0.5) / n_days
    dec = np.arcsin(np.sin(np.radians(OBLIQUITY_DEG)) * np.sin(lam))[:, None]            # (days, 1)
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
        ins[i] = S0 * np.clip(sin_h, 0.0, None).mean()
    return {"sun_max_elev": mx[inv].reshape(lat.shape), "sun_low_share": lo[inv].reshape(lat.shape),
            "insol_annual": ins[inv].reshape(lat.shape)}
