import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from gsop import operators as O
from gsop.config import load_all
from gsop.earth.solar import sun_features
from gsop.targets import common as C
from gsop.targets import mars, moon

CFG = load_all()
OP = CFG["features"]["operator"]
MOLA_CELL = 463.093541550370901                                   # PixelResolution in the USGS MOLA 463 m label


# ------------------------------------------------------------------ resampling and roughness on a coarse DEM

def test_resample_bilinear_keeps_a_plane_and_the_centre():
    n = 37
    y, x = np.mgrid[0:n, 0:n]
    z = 3.0 * x * MOLA_CELL / 1000.0 - 1.5 * y * MOLA_CELL / 1000.0           # a plane in metres per km
    out, cell = C.resample_bilinear(z, MOLA_CELL, 500.0)
    assert cell == 500.0 and out.shape == (int(n * MOLA_CELL // 500), int(n * MOLA_CELL // 500))
    m = out.shape[0]
    yy = (n - 1) / 2 + (np.arange(m) - (m - 1) / 2) * 500.0 / MOLA_CELL
    want = 3.0 * yy[None, :] * MOLA_CELL / 1000.0 - 1.5 * yy[:, None] * MOLA_CELL / 1000.0
    inside = np.isfinite(out)
    assert inside[1:-1, 1:-1].all()
    assert np.allclose(out[inside], want[inside], atol=1e-6)


def test_resample_bilinear_never_fills_a_nan():
    z = np.ones((40, 40))
    z[20, 20] = np.nan
    out, _ = C.resample_bilinear(z, MOLA_CELL, 500.0)
    assert np.isnan(out).sum() >= 1 and np.isfinite(out).sum() > 0.9 * out.size


def test_rough_reason_is_none_on_lola_and_names_both_baselines_on_mola():
    assert C.rough_unavailable_reason(20.0, OP) is None                       # LOLA 20 m: 5 and 50 cells
    why = C.rough_unavailable_reason(MOLA_CELL, OP)
    assert "rough_a" in why and "rough_b" in why and "0.65 cells" in why and "2.16 cells" in why


def test_slope_on_a_resampled_tilted_plane_matches_the_plane():
    n = 40                                                         # 18.5 km of 463 m cells
    y, x = np.mgrid[0:n, 0:n]
    g = np.tan(np.radians(5.0))
    z = g * x * MOLA_CELL                                           # 5 deg slope towards +x
    tdem, cell = C.resample_bilinear(z, MOLA_CELL, 500.0)
    rows = {r["col"]: r for r in C.terrain_rows("t", tdem, cell, "src", "A", 15.0, OP,
                                                C.rough_unavailable_reason(MOLA_CELL, OP))}
    assert rows["slope_med"]["value"] == pytest.approx(5.0, abs=1e-6)
    assert rows["slope_p90"]["value"] == pytest.approx(5.0, abs=1e-6)
    assert rows["relief"]["value"] == pytest.approx(g * 11 * 500.0, rel=1e-6)    # 12 cells of 500 m per tile
    for c in ("rough_a", "rough_b"):
        assert rows[c]["unavailable"] and np.isnan(rows[c]["value"]) and "plane fit" in rows[c]["source"]


def test_rough_a_is_300_m_in_config_and_in_the_operator_default():
    """target-side E22: one roughness baseline on every body; the operator default must not drift from the config."""
    import inspect
    assert OP["rough_a_baseline_m"] == 300 and OP["rough_b_baseline_m"] == 1000
    default = inspect.signature(O.tile_features).parameters["rough_baselines_m"].default
    assert default == (OP["rough_a_baseline_m"], OP["rough_b_baseline_m"])
    for cell in (20.0, 25.0, 100.0):                       # LOLA, the Earth Engine check grid, the SRTM90 work grid
        assert C.rough_unavailable_reason(cell, OP) is None


def test_terrain_rows_without_a_reason_still_compute_roughness():
    rng = np.random.default_rng(0)
    z = rng.normal(0, 1, (850, 850))                                # 17 km at 20 m
    rows = {r["col"]: r for r in C.terrain_rows("t", z, 20.0, "src", "A", 15.0, OP)}
    assert not rows["rough_a"]["unavailable"] and not rows["rough_b"]["unavailable"]
    assert set(rows) == {"slope_med", "slope_p90", "relief", "rough_a", "rough_b"}


# ------------------------------------------------------------------ Mars build with a MOLA-like GeoTIFF

def _mola_like(path, value_fn):
    """A small equirectangular Mars raster with the MOLA cell size, around Jezero."""
    crs = "+proj=eqc +lat_ts=0 +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +R=3396190 +units=m +no_defs"
    x0 = np.radians(77.5031) * 3396190 - 30 * MOLA_CELL
    y0 = np.radians(18.4386) * 3396190 + 30 * MOLA_CELL
    n = 60
    yy, xx = np.mgrid[0:n, 0:n]
    with rasterio.open(path, "w", driver="GTiff", height=n, width=n, count=1, dtype="int16", crs=crs, nodata=-32768,
                       transform=from_origin(x0, y0, MOLA_CELL, MOLA_CELL)) as ds:
        ds.write(value_fn(xx, yy).astype("int16"), 1)


def test_mars_build_from_a_mola_cell_dem(tmp_path):
    p = tmp_path / "mola.tif"
    _mola_like(p, lambda x, y: -2500 + 0 * x)                          # flat at -2500 m
    rows = mars.build(CFG, p)
    by = {r["col"]: r for r in rows}
    assert {r["target"] for r in rows} == {"jezero"}
    for c in ("slope_med", "slope_p90", "relief"):
        assert not by[c]["unavailable"] and by[c]["value"] == pytest.approx(0.0, abs=1e-9)
        assert "resampled bilinearly" in by[c]["source"]
    assert by["rough_a"]["unavailable"] and by["rough_b"]["unavailable"]
    assert by["aux_elevation_m"]["value"] == -2500.0
    assert by["air_density"]["value"] == pytest.approx(
        mars.air_density_kg_m3(-2500.0, CFG["targets"]["mars_atmosphere"]))
    for c in mars.UNBUILT + mars.FILE_COLS:                              # no THEMIS file and no MCD table were given
        assert by[c]["unavailable"], c


def test_mars_sunlight_uses_the_earth_code_with_the_mars_constants():
    by = {r["col"]: r for r in mars.sun_rows("j", 18.4386, CFG)}
    ms = CFG["targets"]["mars_solar"]
    want = sun_features(18.4386, {"solar": {**CFG["features"]["solar"], "obliquity_deg": ms["obliquity_deg"],
                                            "s0_w_m2": ms["s0_w_m2"]},
                                  "sun_low_threshold_deg": CFG["features"]["sun_low_threshold_deg"]})
    assert by["insol_annual"]["value"] == pytest.approx(float(want["insol_annual"][0]))
    assert by["sun_max_elev"]["value"] == pytest.approx(float(want["sun_max_elev"][0]))
    assert by["insol_annual"]["evidence_grade"] == "C" and "fact sheet" in by["insol_annual"]["source"]
    assert 80.0 < by["sun_max_elev"]["value"] <= 90.0                  # 18.4 deg < obliquity 25.19: Sun near zenith
    earth = sun_features(18.4386, CFG["features"])["insol_annual"][0]
    assert by["insol_annual"]["value"] == pytest.approx(earth * ms["s0_w_m2"] / CFG["features"]["solar"]["s0_w_m2"],
                                                        rel=0.02)    # obliquities differ by 1.75 deg only
    cfg = {**CFG, "targets": {k: v for k, v in CFG["targets"].items() if k != "mars_solar"}}
    assert all(r["unavailable"] for r in mars.sun_rows("j", 18.4386, cfg))


# ------------------------------------------------------------------ Moon PSR grade

def _mask(path, a):
    n = a.shape[0]
    crs = "+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 +a=1737400 +b=1737400 +units=m +no_defs"
    with rasterio.open(path, "w", driver="GTiff", height=n, width=n, count=1, dtype="float32", crs=crs,
                       nodata=np.nan, transform=from_origin(-n * 50.0, n * 50.0, 100.0, 100.0)) as ds:
        ds.write(a.astype("float32"), 1)


@pytest.mark.parametrize("name,value,grade", [("LPSR_80S_20MPP_ADJ_clip32km.tif", 1.0, "A"),
                                              ("LPSR_80S_20MPP_ADJ.TIF", 1.0, "A"),
                                              ("LPSR_80S_20MPP_ADJ_clip32km.tif", 2.0, "B"),
                                              ("other_psr.tif", 1.0, "B")])
def test_psr_grade_is_a_only_for_the_checked_product_with_0_1_values(tmp_path, name, value, grade):
    a = np.zeros((400, 400))
    a[:, :200] = value
    p = tmp_path / name
    _mask(p, a)
    cfg = {**CFG, "targets": {**CFG["targets"], "moon": {"c": {"lat": -89.9, "lon_e": 0.0, "source": "test"}}}}
    row = {r["col"]: r for r in moon.build(cfg, None, p)}["water_index"]
    assert row["evidence_grade"] == grade
    assert ("CONFIRM the encoding" in row["source"]) == (grade == "B")
    assert row["value"] == pytest.approx(0.5)
