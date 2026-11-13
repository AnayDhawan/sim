"""A06: config validation, readable errors, unknown-key warnings, a hash that does not depend on line endings."""

import copy
import shutil
import warnings
from pathlib import Path

import pytest

from gsop.config import CONFIG_DIR, NAMES, Config, ConfigError, ConfigWarning, check, load_all, load_raw, validate


@pytest.fixture()
def raw():
    return load_raw()


def test_shipped_config_is_valid_and_has_no_warnings():
    errors, warns = check(load_raw())
    assert errors == []
    assert warns == []


def test_load_all_does_not_warn_on_shipped_config():
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConfigWarning)
        load_all()


@pytest.mark.parametrize("mutate, needle", [
    (lambda c: c["weights"]["moon"]["slope"].pop("matchability"), "weights.yaml: moon.slope.matchability: missing"),
    (lambda c: c["weights"]["moon"]["slope"].__setitem__("range", [0.4, 0.2]), "moon.slope.range: lo must be < hi"),
    (lambda c: c["weights"]["moon"]["slope"].__setitem__("paper_score", "sixteen"), "moon.slope.paper_score: must be a number"),
    (lambda c: c["weights"]["moon"]["slope"].__setitem__("columns", []), "moon.slope.columns: must be a non-empty list"),
    (lambda c: c["purposes"]["purposes"]["power_night"]["multipliers"].__setitem__("no_such_family", 2),
     "purposes.power_night.multipliers.no_such_family: unknown family"),
    (lambda c: c["purposes"]["profiles"]["moon"].append("nope"), "profiles.moon: unknown purpose 'nope'"),
    (lambda c: c["targets"]["moon"]["connecting_ridge_c1"].__setitem__("lat", "south"), "lat: must be a number"),
    (lambda c: c["targets"]["moon"]["connecting_ridge_c1"].__setitem__("lat", -95.0), "lat: out of range"),
    (lambda c: c["targets"].pop("target_window_km"), "targets.yaml: target_window_km: missing"),
    (lambda c: c["run"].__setitem__("runs", "2000"), "run.yaml: runs: must be an integer"),
    (lambda c: c["run"].__setitem__("top_fracs", [0.01, 5]), "top_fracs: must be a non-empty list of fractions"),
    (lambda c: c["known_sites"]["primary"]["lonar"].__setitem__("bodies", ["venus"]), "primary.lonar.bodies"),
    (lambda c: c["ledger"]["rows"][0].__setitem__("status", "fine"), "rows[0].status: must be one of"),
    (lambda c: c["gates"]["mars_target_check"].__setitem__("mode", "maybe"), "mars_target_check.mode"),
])
def test_broken_config_fails_with_one_readable_line(raw, mutate, needle):
    cfg = copy.deepcopy(raw)
    mutate(cfg)
    with pytest.raises(ConfigError) as e:
        validate(cfg)
    msg = str(e.value)
    assert "\n" not in msg
    assert needle in msg


def test_a_bool_is_not_a_number(raw):
    raw["run"]["ram_fraction"] = True
    with pytest.raises(ConfigError, match="ram_fraction: must be a number"):
        validate(raw)


def test_all_problems_are_reported_in_one_line(raw):
    raw["run"]["runs"] = -1
    raw["gates"]["mars_target_check"]["mode"] = "x"
    with pytest.raises(ConfigError) as e:
        validate(raw)
    assert str(e.value).startswith("2 config problems")
    assert "run.yaml: runs" in str(e.value) and "gates.yaml: mars_target_check.mode" in str(e.value)


def test_unknown_keys_warn_but_do_not_fail(raw):
    raw["run"]["surprise"] = 1
    raw["weights"]["moon"]["slope"]["colour"] = "red"
    with pytest.warns(ConfigWarning) as rec:
        warns = validate(raw)
    text = " ".join(str(r.message) for r in rec)
    assert "run.yaml: surprise: unknown key" in text
    assert "weights.yaml: moon.slope.colour: unknown key" in text
    assert len(warns) == 2


def test_missing_file_is_a_config_error(tmp_path):
    for n in NAMES[:-1]:
        shutil.copy(CONFIG_DIR / f"{n}.yaml", tmp_path / f"{n}.yaml")
    with pytest.raises(ConfigError, match="run.yaml: file not found"):
        load_all(tmp_path)


def test_bad_yaml_names_the_file(tmp_path):
    for n in NAMES:
        shutil.copy(CONFIG_DIR / f"{n}.yaml", tmp_path / f"{n}.yaml")
    (tmp_path / "gates.yaml").write_text("tile_gates: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="gates.yaml: not valid YAML"):
        load_all(tmp_path)


def _copy_with_newlines(dst: Path, newline: str, bom: bool = False) -> Path:
    dst.mkdir()
    for n in NAMES:
        text = (CONFIG_DIR / f"{n}.yaml").read_bytes().decode("utf-8").replace("\r\n", "\n")
        data = text.replace("\n", newline).encode("utf-8")
        (dst / f"{n}.yaml").write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)
    return dst


def test_hash_is_identical_for_lf_crlf_and_cr_copies(tmp_path):
    h = {}
    for name, nl, bom in (("lf", "\n", False), ("crlf", "\r\n", False), ("cr", "\r", False), ("bom_crlf", "\r\n", True)):
        h[name] = Config.load(_copy_with_newlines(tmp_path / name, nl, bom)).hash
    assert len(set(h.values())) == 1, h
    assert h["lf"] == Config.load().hash


def test_hash_changes_with_one_value(raw):
    a = Config(raw).hash
    raw["run"]["runs"] += 1
    assert Config(raw).hash != a


def test_hash_ignores_key_order(raw):
    a = Config(raw).hash
    reordered = {k: raw[k] for k in reversed(list(raw))}
    reordered["run"] = {k: raw["run"][k] for k in reversed(list(raw["run"]))}
    assert Config(reordered).hash == a


def test_typed_accessors():
    cfg = Config.load()
    assert cfg.run.seed == 20261114
    assert cfg.run.runs == 2000
    assert list(cfg.weights("moon"))[0] == "slope"
    assert cfg.profiles("mars")[0] == "base"
    assert cfg.targets("mars")["jezero"]["lat"] == pytest.approx(18.4386)
    with pytest.raises(ConfigError, match="body must be one of"):
        cfg.weights("venus")
    with pytest.raises(AttributeError, match="run.yaml has no key"):
        cfg.run.no_such_key
