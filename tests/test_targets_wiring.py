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


def _mask_tif(path, nodata, half_km=20, cell=100.0):
    n = int(2 * half_km * 1000 / cell)
    a = np.zeros((n, n), dtype="float32")
    a[:, : n // 2] = 1.0                                       # left half permanently shadowed
    crs = "+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 +a=1737400 +b=1737400 +units=m +no_defs"
    with rasterio.open(path, "w", driver="GTiff", height=n, width=n, count=1, dtype="float32", crs=crs, nodata=nodata,
                       transform=from_origin(-half_km * 1000.0, half_km * 1000.0, cell, cell)) as ds:
        ds.write(a, 1)


@pytest.mark.parametrize("nodata", [None, 0.0, -9999.0])
def test_psr_water_index_survives_any_declared_nodata(tmp_path, nodata):
    """Review: a PSR mask that declares nodata = 0 turned every non-PSR cell into NaN, so every tile was dropped and
    water_index came out unavailable."""
    psr = tmp_path / "psr.tif"
    _mask_tif(psr, nodata)
    cfg = {**CFG, "targets": {**CFG["targets"], "moon": {"c": {"lat": -89.9, "lon_e": 0.0, "source": "test"}}}}
    row = {r["col"]: r for r in moon.build(cfg, None, psr)}["water_index"]
    assert not row["unavailable"], f"nodata={nodata}: water_index was dropped"
    assert 0.0 < row["value"] < 1.0 or row["value"] in (0.0, 1.0)
    assert row["evidence_grade"] == "B"                                       # encoding not confirmed: not A
    assert "CONFIRM the encoding" in row["source"]                           # PSR_NOTE is in the row


def test_psr_value_is_the_same_with_and_without_a_declared_nodata(tmp_path):
    vals = []
    for nd in (None, 0.0):
        p = tmp_path / f"psr_{nd}.tif"
        _mask_tif(p, nd)
        cfg = {**CFG, "targets": {**CFG["targets"], "moon": {"c": {"lat": -89.9, "lon_e": 0.0, "source": "test"}}}}
        vals.append({r["col"]: r for r in moon.build(cfg, None, p)}["water_index"]["value"])
    assert vals[0] == pytest.approx(vals[1])


def test_dem_nodata_is_still_nan_but_mask_nodata_is_zero(tmp_path):
    p = tmp_path / "m.tif"
    _mask_tif(p, 0.0)
    dem, _ = C.read_window(p, -89.9, 0.0, 5.0, "nan")
    mask, _ = C.read_window(p, -89.9, 0.0, 5.0, "zero")
    assert np.isnan(dem).any() and np.isfinite(mask).all()
    with pytest.raises(ValueError):
        C.read_window(p, -89.9, 0.0, 5.0, "other")


def test_central_crop_is_the_central_window():
    a = np.arange(170 * 170, dtype=float).reshape(170, 170)
    c = C.central_crop(a, 100.0, 15.0)
    assert c.shape == (150, 150) and c[0, 0] == a[10, 10] and c[-1, -1] == a[159, 159]
    with pytest.raises(ValueError):
        C.central_crop(a, 100.0, 20.0)


def test_mars_elevation_is_the_median_of_the_target_window_not_the_whole_read(monkeypatch):
    """Review: np.nanmedian ran over the 17 km read while the row said 15 km."""
    n, cell = 170, 100.0                                          # a 17 km read at 100 m cells
    z = np.full((n, n), 1000.0)                                   # the margin ring
    z[10:160, 10:85] = 0.0                                        # the central 15 km: left half 0 ...
    z[10:160, 85:160] = 10.0                                      # ... right half 10, so its median is 5
    assert np.nanmedian(z) == 10.0                                # the whole read gives a different answer (the old bug)
    monkeypatch.setattr(C, "read_dem_window", lambda *a, **k: (z, cell))
    monkeypatch.setattr(C, "terrain_rows", lambda *a, **k: [])
    cfg = {**CFG, "targets": {**CFG["targets"], "mars": {"j": {"lat": 18.4386, "lon_e": 77.5031, "source": "t"}}}}
    by = {r["col"]: r for r in mars.build(cfg, "dem.tif")}
    assert by["aux_elevation_m"]["value"] == 5.0
    assert by["aux_elevation_m"]["window"] == "15 km"
    assert by["air_density"]["value"] == pytest.approx(mars.air_density_kg_m3(5.0, cfg["targets"]["mars_atmosphere"]))
