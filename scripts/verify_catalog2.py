"""Second catalog pass: date ranges, the GLO30 replacement, and a search for permafrost and aridity assets."""

from __future__ import annotations

import json
import sys
import warnings

import ee

warnings.filterwarnings("ignore")
ee.Initialize(project=sys.argv[1] if len(sys.argv) > 1 else "gsop-earthengine")

for cid in ["COPERNICUS/DEM/GLO30_2024_1", "MODIS/061/MOD11A2", "MODIS/061/MOD13A2", "MODIS/061/MCD12Q1",
            "MODIS/061/MOD16A2GF", "NASA/GPM_L3/IMERG_MONTHLY_V07", "NASA/GSFC/MERRA/aer/2"]:
    try:
        ic = ee.ImageCollection(cid)
        rng = ic.reduceColumns(ee.Reducer.minMax(), ["system:time_start"]).getInfo()
        info = ee.data.getAsset(cid)
        print(json.dumps({"id": cid, "min": rng["min"], "max": rng["max"],
                          "start_iso": ee.Date(rng["min"]).format("YYYY-MM-dd").getInfo(),
                          "end_iso": ee.Date(rng["max"]).format("YYYY-MM-dd").getInfo(),
                          "first_bands": ic.first().bandNames().getInfo()[:6],
                          "proj_scale_m": ic.first().select(0).projection().nominalScale().getInfo(),
                          "keys": sorted(info.get("properties", {}).keys())[:12]}))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"id": cid, "error": str(e)[:200]}))

# community catalog search
for parent in ["projects/sat-io/open-datasets"]:
    try:
        tok, hits = None, []
        while True:
            r = ee.data.listAssets({"parent": parent, "pageSize": 1000, **({"pageToken": tok} if tok else {})})
            for a in r.get("assets", []):
                n = a["id"].lower()
                if any(k in n for k in ("permafrost", "arid", "gaez", "pet", "ai_et0", "frozen", "ground_ice")):
                    hits.append(a["id"])
            tok = r.get("nextPageToken")
            if not tok:
                break
        print(json.dumps({"community_hits": hits}))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"community_list_error": str(e)[:200]}))
