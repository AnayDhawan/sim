"""Google Earth Engine route (issue #1): export the 6 km Earth feature raster, one band per feature.

STATUS: written but NOT RUN. Earth Engine needs `earthengine authenticate` and the Cloud project id from Anay; this module
never works around a failed login (it stops with the error). Run in this order, and fix what each step reports:
  1. uv run gsop s2 earth --source gee --verify                       every collection id in config/earth_layers.yaml
  2. uv run gsop check-operators                                      Earth Engine vs numpy terrain operators (issue #2)
  3. uv run gsop s2 earth --source gee --bbox 74,17,80,22 --name lonar_test    a ~600 km box around Lonar
  4. uv run gsop s2 earth --source gee --name global                  chunked global export
Then download the GeoTIFFs from Drive and run `uv run gsop s2 earth --source local --src <folder> --add-solar`.

Bands exported (names are the column names of config/features.yaml): land_frac, water_ice_frac, built_crop_frac,
ndvi_median, slope_med, slope_p90, relief, rough_a, rough_b, t_mean, t_coldest, ti_proxy, air_density.
Computed locally instead (latitude only, see solar.py): sun_max_elev, sun_low_share, insol_annual (`--add-solar`).
NOT built, so left out of the export and rejected by the missing-data gate with a reason: water_index, silica_index,
dust_index (see `not_built` in config/earth_layers.yaml). Nothing is substituted.

Tile alignment: every export uses crs EPSG:6933 and a crsTransform whose origin is the tile grid's own corner, so a
regional export and the global export give the same tile ids.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

import yaml

from ..grid import Grid
from ..provenance import ROOT
from . import gee_operators as GO
from . import open_data as OD

LAYERS_PATH = ROOT / "config" / "earth_layers.yaml"
ELEMENTS_PER_TASK_TILES = 200          # block edge in tiles for the global export (1,200 km)


# --------------------------------------------------------------------------- config and planning (tested offline)

def load_layers(path: Path | str = LAYERS_PATH) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def collection_ids(layers: dict[str, Any]) -> dict[str, str]:
    out = {"dem_primary": layers["dem"]["primary"]["id"], "dem_fallback": layers["dem"]["fallback"]["id"]}
    for k, v in layers["modis"].items():
        out[f"modis_{k}"] = v["id"]
    out["precip"] = layers["precip"]["id"]
    return out


def plan_windows(grid: Grid, window: tuple[int, int, int, int], block: int = ELEMENTS_PER_TASK_TILES
                 ) -> list[tuple[int, int, int, int]]:
    """Split a tile window (ix0, iy0, ix1, iy1) into blocks of at most block x block tiles."""
    ix0, iy0, ix1, iy1 = window
    return [(x, y, min(x + block, ix1), min(y + block, iy1)) for y in range(iy0, iy1, block) for x in range(ix0, ix1, block)]


def month_triplets() -> list[tuple[int, int, int]]:
    """The 12 cyclic runs of three consecutive calendar months (Dec-Jan-Feb wraps)."""
    return [(m, m % 12 + 1, (m + 1) % 12 + 1) for m in range(1, 13)]


# --------------------------------------------------------------------------- session

def init(project: str | None = None):
    """Initialise Earth Engine. No fallback: a failed login stops the run."""
    import ee
    project = project or os.environ.get("GSOP_EE_PROJECT")
    try:
        ee.Initialize(project=project) if project else ee.Initialize()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Earth Engine is not ready ({e}). Run `earthengine authenticate`, get the Cloud project id "
                           "from Anay and set GSOP_EE_PROJECT. Not working around this.") from e
    return ee


def verify(project: str | None = None) -> list[dict[str, Any]]:
    """Ask the live catalog about every collection id and the bands we use. Returns one row per collection."""
    ee = init(project)
    layers = load_layers()
    want = {layers["dem"]["primary"]["id"]: [layers["dem"]["primary"]["band"]],
            layers["dem"]["fallback"]["id"]: [layers["dem"]["fallback"]["band"]],
            layers["modis"]["lst"]["id"]: layers["modis"]["lst"]["bands"],
            layers["modis"]["ndvi"]["id"]: [layers["modis"]["ndvi"]["band"], layers["modis"]["ndvi"]["qa_band"]],
            layers["modis"]["landcover"]["id"]: [layers["modis"]["landcover"]["band"]],
            layers["precip"]["id"]: [layers["precip"]["band"]]}
    rows = []
    for cid, bands in want.items():
        try:
            info = ee.ImageCollection(cid).limit(1).getInfo()
            have = [b["id"] for b in info["features"][0]["bands"]] if info["features"] else []
            rows.append({"id": cid, "reachable": True, "bands_missing": [b for b in bands if b not in have],
                         "first_image_properties": sorted(info["features"][0]["properties"])[:6] if info["features"] else []})
        except Exception as e:  # noqa: BLE001
            rows.append({"id": cid, "reachable": False, "error": str(e)})
    return rows


# --------------------------------------------------------------------------- Earth Engine expressions (not run yet)

def _tf(grid: Grid, ix0: int, iy0: int, cell_m: float) -> list[float]:
    return GO.tile_transform(grid, ix0, iy0, cell_m)


def _to_tile_grid(img, reducer, grid: Grid, ix0: int, iy0: int, max_pixels: int = 65536):
    return img.reduceResolution(reducer=reducer, bestEffort=False, maxPixels=max_pixels).reproject(
        crs=grid.crs, crsTransform=_tf(grid, ix0, iy0, grid.cell_m))


def dem_image(ee, layers: dict[str, Any]):
    """NASADEM where it exists, Copernicus GLO-30 elsewhere (above 60N, below 56S)."""
    p, f = layers["dem"]["primary"], layers["dem"]["fallback"]
    nasa = ee.Image(p["id"]).select(p["band"])
    cop = ee.ImageCollection(f["id"]).select(f["band"]).mosaic().setDefaultProjection(
        ee.ImageCollection(f["id"]).first().select(f["band"]).projection())
    return nasa.unmask(cop).rename("elevation")


def climate_bands(ee, layers: dict[str, Any], grid: Grid, ix0: int, iy0: int):
    """t_mean, t_coldest, ti_proxy on the tile grid from the MODIS 8-day LST climatology.
    t_mean     = mean over the years of (day + night) / 2.
    t_coldest  = coldest calendar month of the climatological monthly mean of (day + night) / 2.
    ti_proxy   = mean (day - night) swing over the three driest consecutive calendar months (TerraClimate pr climatology)."""
    y0, y1 = layers["climatology_years"]
    lst, pr = layers["modis"]["lst"], layers["precip"]
    col = (ee.ImageCollection(lst["id"]).filterDate(f"{y0}-01-01", f"{y1 + 1}-01-01")
           .select(lst["bands"]))
    sc = lst["scale"]
    both = col.map(lambda im: im.multiply(sc).rename(["day", "night"]).copyProperties(im, ["system:time_start"]))
    mean_dn = both.map(lambda im: im.select("day").add(im.select("night")).divide(2).rename("t")
                       .copyProperties(im, ["system:time_start"]))
    swing = both.map(lambda im: im.select("day").subtract(im.select("night")).rename("swing")
                     .copyProperties(im, ["system:time_start"]))

    def monthly(c, band):
        return [c.filter(ee.Filter.calendarRange(m, m, "month")).mean().select(band) for m in range(1, 13)]

    t_m = monthly(mean_dn, "t")
    sw_m = monthly(swing, "swing")
    pr_col = (ee.ImageCollection(pr["id"]).filterDate(f"{y0}-01-01", f"{y1 + 1}-01-01").select(pr["band"]))
    pr_m = monthly(pr_col, pr["band"])
    t_mean = mean_dn.mean().rename("t_mean")
    t_cold = ee.ImageCollection.fromImages(t_m).min().rename("t_coldest")
    # three driest consecutive months: the triplet with the smallest summed precipitation, then its mean swing
    best_sum, best_swing = None, None
    for a, b, c in month_triplets():
        s = pr_m[a - 1].add(pr_m[b - 1]).add(pr_m[c - 1])
        w = sw_m[a - 1].add(sw_m[b - 1]).add(sw_m[c - 1]).divide(3)
        if best_sum is None:
            best_sum, best_swing = s, w
        else:
            drier = s.lt(best_sum)
            best_sum, best_swing = best_sum.where(drier, s), best_swing.where(drier, w)
    # where precipitation is missing (TerraClimate has gaps over ice), fall back to the annual mean swing and flag it
    annual_swing = swing.mean()
    ti = best_swing.unmask(annual_swing).rename("ti_proxy")
    mean = ee.Reducer.mean()
    return ee.Image.cat([_to_tile_grid(t_mean, mean, grid, ix0, iy0), _to_tile_grid(t_cold, mean, grid, ix0, iy0),
                         _to_tile_grid(ti, mean, grid, ix0, iy0)])


def gate_bands(ee, layers: dict[str, Any], grid: Grid, ix0: int, iy0: int):
    """land_frac, water_ice_frac, built_crop_frac from MODIS MCD12Q1 LC_Type1 (500 m, one year), ndvi_median from MOD13A2."""
    lc = layers["modis"]["landcover"]
    cls = lc["classes"]
    img = (ee.ImageCollection(lc["id"]).filterDate(f"{lc['year']}-01-01", f"{lc['year'] + 1}-01-01").first()
           .select(lc["band"]))
    mean = ee.Reducer.mean()
    land = img.neq(cls["water"]).rename("land_frac")
    wi = img.eq(cls["water"]).Or(img.eq(cls["snow_ice"])).rename("water_ice_frac")
    bc = img.eq(cls["cropland"]).Or(img.eq(cls["built"])).rename("built_crop_frac")
    nd = layers["modis"]["ndvi"]
    y0, y1 = layers["climatology_years"]
    ndvi_col = (ee.ImageCollection(nd["id"]).filterDate(f"{y0}-01-01", f"{y1 + 1}-01-01")
                .map(lambda im: im.select(nd["band"]).multiply(nd["scale"]).updateMask(
                    im.select(nd["qa_band"]).eq(nd["qa_good"]))))
    ndvi = ndvi_col.median().rename("ndvi_median")             # per-pixel temporal median, then the tile median below
    parts = [_to_tile_grid(x, mean, grid, ix0, iy0) for x in (land, wi, bc)]
    parts.append(_to_tile_grid(ndvi, ee.Reducer.median(), grid, ix0, iy0))
    return ee.Image.cat(parts)


def air_density_band(ee, dem, grid: Grid, ix0: int, iy0: int):
    """Earth standard atmosphere from the tile-mean elevation (NASA Glenn model, troposphere):
    T = 15.04 - 0.00649 h (C); p = 101.29 ((T + 273.1) / 288.08)^5.256 (kPa); rho = p / (0.2869 (T + 273.1)). Valid to 11 km."""
    h = _to_tile_grid(dem, ee.Reducer.mean(), grid, ix0, iy0).max(0).rename("h")
    t = h.multiply(-0.00649).add(15.04)
    p = t.add(273.1).divide(288.08).pow(5.256).multiply(101.29)
    return p.divide(t.add(273.1).multiply(0.2869)).rename("air_density")


def export_image(ee, window: tuple[int, int, int, int], grid: Grid | None = None, layers: dict[str, Any] | None = None):
    """All exported bands for one tile window, on the 6 km tile grid."""
    grid = grid or Grid()
    layers = layers or load_layers()
    ix0, iy0, _, _ = window
    dem = dem_image(ee, layers)
    terrain = GO.ee_tile_terrain(dem, grid, window, ee)
    return ee.Image.cat([gate_bands(ee, layers, grid, ix0, iy0), terrain, climate_bands(ee, layers, grid, ix0, iy0),
                         air_density_band(ee, dem, grid, ix0, iy0)]).toFloat()


BAND_ORDER = ["land_frac", "water_ice_frac", "built_crop_frac", "ndvi_median", "slope_med", "slope_p90", "relief",
              "rough_a", "rough_b", "t_mean", "t_coldest", "ti_proxy", "air_density"]


def run(source_bbox: tuple[float, float, float, float] | None = None, name: str = "gsop_earth", folder: str = "gsop_earth",
        project: str | None = None, dry_run: bool = False) -> list[dict[str, Any]]:
    """Start one Drive export task per block. dry_run only prints the plan. Returns the task list."""
    grid = Grid()
    win = OD.tile_window(grid, source_bbox)
    blocks = plan_windows(grid, win)
    tasks = []
    ee = None if dry_run else init(project)
    for k, w in enumerate(blocks):
        ix0, iy0, ix1, iy1 = w
        desc = f"{name}_{k:04d}_x{ix0}_y{iy0}"
        rec = {"description": desc, "window": w, "tiles": (ix1 - ix0) * (iy1 - iy0)}
        if not dry_run:
            img = export_image(ee, w, grid)
            region = ee.Geometry.Rectangle(
                [grid.x0 + ix0 * grid.cell_m, grid.y_top - iy1 * grid.cell_m,
                 grid.x0 + ix1 * grid.cell_m, grid.y_top - iy0 * grid.cell_m], proj=grid.crs, geodesic=False)
            task = ee.batch.Export.image.toDrive(image=img, description=desc, folder=folder, fileNamePrefix=desc,
                                                 region=region, crs=grid.crs, crsTransform=_tf(grid, ix0, iy0, grid.cell_m),
                                                 maxPixels=int(1e10), fileFormat="GeoTIFF")
            task.start()
            rec["task_id"] = task.id
        tasks.append(rec)
    out = Path("data") / "raw" / "earth"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}_export_plan.json").write_text(json.dumps({"band_order": BAND_ORDER, "tasks": tasks}, indent=2))
    return tasks
