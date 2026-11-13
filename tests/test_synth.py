"""A21: the synthetic grid is deterministic and its planted tiles behave as the docstring says."""

import numpy as np
import pandas as pd
import pytest

from gsop import gates as G
from gsop import pipeline as P
from gsop.config import load_all
from gsop.provenance import config_hash
from synth import IDS, SINGLE_FAMILY_BASE, SINGLE_FAMILY_ORDER, TARGET_VALUES, make_synth

CFG = load_all()


@pytest.fixture(scope="module")
def s():
    return make_synth()


def _frame_hash(df):
    return int(pd.util.hash_pandas_object(df, index=True).sum() % (1 << 62))


def test_defaults_and_columns(s):
    assert len(s.earth) == 20_000
    assert (s.earth["tile_id"].to_numpy() == np.arange(20_000)).all()
    for c in list(TARGET_VALUES) + ["lat", "lon", "water_ice_frac", "ndvi_median", "built_crop_frac"]:
        assert c in s.earth.columns


def test_deterministic_for_a_seed_and_different_across_seeds():
    a, b, c = make_synth(2000, 5), make_synth(2000, 5), make_synth(2000, 6)
    assert _frame_hash(a.earth) == _frame_hash(b.earth)
    assert config_hash(a.targets) == config_hash(b.targets)
    assert a.truth == b.truth
    assert _frame_hash(a.earth) != _frame_hash(c.earth)


def test_too_small_n_is_refused():
    with pytest.raises(ValueError):
        make_synth(999)


def test_planted_ids_are_stable_when_n_grows():
    assert make_synth(1000).truth == make_synth(5000).truth


def test_exact_tile_equals_the_target_on_every_column(s):
    row = s.earth.loc[IDS["exact"]]
    for c, v in TARGET_VALUES.items():
        assert row[c] == v
    assert row["water_ice_frac"] == 0 and row["ndvi_median"] < 0.2 and row["built_crop_frac"] == 0


def test_single_family_tiles_match_exactly_one_family(s):
    for i, fam in enumerate(SINGLE_FAMILY_ORDER):
        row = s.earth.loc[SINGLE_FAMILY_BASE + i]
        for c in TARGET_VALUES:
            if c in s.family_columns[fam]:
                assert row[c] == TARGET_VALUES[c]
        assert any(row[c] != TARGET_VALUES[c] for c in TARGET_VALUES if c not in s.family_columns[fam])
        assert s.truth[f"single_family_{fam}"] == [SINGLE_FAMILY_BASE + i]


@pytest.mark.parametrize("body", ["moon", "mars"])
def test_engine_finds_the_planted_analog_and_rejects_the_traps(s, body):
    job = P.prepare_job(body, "t1", "base", CFG, s.earth, s.targets[body])
    g = job.gate_df.set_index("tile_id")
    reasons = {"gated_water": "open_water_or_ice", "gated_ndvi": "vegetated", "gated_built": "built_or_cropland",
               "missing_feature": "missing_data", "missing_water_index": "missing_data",
               "missing_gate_layer": "missing_data"}
    for role, why in reasons.items():
        assert g.loc[IDS[role], "reason"] == why, role
    score, _, _ = P.base_score(job)
    tid = s.earth["tile_id"].to_numpy()[job.gated_rows]
    sc = pd.Series(score, index=tid).sort_values(ascending=False)
    assert sc.index[0] == IDS["exact"] and sc.iloc[0] == pytest.approx(100.0, abs=1e-3)
    assert sc.index[1] == IDS["near_miss"]
    fams = {f for f in SINGLE_FAMILY_ORDER if f in job.fam_cols}
    for i, fam in enumerate(SINGLE_FAMILY_ORDER):
        if fam in fams:
            tile = SINGLE_FAMILY_BASE + i
            assert tile in sc.index                       # passes the gates
            assert sc.loc[tile] < 0.5 * sc.iloc[0]        # one family alone is far below the exact analog


def test_mars_profile_passes_its_own_target_check(s):
    job = P.prepare_job("mars", "t1", "base", CFG, s.earth, s.targets["mars"])
    assert job.mars_check["fails_own_gate"] is False
