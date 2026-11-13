import numpy as np
import pytest

from gsop import weights as W
from gsop.config import load_all

CFG = load_all()

MOON = [0.3042, 0.1806, 0.1483, 0.1198, 0.1141, 0.0608, 0.0532, 0.0190]
MARS = [0.2289, 0.1937, 0.1497, 0.1132, 0.0906, 0.0792, 0.0755, 0.0377, 0.0314]


@pytest.mark.parametrize("body,expected", [("moon", MOON), ("mars", MARS)])
def test_derived_weights_match_plan(body, expected):
    d = W.derive_weights(CFG["weights"][body])
    assert list(d.values()) == pytest.approx(expected, abs=6e-5)
    assert sum(d.values()) == pytest.approx(1.0)


@pytest.mark.parametrize("body", ["moon", "mars"])
def test_within_tolerance_of_published(body):
    diff = W.check_against_published(CFG["weights"][body], CFG["weights"]["published_tolerance"])
    assert max(diff.values()) < CFG["weights"]["published_tolerance"]


def test_moon_thermal_inertia_is_0_019_not_published_0_03():
    d = W.derive_weights(CFG["weights"]["moon"])
    assert d["thermal_inertia"] == pytest.approx(0.019, abs=5e-4)
    assert CFG["weights"]["moon"]["thermal_inertia"]["published"] == 0.03


def test_draw_weights_within_range_before_renormalising_and_sum_to_one():
    rng = np.random.default_rng(1)
    ranges = {f: tuple(v["range"]) for f, v in CFG["weights"]["moon"].items()}
    for _ in range(50):
        w = W.draw_weights(rng, ranges, {})
        assert sum(w.values()) == pytest.approx(1.0)
        assert all(v > 0 for v in w.values())


def test_purpose_multipliers_raise_the_right_families():
    base = W.derive_weights(CFG["weights"]["moon"])
    lm = W.profile_weights(CFG["weights"]["moon"], CFG["purposes"], "landing_mobility", "moon")
    assert lm["slope"] > base["slope"] and lm["illumination"] < base["illumination"]
    assert sum(lm.values()) == pytest.approx(1.0)


def test_no_moon_life_profile_and_mars_has_four_plus_base():
    assert "geology_life" not in CFG["purposes"]["profiles"]["moon"]
    assert len(CFG["purposes"]["profiles"]["mars"]) == 5
    with pytest.raises(ValueError):
        W.profile_multipliers(CFG["purposes"], "geology_life", "moon")


def test_alt_sets():
    moon = W.alt_weight_sets("moon", CFG["weights"])
    assert moon["no_illumination"]["illumination"] == 0.0
    assert sum(moon["no_illumination"].values()) == pytest.approx(1.0)
    assert moon["liu2025"]["relief"] == 0.0
    assert W.alt_weight_sets("mars", CFG["weights"])["mashal2025"]["composition"] == pytest.approx(0.75)
