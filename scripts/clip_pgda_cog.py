"""Clip a square around the lunar south pole out of a remote PGDA cloud-optimised GeoTIFF, by HTTP range requests.

The full LOLA 20 m south-polar files are 2.7 GB (DEM) and 154 MB (PSR map) and the PGDA server gave about 100 KB/s, so only
the part the Moon targets use is taken. Pixels are copied unchanged (no resampling), with the source CRS, the source pixel
grid, dtype, nodata and tags. Both targets' 17 km reads lie inside a 32 km half-width box (docs/PROVENANCE.md).

    uv run python scripts/clip_pgda_cog.py https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LDEM_80S_20MPP_ADJ.TIF \
        data/raw/moon/LDEM_80S_20MPP_ADJ_clip32km.tif 32
    uv run python scripts/clip_pgda_cog.py https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LPSR_80S_20MPP_ADJ.TIF \
        data/raw/moon/LPSR_80S_20MPP_ADJ_clip32km.tif 32

Prints the sha256 of the written file and value statistics (for a 0/1 mask, the distinct values).
Set GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR to stop GDAL listing the remote directory.
"""

from __future__ import annotations

import hashlib
import sys

import numpy as np
import rasterio
from rasterio.windows import from_bounds


def clip(url: str, out: str, half_km: float) -> dict:
    h = half_km * 1000.0
    with rasterio.open("/vsicurl/" + url) as ds:
        win = from_bounds(-h, -h, h, h, ds.transform).round_offsets().round_lengths()
        a = ds.read(1, window=win)
        prof = ds.profile.copy()
        prof.update(width=a.shape[1], height=a.shape[0], transform=ds.window_transform(win), tiled=True,
                    blockxsize=512, blockysize=512, compress="deflate")
        tags, btags = ds.tags(), ds.tags(1)
    with rasterio.open(out, "w", **prof) as dst:
        dst.write(a, 1)
        dst.update_tags(**tags, SOURCE_URL=url, CLIP=f"x and y in [-{h:.0f}, {h:.0f}] m, source pixels unchanged")
        dst.update_tags(1, **btags)
    with open(out, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    fin = np.isfinite(a)
    uniq = np.unique(a[fin])
    return {"out": out, "shape": a.shape, "dtype": str(a.dtype), "transform": tuple(prof["transform"])[:6],
            "nodata": prof.get("nodata"), "n_nan": int((~fin).sum()), "min": float(uniq.min()), "max": float(uniq.max()),
            "distinct_values_if_few": uniq.tolist() if uniq.size < 20 else None, "sha256": sha}


if __name__ == "__main__":
    print(clip(sys.argv[1], sys.argv[2], float(sys.argv[3])))
