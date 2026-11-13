"""Google Earth Engine route (Phase 2). NOT IMPLEMENTED YET.

Plan (see the setup prompt, section 4):
  * authenticate with `earthengine authenticate`; the Cloud project id comes from Anay, never bypass the login;
  * verify every collection ID in the live catalog before use and record id, version, date range, resolution and
    licence in docs/PROVENANCE.md (do not trust the leads in config/features.yaml);
  * compute every layer server-side, export 6 km rasters (crs EPSG:6933, scale 6000), one band per feature;
  * slope: reduceResolution(mean) to the 500 m baseline, then slope, then reduce to the tile with percentiles 50 and 90.
    This must match gsop.operators; `gsop check-operators` compares the two on one small window.
Until then `gsop s2 earth --source local` builds the table from rasters you export yourself.
"""

from __future__ import annotations


def verify_collection(collection_id: str) -> dict:
    """Query the live catalog for one collection. Requires an authenticated Earth Engine session."""
    import ee
    ee.Initialize()
    info = ee.ImageCollection(collection_id).limit(1).getInfo() if "/" in collection_id else None
    return {"id": collection_id, "reachable": info is not None}


def run(*args, **kwargs):
    raise NotImplementedError("Earth Engine export is Phase 2: authenticate first, then implement and test on a "
                              "small region before any global export. See this module's docstring.")
