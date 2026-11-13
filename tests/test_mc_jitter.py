"""C16: data jitter in the Monte Carlo. Target value noise, Earth systematic bias, separate seed streams."""

import logging

import numpy as np
import pytest

from gsop import montecarlo as MC


def spec(meas=None, earth=None, cols=("a", "b", "c")):
    cols = list(cols)
    return MC.MCSpec(columns=cols, families={"f1": cols[:2], "f2": cols[2:]}, ranges={"f1": (0.3, 0.5), "f2": (0.5, 0.7)},
                     multipliers={}, target={c: 10.0 * (i + 1) for i, c in enumerate(cols)}, meas_unc=meas or {},
                     earth_unc=earth or {}, sigma={c: 1.0 for c in cols})


def test_zero_uncertainty_jitter_is_the_identity():
    s = spec()
    for r in range(50):
        _, t = MC.draw_run(s, r)
        assert t == s.target
    s0 = spec({"a": 0.0, "b": 0.0, "c": 0.0}, {"a": 0.0})
    assert MC.draw_run(s0, 3)[1] == s0.target


def test_target_value_is_normal_around_the_configured_value():
    s = spec(meas={"a": 2.0, "b": 0.5})
    t = np.array([[MC.draw_run(s, r)[1][c] for c in "abc"] for r in range(20_000)])
    assert t[:, 0].mean() == pytest.approx(10.0, abs=0.06) and t[:, 0].std() == pytest.approx(2.0, rel=0.03)
    assert t[:, 1].mean() == pytest.approx(20.0, abs=0.02) and t[:, 1].std() == pytest.approx(0.5, rel=0.03)
    assert (t[:, 2] == 30.0).all()                               # no uncertainty: untouched


def test_earth_bias_shifts_the_target_by_minus_the_bias():
    s = spec(earth={"c": 1.5})
    t = np.array([MC.draw_run(s, r)[1]["c"] for r in range(20_000)])
    assert t.mean() == pytest.approx(30.0, abs=0.03) and t.std() == pytest.approx(1.5, rel=0.03)
    rw, rt, rb = MC.run_streams(s.master_seed, 4)
    rt.standard_normal(3)
    y = rb.standard_normal(3)
    assert MC.draw_run(s, 4)[1]["c"] == pytest.approx(30.0 - 1.5 * y[2])


def test_measurement_and_earth_draws_are_independent():
    s = spec(meas={"a": 1.0}, earth={"a": 1.0})
    both = np.array([MC.draw_run(s, r)[1]["a"] - 10.0 for r in range(20_000)])
    assert both.std() == pytest.approx(np.sqrt(2.0), rel=0.03)    # variances add: independent streams
    zs = np.array([MC.run_streams(s.master_seed, r)[1].standard_normal() for r in range(5000)])
    ys = np.array([MC.run_streams(s.master_seed, r)[2].standard_normal() for r in range(5000)])
    assert abs(np.corrcoef(zs, ys)[0, 1]) < 0.05


def test_weights_and_data_streams_never_overlap_and_adding_uncertainty_changes_no_other_draw():
    base = spec()
    w0 = MC.weights_for_run(base, 9)
    withunc = spec(meas={"b": 3.0}, earth={"a": 2.0})
    assert MC.weights_for_run(withunc, 9) == w0
    t0, t1 = MC.draw_run(base, 9)[1], MC.draw_run(withunc, 9)[1]
    assert t1["c"] == t0["c"]                                     # column c has no uncertainty either way
    ss = MC.run_streams(base.master_seed, 9)
    firsts = [g.bit_generator.state["state"]["state"] for g in MC.run_streams(base.master_seed, 9)]
    assert len(set(firsts)) == 3 and len(ss) == 3


def test_jitter_is_reproducible_by_run_id():
    s = spec(meas={"a": 1.0, "b": 1.0})
    assert MC.draw_run(s, 12) == MC.draw_run(spec(meas={"a": 1.0, "b": 1.0}), 12)
    assert MC.draw_run(s, 12)[1] != MC.draw_run(s, 13)[1]


def test_report_says_exactly_what_is_and_is_not_jittered():
    r = MC.jitter_report(spec(meas={"a": 2.0}, earth={"b": 1.0}))
    assert r["not_jittered"] == ["c"]
    assert r["columns"]["a"] == {"measurement_unc": 2.0, "earth_unc": 0.0, "jittered": True}
    assert r["columns"]["b"]["jittered"] is True
    assert "per_tile_noise" in r and "not applied" in r["per_tile_noise"]


def test_unjittered_columns_are_logged_once(caplog):
    MC._LOGGED_NO_JITTER.clear()
    s = spec(meas={"a": 2.0})
    with caplog.at_level(logging.INFO, logger="gsop.montecarlo"):
        assert MC.log_unjittered_once(s) == ["b", "c"]
        MC.log_unjittered_once(s)
        MC.log_unjittered_once(s)
    msgs = [m for m in caplog.messages if "no jitter on b, c" in m]
    assert len(msgs) == 1 and "TODO" in msgs[0]
