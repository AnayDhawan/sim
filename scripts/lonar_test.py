"""Phase 2 smoke test: download a small Earth Engine box, build the table, print what came out.

    uv run python scripts/lonar_test.py [half_km]
"""

from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")
from gsop.config import load_all  # noqa: E402
from gsop.earth import gee_export as GE  # noqa: E402
from gsop.earth.local_loaders import build_earth_table  # noqa: E402
from gsop.provenance import ROOT  # noqa: E402

half = float(sys.argv[1]) if len(sys.argv) > 1 else 150.0
cfg = load_all()
GE.init()
out = ROOT / "data" / "raw" / "earth_test_lonar"
t0 = time.perf_counter()
GE.download_test_box(76.51, 19.98, half, out, "lonar")
print(f"download {time.perf_counter() - t0:.0f}s")
df = build_earth_table(out, ROOT / "data" / "interim" / "earth_test_lonar.parquet",
                       add_solar=True, solar_cfg=cfg["features"])
pd.set_option("display.width", 200)
print(len(df), "tiles")
print(df.describe().T[["count", "min", "50%", "max"]])
