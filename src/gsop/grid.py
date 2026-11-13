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
        """Centre of the part of the cell inside the projection's domain. The grid is 5789.18 cells wide and 2447.4
        high, so the last column and the last row are partial (about 1.1 km and 2.4 km); their centres are the centres
        of the slivers, not points beyond the antimeridian or the pole."""
        ix, iy = np.asarray(ix, float), np.asarray(iy, float)
        xa = self.x0 + ix * self.cell_m
        ya = self.y_top - iy * self.cell_m
        xb = np.minimum(xa + self.cell_m, X_MAX)
        yb = np.maximum(ya - self.cell_m, -Y_MAX)
        return (xa + xb) / 2.0, (ya + yb) / 2.0

    def centre_lonlat(self, ix, iy):
        from pyproj import Transformer
        x, y = self.centre_xy(ix, iy)
        tr = Transformer.from_crs(self.crs, "EPSG:4326", always_xy=True)
        lon, lat = tr.transform(x, y)
        return np.asarray(lon), np.asarray(lat)

    def cell_of_lonlat(self, lon, lat):
        """Cell (ix, iy) containing each point. lon 180 and lat -90 fall on the last column and row, lat 90 on row 0;
        lon -180 and lon 180 are the two ends of the same meridian and land in the first and the last column."""
        from pyproj import Transformer
        tr = Transformer.from_crs("EPSG:4326", self.crs, always_xy=True)
        x, y = tr.transform(lon, lat)
        ix = np.floor((np.asarray(x) - self.x0) / self.cell_m).astype(np.int64)
        iy = np.floor((self.y_top - np.asarray(y)) / self.cell_m).astype(np.int64)
        return np.clip(ix, 0, self.ncols - 1), np.clip(iy, 0, self.nrows - 1)

    def tile_of_lonlat(self, lon, lat):
        """lonlat -> tile_id (int64)."""
        return self.tile_id(*self.cell_of_lonlat(lon, lat))

    def centre_of_tile(self, tid):
        """tile_id -> (lon, lat) of the tile centre."""
        return self.centre_lonlat(*self.split_id(tid))

    def polygon(self, tid):
        """Shapely polygon of one tile in the grid CRS (metres), built on demand. The last column and row are clipped to
        the projection domain, so they are smaller than 6 km x 6 km."""
        from shapely.geometry import box
        ix, iy = (int(v) for v in self.split_id(tid))
        x0, x1 = self.x0 + ix * self.cell_m, min(self.x0 + (ix + 1) * self.cell_m, X_MAX)
        y1, y0 = self.y_top - iy * self.cell_m, max(self.y_top - (iy + 1) * self.cell_m, -Y_MAX)
        return box(x0, y0, x1, y1)

    def describe(self) -> dict:
        """The grid definition written to grid.json: CRS, cell size, origin, extent and cell count."""
        return {"crs": self.crs, "cell_m": self.cell_m, "ncols": self.ncols, "nrows": self.nrows, "x0": self.x0,
                "y_top": self.y_top, "x_extent_m": 2 * X_MAX, "y_extent_m": 2 * Y_MAX,
                "n_cells": self.ncols * self.nrows,
                "origin": "x0 = -X_MAX (lon -180), y_top = Y_MAX (lat +90) of EPSG:6933; cell (ix, iy) grows east and south",
                "tile_id": "iy * ncols + ix (int64); inverse: ix = tile_id % ncols, iy = tile_id // ncols"}


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
