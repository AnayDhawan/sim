"""Mars target columns derived from files: THEMIS thermal inertia (aux_thermal_inertia_si) and MCD surface temperature
(t_mean, t_coldest). Synthetic rasters and tables only; the real inputs are in docs/PROVENANCE.md."""

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin

from gsop import operators as O
from gsop.config import load_all
from gsop.targets import common as C
from gsop.targets import mars

CFG = load_all()
R_MARS = 3396190.0
THEMIS_CRS = ("+proj=eqc +lat_ts=0 +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +R=3396190 +units=m +no_defs")
LAT, LON = 18.4386, 77.5031


def _themis(path, fn, n=200, cell=100.0, offset_cells=(0, 0)):
    """An equirectangular Mars float32 raster at 100 m with nodata 0, centred on Jezero (plus an optional shift in cells)."""
    x0 = np.radians(LON) * R_MARS - n / 2 * cell + offset_cells[1] * cell
    y0 = np.radians(LAT) * R_MARS + n / 2 * cell + offset_cells[0] * cell
    yy, xx = np.mgrid[0:n, 0:n]
    with rasterio.open(path, "w", driver="GTiff", height=n, width=n, count=1, dtype="float32", crs=THEMIS_CRS,
                       nodata=0.0, transform=from_origin(x0, y0, cell, cell)) as ds:
        ds.write(fn(xx, yy).astype("float32"), 1)


# ------------------------------------------------------------------ common helpers

def test_tile_median_profile_uses_the_tile_median_then_median_and_iqr_over_tiles():
    a = np.arange(150 * 150, dtype=float).reshape(150, 150) % 97.0          # 6 km tiles at 3 km stride = 60 and 30 cells
    v, s, n = C.tile_median_profile(a, 100.0, 15.0)
    t = O._nanstat(O._tile_view(a, 60, 30), lambda z: np.nanmedian(z, axis=2)).ravel()
    q75, q25 = np.percentile(t, [75, 25])
    assert n == 16 and v == pytest.approx(np.median(t)) and s == pytest.approx((q75 - q25) / 1.349)


def test_tile_median_profile_drops_a_tile_with_under_90_percent_valid_cells():
    a = np.full((150, 150), 100.0)
    a[0:7, :] = np.nan                                             # 7 of the 60 rows (11.7%) of every tile in tile-row 0
    v, s, n = C.tile_median_profile(a, 100.0, 15.0)
    assert n == 12 and v == 100.0 and s == 0.0                      # the 4 tiles of tile-row 0 are dropped, nothing is filled


def test_tile_median_profile_all_missing_gives_nan():
    v, s, n = C.tile_median_profile(np.full((150, 150), np.nan), 100.0, 15.0)
    assert n == 0 and np.isnan(v) and np.isnan(s)


def test_window_coverage_counts_finite_cells_of_the_central_window():
    a = np.full((170, 170), 5.0)
    a[:, :60] = np.nan                                             # outside the 150-cell crop at columns 10..160: 50 columns of it
    cov = C.window_coverage(a, 100.0, 15.0)
    assert cov["cells"] == 22500 and cov["valid_cells"] == 22500 - 150 * 50
    assert cov["covered_frac"] == pytest.approx(1 - 50 / 150)


# ------------------------------------------------------------------ THEMIS

def test_themis_reports_file_metadata_and_full_coverage(tmp_path):
    p = tmp_path / "themis.tif"
    _themis(p, lambda x, y: np.where(x < 20, 0.0, 250.0))          # nodata only in the 1 km read margin, outside the window
    prof = mars.themis_profile(p, LAT, LON, 15.0, CFG["features"]["operator"])
    assert prof["value"] == pytest.approx(250.0) and prof["spread"] == pytest.approx(0.0)
    assert prof["covered_frac"] == 1.0 and prof["n_tiles"] == 16
    assert prof["nodata"] == 0.0 and prof["cell_m"] == 100.0 and prof["bounds"][0] < prof["bounds"][2]


def test_themis_zero_cells_inside_the_window_are_not_averaged_in(tmp_path):
    p = tmp_path / "themis.tif"
    _themis(p, lambda x, y: np.where((x >= 100) & (x < 106), 0.0, 300.0))      # 6 columns of nodata, inside the window
    prof = mars.themis_profile(p, LAT, LON, 15.0, CFG["features"]["operator"])
    assert prof["value"] == pytest.approx(300.0)                    # a 0 read as data would pull the median of that tile down
    assert prof["valid_pixels"] == 22500 - 6 * 150 and prof["covered_frac"] == pytest.approx(1 - 6 / 150)


def test_themis_window_partly_off_the_raster_reports_the_covered_fraction(tmp_path):
    p = tmp_path / "themis.tif"
    _themis(p, lambda x, y: 220.0 + 0 * x, n=200, offset_cells=(0, 40))        # raster shifted: window hangs off the west edge
    prof = mars.themis_profile(p, LAT, LON, 15.0, CFG["features"]["operator"])
    assert 0.5 < prof["covered_frac"] < 1.0 and prof["valid_pixels"] < prof["window_pixels"]


