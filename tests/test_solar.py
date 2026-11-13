import numpy as np
import pytest

from gsop.config import load_all
from gsop.earth.solar import sun_features

S0 = load_all()["features"]["solar"]["s0_w_m2"]


def test_equator_and_tropic_and_pole():
    f = sun_features([0.0, 23.44, 60.0, 89.9])
    assert f["sun_max_elev"][0] == pytest.approx(90.0, abs=0.7)         # equator: Sun at the zenith at the equinox
    assert f["sun_max_elev"][1] == pytest.approx(90.0, abs=0.7)         # the tropic: Sun at the zenith once a year
    assert f["sun_max_elev"][2] == pytest.approx(90 - 60 + 23.44, abs=0.4)
    assert f["sun_max_elev"][3] < 24.0                                  # pole never above the obliquity
    assert f["sun_low_share"][0] < 0.1 < f["sun_low_share"][3]          # polar Sun is low most of the time


def test_insolation_matches_the_closed_form_at_the_equator_and_is_monotonic():
    f = sun_features([0.0, 30.0, 60.0, 85.0])
    assert f["insol_annual"][0] == pytest.approx(S0 / np.pi * 0.98, rel=0.03)   # about S0/pi at the equator
    assert np.all(np.diff(f["insol_annual"]) < 0)


def test_symmetric_in_latitude_and_shape_is_kept():
    lat = np.array([[-40.0, 40.0], [10.0, -10.0]])
    f = sun_features(lat)
    assert f["sun_max_elev"].shape == lat.shape
    assert f["insol_annual"][0, 0] == pytest.approx(f["insol_annual"][0, 1], rel=1e-6)


def test_parameters_come_from_config_not_code():
    cfg = load_all()["features"]
    base = sun_features([60.0], cfg)["sun_max_elev"][0]
    tilted = {**cfg, "solar": {**cfg["solar"], "obliquity_deg": 10.0}}
    assert sun_features([60.0], tilted)["sun_max_elev"][0] == pytest.approx(90 - 60 + 10.0, abs=0.4)
    assert base == pytest.approx(90 - 60 + 23.44, abs=0.4)
    wide = {**cfg, "sun_low_threshold_deg": 30.0}
    assert sun_features([60.0], wide)["sun_low_share"][0] > sun_features([60.0], cfg)["sun_low_share"][0]
