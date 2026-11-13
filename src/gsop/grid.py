"""Equal-area tile grid, EPSG:6933, 6000 m cells (D1). Cell (ix, iy): ix east from x0, iy south from y_top."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# EPSG:6933 projected extent in metres, from pyproj: x at lon 180 / lat 0, y at lat 90.
# The standard EASE-Grid 2.0 rows stop at 85.04 deg latitude (y 7314540.83); we use the full pole-to-pole
# extent so no land is silently dropped. Cells above 85 deg are polar ice and are gated out anyway.
X_MAX = 17_367_530.445161372
Y_MAX = 7_342_230.136498678


@dataclass(frozen=True)
class Grid:
    cell_m: float = 6000.0
    crs: str = "EPSG:6933"

    @property
    def x0(self) -> float:
        return -X_MAX

    @property
    def y_top(self) -> float:
        return Y_MAX

    @property
    def ncols(self) -> int:
        return math.ceil(2 * X_MAX / self.cell_m)

    @property
    def nrows(self) -> int:
        return math.ceil(2 * Y_MAX / self.cell_m)

    def tile_id(self, ix, iy):
        return np.asarray(iy, dtype=np.int64) * self.ncols + np.asarray(ix, dtype=np.int64)

    def split_id(self, tid):
        tid = np.asarray(tid, dtype=np.int64)
        return tid % self.ncols, tid // self.ncols

    def centre_xy(self, ix, iy):
        ix, iy = np.asarray(ix, float), np.asarray(iy, float)
        return self.x0 + (ix + 0.5) * self.cell_m, self.y_top - (iy + 0.5) * self.cell_m

    def centre_lonlat(self, ix, iy):
        from pyproj import Transformer
        x, y = self.centre_xy(ix, iy)
        tr = Transformer.from_crs(self.crs, "EPSG:4326", always_xy=True)
        lon, lat = tr.transform(x, y)
        return np.asarray(lon), np.asarray(lat)

    def cell_of_lonlat(self, lon, lat):
        from pyproj import Transformer
        tr = Transformer.from_crs("EPSG:4326", self.crs, always_xy=True)
        x, y = tr.transform(lon, lat)
        ix = np.floor((np.asarray(x) - self.x0) / self.cell_m).astype(np.int64)
        iy = np.floor((self.y_top - np.asarray(y)) / self.cell_m).astype(np.int64)
        return ix, iy


def wrap_lon(lon_e):
    """Degrees east 0..360 to -180..180."""
    return (np.asarray(lon_e, float) + 180.0) % 360.0 - 180.0


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