def test_themis_rows_put_ti_in_the_aux_column_and_leave_ti_proxy_unavailable(tmp_path):
    p = tmp_path / "themis.tif"
    _themis(p, lambda x, y: 240.0 + 0 * x)
    by = {r["col"]: r for r in mars.themis_rows("jezero", LAT, LON, p, CFG)}
    ti = by["aux_thermal_inertia_si"]
    assert ti["value"] == pytest.approx(240.0) and not ti["unavailable"] and ti["evidence_grade"] == "A"
    for word in ("status DERIVED", "zenodo.org/records/4931348", "J m-2 K-1 s-1/2", "2026-11-14", "--themis",
                 "valid pixels", "nodata 0"):
        assert word in ti["source"], word
    assert by["ti_proxy"]["unavailable"] and "temperature swing in K" in by["ti_proxy"]["source"]
    assert np.isnan(by["ti_proxy"]["value"])


# ------------------------------------------------------------------ MCD

HTML = """<html><head><title>Mars Climate Database: The Web Interface</title></head><body>
 Loading variables for new season
<hr>
MCD_v6.2 with climatology average solar scenario. Ls 0.0deg.
 Latitude 18.4386N. Longitude 77.5031E. Altitude 0.0 m ALS. Local time 12.0h
<hr>
<ul>
<li>
Surface temperature (K) ..... 270.04218
</li>
</ul>
<hr>
</body></html>"""


def test_parse_mcd_tsurf_reads_value_and_version_line():
    v, head = mars.parse_mcd_tsurf(HTML)
    assert v == pytest.approx(270.04218)
    assert head.startswith("MCD_v6.2 with climatology average solar scenario")
    with pytest.raises(ValueError):
        mars.parse_mcd_tsurf("<html>error</html>")


def _table(fn):
    rows = []
    for ls in range(0, 360, 15):
        for lt in range(24):
            rows.append({"ls_deg": float(ls), "local_time_h": float(lt), "tsurf_k": float(fn(ls, lt)), "kind": "point"})
    rows.append({"ls_deg": 0.0, "local_time_h": 0.0, "tsurf_k": 999.0, "kind": "service_diurnal_mean"})   # must be ignored
    return pd.DataFrame(rows)


def test_mcd_stats_weights_months_by_sols_and_finds_the_daily_minimum():
    w = CFG["targets"]["mars_climate"]["month_sols"]
    assert len(w) == 12 and sum(w) == pytest.approx(668.6)
    # warm months 0 to 5 (Ls 0-179), cold months 6 to 11; one 5 K dip at Ls 300, local time 5
    df = _table(lambda ls, lt: (260.0 if ls < 180 else 200.0) - (5.0 if (ls == 300 and lt == 5) else 0.0))
    s = mars.mcd_stats(df, w)
    want = (sum(w[:6]) * 260.0 + sum(w[6:]) * 200.0) / sum(w)
    assert s["t_mean"] == pytest.approx(want)                        # Ls 300 is not a month centre, so the dip does not enter
    assert s["t_mean_equal_ls"] != pytest.approx(s["t_mean"])        # equal Ls steps are not equal time steps
    assert s["t_coldest"] == 195.0 and s["t_coldest_ls_deg"] == 300.0 and s["t_coldest_local_time_h"] == 5.0
    assert s["n_ls"] == 24 and s["n_local_times"] == 24 and s["n_point_rows"] == 576


def test_mcd_stats_needs_the_month_centres():
    df = _table(lambda ls, lt: 250.0)
    df = df[df["ls_deg"] != 45.0]
    with pytest.raises(ValueError, match="month-centre"):
        mars.mcd_stats(df, CFG["targets"]["mars_climate"]["month_sols"])


def test_mcd_rows_are_derived_grade_c_with_zero_spread(tmp_path):
    p = tmp_path / "mcd.csv"
    _table(lambda ls, lt: 220.0 + 40.0 * np.cos(np.radians((lt - 14) * 15))).to_csv(p, index=False)
    by = {r["col"]: r for r in mars.mcd_rows("jezero", p, CFG)}
    assert set(by) == {"t_mean", "t_coldest"}
    assert by["t_mean"]["value"] == pytest.approx(220.0, abs=1e-6) and by["t_mean"]["spread"] == 0.0
    assert by["t_coldest"]["value"] == pytest.approx(180.0, abs=1e-6)            # the 24 h cosine bottoms out at lt = 2
    for r in by.values():
        assert r["evidence_grade"] == "C" and not r["unavailable"]
        for word in ("status DERIVED", "Mars Climate Database v6.2", "climatology average solar", "tsurf",
                     "2026-11-14", "--mcd", "MCD is a model"):
            assert word in r["source"], word


def test_build_with_and_without_the_derived_files(tmp_path):
    th, mc = tmp_path / "themis.tif", tmp_path / "mcd.csv"
    _themis(th, lambda x, y: 210.0 + 0 * x)
    _table(lambda ls, lt: 230.0).to_csv(mc, index=False)
    bare = {r["col"]: r for r in mars.build(CFG, None)}
    for c in mars.UNBUILT + mars.FILE_COLS:
        assert bare[c]["unavailable"], c
    full = {r["col"]: r for r in mars.build(CFG, None, th, mc)}
    for c in ("aux_thermal_inertia_si", "t_mean", "t_coldest"):
        assert not full[c]["unavailable"], c
    for c in ("ti_proxy", "silica_index", "water_index", "dust_index"):
        assert full[c]["unavailable"], c
    assert sum(r["col"] == "ti_proxy" for r in mars.build(CFG, None, th, mc)) == 1      # no duplicate row
