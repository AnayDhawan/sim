"""Google Earth Engine route (issue #1): export the 6 km Earth feature raster, one band per feature.

STATUS: written without a login, then corrected against Anay's real-run errors (PR 13 review); NOT RE-RUN since. Earth Engine needs `earthengine authenticate` and the Cloud project id from Anay; this module
never works around a failed login (it stops with the error). Run in this order, and fix what each step reports:
  1. uv run gsop s2 earth --source gee --verify                       every collection id in config/earth_layers.yaml
  2. uv run gsop check-operators                                      Earth Engine vs numpy terrain operators (issue #2)
  3. uv run gsop s2 earth --source gee --bbox 74,17,80,22 --name lonar_test    a ~600 km box around Lonar
  4. uv run gsop s2 earth --source gee --name global                  chunked global export
Then download the GeoTIFFs from Drive and run `uv run gsop s2 earth --source local --src <folder> --add-solar`.

Bands exported (names are the column names of config/features.yaml): land_frac, water_ice_frac, built_crop_frac,
ndvi_median, slope_med, slope_p90, relief, rough_a, rough_b, t_mean, t_coldest, ti_proxy, ti_is_fallback, air_density.
ti_is_fallback is a 0/1 flag per tile: 1 where more than half of the tile's pixels used the annual mean swing because no
precipitation-based dry season existed. It is a flag, not a feature, and never enters the score.
Computed locally instead (latitude only, see solar.py): sun_max_elev, sun_low_share, insol_annual (`--add-solar`).
NOT built, so left out of the export and rejected by the missing-data gate with a reason: water_index, silica_index,
dust_index (see `not_built` in config/earth_layers.yaml). Nothing is substituted.

Tile alignment: every export uses EPSG:6933 (passed as a WKT1_GDAL string, the only form Earth Engine accepts) and a crsTransform whose origin is the tile grid's own corner, so a
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
from ..config import data_dir, load_all
from . import gee_operators as GO
from . import open_data as OD

LAYERS_PATH = ROOT / "config" / "earth_layers.yaml"


# --------------------------------------------------------------------------- config and planning (tested offline)

def load_layers(path: Path | str = LAYERS_PATH) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def collection_ids(layers: dict[str, Any]) -> dict[str, str]:
    out = {"dem_primary": layers["dem"]["primary"]["id"], "dem_fallback": layers["dem"]["fallback"]["id"]}
    for k, v in layers["modis"].items():
        out[f"modis_{k}"] = v["id"]
    out["precip"] = layers["precip"]["id"]
    return out


def plan_windows(grid: Grid, window: tuple[int, int, int, int], block: int
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


# --------------------------------------------------------------------------- Earth Engine expressions (not re-run since the review)

def _tf(grid: Grid, ix0: int, iy0: int, cell_m: float) -> list[float]:
    return GO.tile_transform(grid, ix0, iy0, cell_m)


def dem_image(ee, layers: dict[str, Any]):
    """NASADEM where it exists, Copernicus GLO-30 (2024_1; the unversioned collection is deprecated) elsewhere."""
    p, f = layers["dem"]["primary"], layers["dem"]["fallback"]
    nasa = ee.Image(p["id"]).select(p["band"])
    col = ee.ImageCollection(f["id"]).select(f["band"])
    cop = col.mosaic().setDefaultProjection(col.first().projection())        # a mosaic has no projection until set
    return nasa.unmask(cop).rename("elevation")


def _monthly(c, band, ee):
    return [c.filter(ee.Filter.calendarRange(m, m, "month")).mean().select(band) for m in range(1, 13)]


def climate_bands(ee, layers: dict[str, Any], grid: Grid, ix0: int, iy0: int):
    """t_mean, t_coldest, ti_proxy, ti_is_fallback on the tile grid from the MODIS 8-day LST climatology.
    t_mean     = mean over the years of (day + night) / 2.
    t_coldest  = coldest calendar month of the climatological monthly mean of (day + night) / 2.
    ti_proxy   = mean (day - night) swing over the three driest consecutive calendar months (TerraClimate pr climatology);
                 where precipitation is missing it is the annual mean swing and ti_is_fallback is 1."""
    y0, y1 = layers["climatology_years"]
    lst, pr = layers["modis"]["lst"], layers["precip"]
    sc = lst["scale"]
    col = ee.ImageCollection(lst["id"]).filterDate(f"{y0}-01-01", f"{y1 + 1}-01-01").select(lst["bands"])
    lst_proj = col.first().select(0).projection()
    keep = ["system:time_start"]                                              # .map() drops it; calendarRange needs it
    both = col.map(lambda im: im.multiply(sc).rename(["day", "night"]).copyProperties(im, keep))
    mean_dn = both.map(lambda im: im.select("day").add(im.select("night")).divide(2).rename("t").copyProperties(im, keep))
    swing = both.map(lambda im: im.select("day").subtract(im.select("night")).rename("swing").copyProperties(im, keep))
    t_m, sw_m = _monthly(mean_dn, "t", ee), _monthly(swing, "swing", ee)
    pr_col = ee.ImageCollection(pr["id"]).filterDate(f"{y0}-01-01", f"{y1 + 1}-01-01").select(pr["band"])
    pr_m = _monthly(pr_col, pr["band"], ee)
    t_mean = mean_dn.mean().rename("t_mean")
    t_cold = ee.ImageCollection.fromImages(t_m).min().rename("t_coldest")
    best_sum, best_swing = None, None
    for a, b, c in month_triplets():                                          # driest three consecutive months
        tot = pr_m[a - 1].add(pr_m[b - 1]).add(pr_m[c - 1])
        w = sw_m[a - 1].add(sw_m[b - 1]).add(sw_m[c - 1]).divide(3)
        if best_sum is None:
            best_sum, best_swing = tot, w
        else:
            drier = tot.lt(best_sum)
            best_sum, best_swing = best_sum.where(drier, tot), best_swing.where(drier, w)
    valid = best_sum.mask().unmask(0)                                         # 1 where precipitation exists
    annual = swing.mean()
    ti = best_swing.updateMask(valid).unmask(annual).rename("ti_proxy")
    fallback = valid.Not().rename("ti_is_fallback")
    mean = ee.Reducer.mean()
    red = lambda im, r: GO.reduce_to(im, r, grid, ix0, iy0, ref_proj=lst_proj)   # noqa: E731
    flag = red(fallback, mean).gt(layers["export"]["fallback_flag_min_share"]).rename("ti_is_fallback")
    return ee.Image.cat([red(t_mean, mean), red(t_cold, mean), red(ti, mean), flag])


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
    raw = ee.ImageCollection(nd["id"]).filterDate(f"{y0}-01-01", f"{y1 + 1}-01-01")
    nd_proj = raw.first().select(nd["band"]).projection()
    ndvi_col = raw.map(lambda im: im.select(nd["band"]).multiply(nd["scale"])
                       .updateMask(im.select(nd["qa_band"]).eq(nd["qa_good"])).copyProperties(im, ["system:time_start"]))
    ndvi = ndvi_col.median().rename("ndvi_median")                           # per-pixel temporal median, then the tile median
    parts = [GO.reduce_to(x, mean, grid, ix0, iy0) for x in (land, wi, bc)]
    parts.append(GO.reduce_to(ndvi, ee.Reducer.median(), grid, ix0, iy0, ref_proj=nd_proj))
    return ee.Image.cat(parts)


def air_density_band(ee, dem, grid: Grid, ix0: int, iy0: int, atm: dict[str, Any]):
    """Earth standard atmosphere from the tile-mean elevation, constants from config/features.yaml `earth_atmosphere`
    (NASA Glenn model, troposphere): T = t0 - lapse h; p = p0 ((T + K) / t_ref) ** exponent; rho = p / (R (T + K))."""
    h = GO.reduce_to(dem, ee.Reducer.mean(), grid, ix0, iy0).max(0).rename("h")
    t = h.multiply(-atm["lapse_c_per_m"]).add(atm["t0_c"])
    tk = t.add(atm["kelvin"])
    p = tk.divide(atm["t_ref_k"]).pow(atm["exponent"]).multiply(atm["p0_kpa"])
    return p.divide(tk.multiply(atm["gas_const"])).rename("air_density")


def export_image(ee, window: tuple[int, int, int, int], grid: Grid | None = None, layers: dict[str, Any] | None = None,
                 cfg: dict[str, Any] | None = None):
    """All exported bands for one tile window, on the 6 km tile grid."""
    grid = grid or Grid()
    layers = layers or load_layers()
    cfg = cfg or load_all()
    op = cfg["features"]["operator"]
    ix0, iy0, _, _ = window
    dem = dem_image(ee, layers)
    terrain = GO.ee_tile_terrain(dem, grid, window, ee, float(op["work_cell_m"]),
                                 float(op["slope_baseline_m"]), (op["rough_a_baseline_m"], op["rough_b_baseline_m"]))
    return ee.Image.cat([gate_bands(ee, layers, grid, ix0, iy0), terrain, climate_bands(ee, layers, grid, ix0, iy0),
                         air_density_band(ee, dem, grid, ix0, iy0, cfg["features"]["earth_atmosphere"])]).toFloat()


BAND_ORDER = ["land_frac", "water_ice_frac", "built_crop_frac", "ndvi_median", "slope_med", "slope_p90", "relief",
              "rough_a", "rough_b", "t_mean", "t_coldest", "ti_proxy", "ti_is_fallback", "air_density"]


def run(source_bbox: tuple[float, float, float, float] | None = None, name: str = "gsop_earth", folder: str = "gsop_earth",
        project: str | None = None, dry_run: bool = False, plan_dir: Path | None = None) -> list[dict[str, Any]]:
    """Start one Drive export task per block. dry_run only plans. The plan JSON is written to `plan_dir` (default
    data/raw/earth under the project root, `config.data_dir`), and the loader needs it next to the downloaded GeoTIFFs or
    via `--plan`. Earth Engine errors (`ee.EEException`) are re-raised as RuntimeError."""
    grid = Grid()
    win = OD.tile_window(grid, source_bbox)
    layers = load_layers()
    blocks = plan_windows(grid, win, int(layers["export"]["block_tiles"]))
    tasks = []
    ee = None if dry_run else init(project)
    cfg = None if dry_run else load_all()
    for k, w in enumerate(blocks):
        ix0, iy0, ix1, iy1 = w
        desc = f"{name}_{k:04d}_x{ix0}_y{iy0}"
        rec = {"description": desc, "window": w, "tiles": (ix1 - ix0) * (iy1 - iy0)}
        if not dry_run:
            try:
                img = export_image(ee, w, grid, cfg=cfg)
                region = ee.Geometry.Rectangle(
                    [grid.x0 + ix0 * grid.cell_m, grid.y_top - iy1 * grid.cell_m,
                     grid.x0 + ix1 * grid.cell_m, grid.y_top - iy0 * grid.cell_m], proj=GO.ee_crs(), geodesic=False)
                task = ee.batch.Export.image.toDrive(image=img, description=desc, folder=folder, fileNamePrefix=desc,
                                                     region=region, crs=GO.ee_crs(), crsTransform=_tf(grid, ix0, iy0, grid.cell_m),
                                                     maxPixels=int(1e10), fileFormat="GeoTIFF")
                task.start()
                rec["task_id"] = task.id
            except ee.EEException as e:
                raise RuntimeError(f"Earth Engine rejected export task {desc}: {e}") from e
        tasks.append(rec)
    out = Path(plan_dir) if plan_dir else data_dir("raw") / "earth"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}_export_plan.json").write_text(json.dumps({"band_order": BAND_ORDER, "tasks": tasks}, indent=2))
    return tasks
