import numpy as np
import pandas as pd
from typer.testing import CliRunner

from gsop.astro import add_earth_derived, earth_air_density
from gsop.config import load_all
from gsop.earth.solar import sun_features

CFG = load_all()["features"]
OBL = float(CFG["solar"]["obliquity_deg"])


def test_equator_sun_reaches_zenith():
    assert abs(sun_features([0.0], CFG)["sun_max_elev"][0] - 90.0) < 1.0


def test_pole_sun_max_is_obliquity():
    assert abs(sun_features([89.99], CFG)["sun_max_elev"][0] - OBL) < 1.0


def test_pole_low_share():
    # At the pole elevation = declination, so the Sun is under 5 deg for the share of daylight with
    # sin(L) < sin(5)/sin(obliquity): analytic 2*asin(sin 5 / sin OBL)/pi, about 0.14 for Earth.
    share = sun_features([89.99], CFG)["sun_low_share"][0]
    expect = 2 * np.arcsin(np.sin(np.radians(5.0)) / np.sin(np.radians(OBL))) / np.pi
    assert abs(share - expect) < 0.02
    # A small obliquity (the Moon's is about 1.5 deg) keeps the pole Sun low all year.
    moonish = {**CFG, "solar": {**CFG["solar"], "obliquity_deg": 1.5}}
    assert sun_features([89.99], moonish)["sun_low_share"][0] > 0.9


def test_insolation_larger_at_equator_than_lat70():
    s = sun_features([0.0, 70.0], CFG)
    assert s["insol_annual"][0] > s["insol_annual"][1]


def test_earth_density_sea_level_and_decreasing():
    atm = CFG["earth_atmosphere"]
    assert abs(float(earth_air_density([0.0], atm)[0]) - 1.225) < 0.005      # sea level about 1.225 kg/m3
    d = earth_air_density(np.array([0.0, 1000.0, 3000.0, 5000.0]), atm)
    assert np.all(np.diff(d) < 0)
    assert earth_air_density([-400.0], atm)[0] == earth_air_density([0.0], atm)[0]   # below sea level clipped to 0 m


def test_add_earth_derived_columns_and_shared_latitude():
    df = pd.DataFrame({"lat": [10.0, 10.0, -35.0, 5.0], "lon": [0.0, 50.0, 20.0, 1.0],
                       "elev_mean": [0.0, 100.0, 2000.0, np.nan]})
    out = add_earth_derived(df, CFG)
    for c in ("sun_max_elev", "sun_low_share", "insol_annual", "air_density"):
        assert c in out.columns
    for c in ("sun_max_elev", "sun_low_share", "insol_annual"):
        assert out[c].iloc[0] == out[c].iloc[1]
    assert out["air_density"].iloc[0] > out["air_density"].iloc[1]
    assert np.isnan(out["air_density"].iloc[3])                     # no terrain, no density
    assert "sun_max_elev" not in df.columns   # input untouched
    keep = add_earth_derived(df.assign(insol_annual=7.0), CFG)
    assert (keep["insol_annual"] == 7.0).all()                      # never overwritten


def _run_verify(monkeypatch, results):
    from gsop.cli import app
    from gsop.earth import gee_export
    monkeypatch.setattr(gee_export, "verify_catalog", lambda project=None: results)
    return CliRunner().invoke(app, ["s2", "earth", "--source", "gee", "--verify"])


def test_cli_verify_all_ok_exits_0(monkeypatch):
    ok = [{"key": "a", "id": "X/Y", "ok": True, "detail": "IMAGE"}, {"key": "b", "id": "X/Z", "ok": True, "detail": "IMAGE"}]
    r = _run_verify(monkeypatch, ok)
    assert r.exit_code == 0, r.output
    assert "PASS" in r.output and "FAIL" not in r.output


def test_cli_verify_one_failure_exits_1(monkeypatch):
    res = [{"key": "a", "id": "X/Y", "ok": True, "detail": "IMAGE"}, {"key": "b", "id": "X/Z", "ok": False, "detail": "not found"}]
    r = _run_verify(monkeypatch, res)
    assert r.exit_code == 1, r.output
    assert "FAIL" in r.output
