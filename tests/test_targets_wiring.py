import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from gsop.config import load_all
from gsop.targets import common as C
from gsop.targets import mars, moon

CFG = load_all()


def test_mars_air_density_follows_the_configured_model():
    atm = CFG["targets"]["mars_atmosphere"]
    g = atm["glenn"]
    assert mars.air_density_kg_m3(0.0, atm) == pytest.approx(g["p0_kpa"] / (g["gas_const"] * (g["kelvin"] + g["t0_c"])), rel=1e-9)
    assert 0.014 < mars.air_density_kg_m3(0.0, atm) < 0.017                 # about 0.015 kg/m3 at the reference level
    assert mars.air_density_kg_m3(-2500.0, atm) > mars.air_density_kg_m3(0.0, atm) > mars.air_density_kg_m3(2000.0, atm)
    with pytest.raises(ValueError):
        mars.air_density_kg_m3(g["valid_to_m"] + 1, atm)
    with pytest.raises(ValueError, match="only 'glenn'"):
        mars.air_density_kg_m3(0.0, {**atm, "use": "fact_sheet"})
    # changing the config changes the answer: nothing is hard-coded
    doubled = {**atm, "glenn": {**g, "p0_kpa": 2 * g["p0_kpa"]}}
    assert mars.air_density_kg_m3(0.0, doubled) == pytest.approx(2 * mars.air_density_kg_m3(0.0, atm))


def test_mask_share_median_and_spread():
    res = 100.0
    m = np.zeros((170, 170))
    m[:, :85] = 1.0                                    # left half shadowed
    rows = C.mask_share_rows("t", "water_index", m, res, "src", "A", 15.0)
    assert len(rows) == 1 and rows[0]["col"] == "water_index" and not rows[0]["unavailable"]
    assert 0.0 <= rows[0]["value"] <= 1.0 and rows[0]["spread"] >= 0.0
    assert C.mask_share_rows("t", "w", np.zeros((150, 150)), res, "s", "A", 15.0)[0]["value"] == 0.0
    assert C.mask_share_rows("t", "w", np.ones((150, 150)), res, "s", "A", 15.0)[0]["value"] == 1.0


def _polar_tif(path, value_fn, cell=100.0, half_km=20):
    n = int(2 * half_km * 1000 / cell)
    y, x = np.mgrid[0:n, 0:n]
    a = value_fn(x, y, n).astype("float32")
    crs = "+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 +a=1737400 +b=1737400 +units=m +no_defs"
    with rasterio.open(path, "w", driver="GTiff", height=n, width=n, count=1, dtype="float32", crs=crs,
                       transform=from_origin(-half_km * 1000.0, half_km * 1000.0, cell, cell)) as ds:
        ds.write(a, 1)


def test_moon_water_index_comes_from_the_psr_raster_and_stays_unavailable_without_it(tmp_path):
    dem, psr = tmp_path / "dem.tif", tmp_path / "psr.tif"
    _polar_tif(dem, lambda x, y, n: 0.02 * x + 0.01 * y)
    _polar_tif(psr, lambda x, y, n: (x < n // 2).astype(float))
    cfg = {**CFG, "targets": {**CFG["targets"], "moon": {"c": {"lat": -89.9, "lon_e": 0.0, "source": "test"}}}}
    with_psr = {(r["col"]): r for r in moon.build(cfg, None, psr)}
    assert not with_psr["water_index"]["unavailable"]
    without = {(r["col"]): r for r in moon.build(cfg, None, None)}
    assert without["water_index"]["unavailable"]
    assert all(without[c]["unavailable"] for c in moon.UNBUILT)
    assert {"silica_index", "t_mean", "t_coldest", "ti_proxy"} == set(moon.UNBUILT)


def test_mars_without_a_dem_leaves_elevation_and_density_unavailable_and_arcadia_is_skipped():
    rows = mars.build(CFG, None)
    targets = {r["target"] for r in rows}
    assert targets == {"jezero"}                                    # Arcadia has no centre (D10): no guess, no profile
    by = {r["col"]: r for r in rows}
    assert by["air_density"]["unavailable"] and by["aux_elevation_m"]["unavailable"]
