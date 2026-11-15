"""Query the live Earth Engine catalog for the candidate datasets and print what is really there.

    uv run python scripts/verify_catalog.py [project_id]

Prints id, type, bands, date range, license and version-like properties. Nothing here is trusted until it prints.
"""

from __future__ import annotations

import json
import sys

import ee

PROJECT = sys.argv[1] if len(sys.argv) > 1 else "gsop-earthengine"

CANDIDATES = [
    "NASA/NASADEM_HGT/001",
    "COPERNICUS/DEM/GLO30",
    "MODIS/061/MOD11A2",
    "MODIS/061/MOD13A2",
    "MODIS/061/MCD12Q1",
    "MODIS/061/MOD16A2GF",
    "NASA/GPM_L3/IMERG_MONTHLY_V07",
    "NASA/ASTER_GED/AG100_003",
    "NASA/GSFC/MERRA/aer/2",
]


def describe(asset_id: str) -> dict:
    info = ee.data.getAsset(asset_id)
    props = info.get("properties", {})
    out = {"id": asset_id, "type": info.get("type"), "title": props.get("title"),
           "start": info.get("startTime") or props.get("date_range"), "end": info.get("endTime"),
           "license": props.get("license") or props.get("terms_of_use") or props.get("provider"),
           "version": props.get("version") or props.get("system:version")}
    bands = info.get("bands")
    if bands:
        out["bands"] = [b["id"] for b in bands]
    return out


def main() -> None:
    ee.Initialize(project=PROJECT)
    for cid in CANDIDATES:
        try:
            d = describe(cid)
            if d["type"] == "IMAGE_COLLECTION":
                first = ee.ImageCollection(cid).first().bandNames().getInfo()
                d["first_image_bands"] = first
                d["size"] = ee.ImageCollection(cid).size().getInfo()
            print(json.dumps(d, default=str))
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"id": cid, "error": str(e)[:200]}))


if __name__ == "__main__":
    main()
