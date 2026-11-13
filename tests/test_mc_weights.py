"""C15: per-run weight draws. Uniform in range, renormalise, purpose multipliers, renormalise; reproducible per run."""

import copy

import numpy as np
import pytest

from gsop import montecarlo as MC
from gsop import weights as W
from gsop.config import load_all

CFG = load_all()
MASTER = 20261114


def spec_for(body="moon", profile="base", **kw):
    bc = CFG["weights"][body]
    fam = {f: v["columns"] for f, v in bc.items()}
    cols = list(dict.fromkeys(c for v in fam.values() for c in v))
    return MC.MCSpec(columns=cols, families=fam, ranges={f: tuple(v["range"]) for f, v in bc.items()},
                     multipliers=W.profile_multipliers(CFG["purposes"], profile, body),
                     target={c: 1.0 for c in cols}, meas_unc={c: 0.1 for c in cols}, earth_unc={}, sigma={c: 1.0 for c in cols},
                     master_seed=MASTER, **kw)


def test_run_i_uses_child_i_of_the_master_seed_sequence():
    spec = spec_for()
    kids = np.random.SeedSequence(MASTER).spawn(30)
    for i in (0, 1, 17, 29):
        rng = np.random.default_rng(kids[i].spawn(3)[0])
        expect = W.draw_weights(rng, spec.ranges, spec.multipliers)
        assert MC.weights_for_run(spec, i) == expect


def test_same_run_index_same_weights_whatever_else_ran():
    spec = spec_for()
    a = MC.weights_for_run(spec, 123)
    for i in (5, 999, 0):                      # unrelated calls in between change nothing
        MC.weights_for_run(spec, i)
    assert MC.weights_for_run(spec, 123) == a
    assert MC.draw_run(spec, 123)[0] == a      # the Monte Carlo loop sees the same vector
    assert MC.weights_for_run(copy.deepcopy(spec), 123) == a


def test_weights_do_not_depend_on_the_data_stream():
    a = spec_for()
    b = spec_for()
    b.meas_unc = {c: 5.0 for c in b.columns}
    b.earth_unc = {c: 3.0 for c in b.columns}
    b.target = {c: 99.0 for c in b.columns}
    assert MC.weights_for_run(a, 41) == MC.weights_for_run(b, 41)


@pytest.mark.parametrize("body", ["moon", "mars"])
def test_10000_draws_stay_in_range_before_renormalising_and_sum_to_one_after(body):
    spec = spec_for(body)
    for i in range(10_000):
        w, raw = MC.weights_for_run(spec, i, return_raw=True)
        for f, (lo, hi) in spec.ranges.items():
            assert lo <= raw[f] <= hi
        assert sum(w.values()) == pytest.approx(1.0, abs=1e-12)
        assert all(v > 0 for v in w.values())


def test_order_is_draw_renormalise_multiply_renormalise():
    spec = spec_for("moon", "landing_mobility")
    w, raw = MC.weights_for_run(spec, 7, return_raw=True)
    s = sum(raw.values())
    step1 = {f: v / s for f, v in raw.items()}
    step2 = {f: v * spec.multipliers.get(f, 1.0) for f, v in step1.items()}
    s2 = sum(step2.values())
    assert w == pytest.approx({f: v / s2 for f, v in step2.items()}, rel=1e-12)
    # the other order (multiply the raw draws, normalise once) differs only by a rescale, so it gives the same weights;
    # what must differ is a version that multiplies AFTER the last renormalisation, which would not sum to one
    assert sum(step2.values()) != pytest.approx(1.0)
    assert sum(w.values()) == pytest.approx(1.0)


def test_purpose_multipliers_raise_the_boosted_families():
    base = spec_for("moon", "base")
    land = spec_for("moon", "landing_mobility")
    wb = np.mean([[MC.weights_for_run(base, i)[f] for f in ("slope", "illumination")] for i in range(500)], axis=0)
    wl = np.mean([[MC.weights_for_run(land, i)[f] for f in ("slope", "illumination")] for i in range(500)], axis=0)
    assert wl[0] > wb[0] and wl[1] < wb[1]


def test_family_order_follows_weights_yaml_and_draws_are_one_scalar_per_family():
    spec = spec_for()
    rng = MC.run_streams(MASTER, 3)[0]
    expect = [rng.uniform(lo, hi) for lo, hi in spec.ranges.values()]
    _, raw = MC.weights_for_run(spec, 3, return_raw=True)
    assert list(raw) == list(CFG["weights"]["moon"]) and list(raw.values()) == expect
