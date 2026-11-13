"""Config loading and validation. All numbers live in config/*.yaml; code reads them, never hard-codes them.

`load_all()` returns the plain dict of parsed files (what the engine and the tests use). It validates first:
a broken config stops with one readable line that names the file and the key (`ConfigError`). Keys the schema does
not know produce a `ConfigWarning`, never an error. `Config` wraps the same dict with typed accessors
(`cfg.weights("moon")`, `cfg.run.seed`) and the config hash.

The hash is sha256 over the canonical JSON of the parsed config (sorted keys, no whitespace, shortest-repr floats).
Files are read as UTF-8 with any BOM removed and CRLF / CR turned into LF before parsing, so a Windows checkout
(`core.autocrlf`) and a macOS checkout give the same hash.
"""

from __future__ import annotations

import math
import re
import warnings
from pathlib import Path
from typing import Any

import yaml

from .provenance import ROOT, config_hash

CONFIG_DIR = ROOT / "config"
NAMES = ("weights", "gates", "purposes", "targets", "known_sites", "ledger", "features", "run")
BODIES = ("moon", "mars")


class ConfigError(ValueError):
    """The config is broken. The message is one line: file, key path and what is wrong."""


class ConfigWarning(UserWarning):
    """A key the schema does not know about. Never fatal."""


# --------------------------------------------------------------------------- reading

def read_text(path: Path | str) -> str:
    """UTF-8 text with the BOM dropped and every line ending turned into LF."""
    raw = Path(path).read_bytes().decode("utf-8-sig")
    return raw.replace("\r\n", "\n").replace("\r", "\n")


def load_yaml(path: Path | str) -> Any:
    try:
        return yaml.safe_load(read_text(path))
    except yaml.YAMLError as e:
        raise ConfigError(f"{Path(path).name}: not valid YAML ({str(e).splitlines()[0]})") from e


def load_raw(config_dir: Path | str | None = None) -> dict[str, Any]:
    d = Path(config_dir) if config_dir else CONFIG_DIR
    out: dict[str, Any] = {}
    for n in NAMES:
        p = d / f"{n}.yaml"
        if not p.exists():
            raise ConfigError(f"{n}.yaml: file not found in {d}")
        out[n] = load_yaml(p)
        if not isinstance(out[n], dict):
            raise ConfigError(f"{n}.yaml: top level must be a mapping")
    return out


# --------------------------------------------------------------------------- validation

class _Check:
    """Collects problems. `file` is the yaml file name, `path` the dotted key path."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, file: str, path: str, msg: str) -> None:
        self.errors.append(f"{file}: {path}: {msg}" if path else f"{file}: {msg}")

    def warn(self, file: str, path: str, msg: str) -> None:
        self.warnings.append(f"{file}: {path}: {msg}" if path else f"{file}: {msg}")

    def unknown(self, file: str, path: str, d: dict, known: set[str]) -> None:
        for k in d:
            if k not in known:
                self.warn(file, f"{path}.{k}" if path else str(k), "unknown key, ignored")

    def mapping(self, file: str, path: str, v: Any) -> bool:
        if not isinstance(v, dict):
            self.err(file, path, f"must be a mapping, got {type(v).__name__}")
            return False
        return True

    def require(self, file: str, path: str, d: dict, key: str, kinds: type | tuple, label: str | None = None) -> Any:
        p = f"{path}.{key}" if path else key
        if key not in d:
            self.err(file, p, "missing required key")
            return None
        v = d[key]
        if not _is(v, kinds):
            self.err(file, p, f"must be {label or _kname(kinds)}, got {type(v).__name__} ({v!r})")
            return None
        return v


def _is(v: Any, kinds: type | tuple) -> bool:
    ks = kinds if isinstance(kinds, tuple) else (kinds,)
    if bool in ks:
        return isinstance(v, bool)
    if isinstance(v, bool):                       # a bool is never a number here
        return False
    return isinstance(v, ks) and not (isinstance(v, float) and not math.isfinite(v))


def _kname(kinds: type | tuple) -> str:
    ks = kinds if isinstance(kinds, tuple) else (kinds,)
    if set(ks) == {int, float}:
        return "a number"
    return " or ".join({int: "an integer", float: "a number", str: "a string", bool: "true/false",
                        list: "a list", dict: "a mapping"}.get(k, k.__name__) for k in ks)


NUM = (int, float)
_EXPR = re.compile(r"^\s*\w+\s*(<=|>=|<|>)\s*[0-9.eE+-]+\s*$")


def _validate_weights(c: _Check, w: dict) -> set[str]:
    f = "weights.yaml"
    families: set[str] = set()
    for body in BODIES:
        if body not in w:
            c.err(f, body, "missing required key")
            continue
        if not c.mapping(f, body, w[body]):
            continue
        for fam, spec in w[body].items():
            p = f"{body}.{fam}"
            families.add(str(fam))
            if not c.mapping(f, p, spec):
                continue
            ps = c.require(f, p, spec, "paper_score", NUM)
            if ps is not None and ps <= 0:
                c.err(f, f"{p}.paper_score", f"must be > 0, got {ps}")
            m = c.require(f, p, spec, "matchability", NUM)
            if m is not None and not 0 < m <= 1:
                c.err(f, f"{p}.matchability", f"must be in (0, 1], got {m}")
            rg = c.require(f, p, spec, "range", list, "a [lo, hi] list")
            if rg is not None:
                if len(rg) != 2 or not all(_is(x, NUM) for x in rg):
                    c.err(f, f"{p}.range", f"must be two numbers [lo, hi], got {rg!r}")
                elif not rg[0] < rg[1]:
                    c.err(f, f"{p}.range", f"lo must be < hi, got {rg!r}")
                elif rg[0] < 0:
                    c.err(f, f"{p}.range", f"weights cannot be negative, got {rg!r}")
            pub = c.require(f, p, spec, "published", NUM)
            if pub is not None and not 0 <= pub <= 1:
                c.err(f, f"{p}.published", f"must be in [0, 1], got {pub}")
            cols = c.require(f, p, spec, "columns", list, "a list of column names")
            if cols is not None and (not cols or not all(isinstance(x, str) for x in cols)):
                c.err(f, f"{p}.columns", f"must be a non-empty list of strings, got {cols!r}")
            c.unknown(f, p, spec, {"paper_score", "matchability", "range", "published", "columns"})
    tol = w.get("published_tolerance")
    if tol is not None and not _is(tol, NUM):
        c.err(f, "published_tolerance", f"must be a number, got {tol!r}")
    alt = w.get("alt_weight_sets")
    if alt is not None and c.mapping(f, "alt_weight_sets", alt):
        for body, sets in alt.items():
            if body not in BODIES:
                c.err(f, f"alt_weight_sets.{body}", "unknown body")
                continue
            for name, spec in (sets or {}).items():
                if isinstance(spec, dict) and "weights" in spec:
                    for fam in spec["weights"]:
                        if fam not in (w.get(body) or {}):
                            c.err(f, f"alt_weight_sets.{body}.{name}.weights.{fam}", f"unknown {body} family")
    c.unknown(f, "", w, set(BODIES) | {"published_tolerance", "alt_weight_sets"})
    return families


def _validate_purposes(c: _Check, p: dict, families: set[str]) -> None:
    f = "purposes.yaml"
    names = set()
    purposes = p.get("purposes")
    if c.require(f, "", p, "purposes", dict) is not None:
        for name, spec in purposes.items():
            names.add(str(name))
            path = f"purposes.{name}"
            if not c.mapping(f, path, spec):
                continue
            mult = c.require(f, path, spec, "multipliers", dict)
            for fam, v in (mult or {}).items():
                if fam not in families:
                    c.err(f, f"{path}.multipliers.{fam}", f"unknown family (known: {', '.join(sorted(families))})")
                elif not _is(v, NUM) or v <= 0:
                    c.err(f, f"{path}.multipliers.{fam}", f"must be a number > 0, got {v!r}")
            eg = spec.get("extra_gate")
            if eg is not None and c.mapping(f, f"{path}.extra_gate", eg):
                for body, expr in eg.items():
                    if body not in BODIES:
                        c.err(f, f"{path}.extra_gate.{body}", "unknown body")
                    elif not isinstance(expr, str) or not _EXPR.match(expr):
                        c.err(f, f"{path}.extra_gate.{body}", f"must look like 'slope_med <= 8', got {expr!r}")
            bodies = spec.get("bodies")
            if bodies is not None and (not isinstance(bodies, list) or not set(bodies) <= set(BODIES)):
                c.err(f, f"{path}.bodies", f"must be a list drawn from {list(BODIES)}, got {bodies!r}")
            c.unknown(f, path, spec, {"multipliers", "extra_gate", "bodies"})
    prof = c.require(f, "", p, "profiles", dict)
    for body, lst in (prof or {}).items():
        if body not in BODIES:
            c.err(f, f"profiles.{body}", "unknown body")
        elif not isinstance(lst, list) or not all(isinstance(x, str) for x in lst):
            c.err(f, f"profiles.{body}", "must be a list of profile names")
        else:
            if "base" not in lst:
                c.err(f, f"profiles.{body}", "must include 'base'")
            for x in lst:
                if x != "base" and x not in names:
                    c.err(f, f"profiles.{body}", f"unknown purpose {x!r}")
    for body in BODIES:
        if prof is not None and body not in prof:
            c.err(f, f"profiles.{body}", "missing required key")
    co = p.get("confidence_overrides") or {}
    if c.mapping(f, "confidence_overrides", co):
        for body, m in co.items():
            for prof_name, level in (m or {}).items():
                if prof_name not in names:
                    c.err(f, f"confidence_overrides.{body}.{prof_name}", "unknown purpose")
                elif level not in ("low", "standard"):
                    c.err(f, f"confidence_overrides.{body}.{prof_name}", f"must be low or standard, got {level!r}")
    c.unknown(f, "", p, {"profiles", "purposes", "confidence_overrides"})


def _validate_gates(c: _Check, g: dict) -> None:
    f = "gates.yaml"
    tg = c.require(f, "", g, "tile_gates", dict)
    if tg is not None:
        for k in ("open_water_or_ice_frac_max", "ndvi_median_max", "built_or_crop_frac_max"):
            v = c.require(f, "tile_gates", tg, k, NUM)
            if v is not None and not -1 <= v <= 1:
                c.err(f, f"tile_gates.{k}", f"must be in [-1, 1], got {v}")
        c.unknown(f, "tile_gates", tg, {"open_water_or_ice_frac_max", "ndvi_median_max", "built_or_crop_frac_max"})
    nm = g.get("near_miss_frac", 0.10)
    if not _is(nm, NUM) or not 0 <= nm < 1:
        c.err(f, "near_miss_frac", f"must be a number in [0, 1), got {nm!r}")
    mc = c.require(f, "", g, "mars_target_check", dict)
    if mc is not None:
        mode = c.require(f, "mars_target_check", mc, "mode", str)
        if mode is not None and mode not in ("warn", "strict"):
            c.err(f, "mars_target_check.mode", f"must be warn or strict, got {mode!r}")
        for k in ("lat_abs_max_deg", "elevation_m_max", "thermal_inertia_si_min"):
            c.require(f, "mars_target_check", mc, k, NUM)
        c.unknown(f, "mars_target_check", mc, {"mode", "lat_abs_max_deg", "elevation_m_max", "thermal_inertia_si_min"})
    c.unknown(f, "", g, {"tile_gates", "mars_target_check", "near_miss_frac"})


def _lat_lon(c: _Check, f: str, p: str, s: dict, lon_key: str, allow_null: bool) -> None:
    for key, lo, hi in (("lat", -90, 90), (lon_key, -360, 360)):
        v = s.get(key)
        if v is None and allow_null and key in s:
            continue
        if not _is(v, NUM):
            c.err(f, f"{p}.{key}", f"must be a number{' or null' if allow_null else ''}, got {v!r}")
        elif not lo <= v <= hi:
            c.err(f, f"{p}.{key}", f"out of range [{lo}, {hi}], got {v}")
    if allow_null and (s.get("lat") is None) != (s.get(lon_key) is None):
        c.err(f, p, f"lat and {lon_key} must both be set or both be null")


def _validate_targets(c: _Check, t: dict) -> None:
    f = "targets.yaml"
    for body in BODIES:
        if body not in t:
            c.err(f, body, "missing required key")
        elif c.mapping(f, body, t[body]):
            for name, s in t[body].items():
                if c.mapping(f, f"{body}.{name}", s):
                    _lat_lon(c, f, f"{body}.{name}", s, "lon_e", allow_null=True)
    w = c.require(f, "", t, "target_window_km", NUM)
    if w is not None and w <= 0:
        c.err(f, "target_window_km", f"must be > 0, got {w}")
    rm = t.get("read_margin_km")
    if rm is not None and (not _is(rm, NUM) or rm < 0):
        c.err(f, "read_margin_km", f"must be a number >= 0, got {rm!r}")


def _validate_sites(c: _Check, ks: dict) -> None:
    f = "known_sites.yaml"
    for grp in ("primary", "secondary", "gate_tests", "negative_controls"):
        if grp not in ks:
            c.err(f, grp, "missing required key")
            continue
        if not c.mapping(f, grp, ks[grp]):
            continue
        for name, s in ks[grp].items():
            p = f"{grp}.{name}"
            if not c.mapping(f, p, s):
                continue
            _lat_lon(c, f, p, s, "lon", allow_null=False)
            if grp in ("primary", "secondary"):
                b = c.require(f, p, s, "bodies", list)
                if b is not None and (not b or not set(b) <= set(BODIES)):
                    c.err(f, f"{p}.bodies", f"must be a non-empty list drawn from {list(BODIES)}, got {b!r}")
            if "confirmed" in s and not isinstance(s["confirmed"], bool):
                c.err(f, f"{p}.confirmed", f"must be true/false, got {s['confirmed']!r}")
            if "radius_km" in s and (not _is(s["radius_km"], NUM) or s["radius_km"] <= 0):
                c.err(f, f"{p}.radius_km", f"must be a number > 0, got {s['radius_km']!r}")
            c.unknown(f, p, s, {"lat", "lon", "bodies", "confirmed", "radius_km", "expect"})
    cr = c.require(f, "", ks, "criteria", dict)
    if cr is not None:
        for k in ("primary_median_rank_pct_min", "negative_control_rank_pct_max"):
            v = c.require(f, "criteria", cr, k, NUM)
            if v is not None and not 0 <= v <= 100:
                c.err(f, f"criteria.{k}", f"must be a percentile in [0, 100], got {v}")
        c.require(f, "criteria", cr, "gate_tests_all_rejected", bool)
        c.unknown(f, "criteria", cr, {"primary_median_rank_pct_min", "negative_control_rank_pct_max",
                                      "gate_tests_all_rejected"})
    c.unknown(f, "", ks, {"primary", "secondary", "gate_tests", "negative_controls", "criteria"})


def _validate_ledger(c: _Check, lg: dict) -> None:
    f = "ledger.yaml"
    sv = c.require(f, "", lg, "status_value", dict)
    for k in ("broken", "partly", "matchable"):
        if sv is not None:
            v = c.require(f, "status_value", sv, k, NUM)
            if v is not None and not 0 <= v <= 1:
                c.err(f, f"status_value.{k}", f"must be in [0, 1], got {v}")
    rows = c.require(f, "", lg, "rows", list)
    ids = set()
    for i, r in enumerate(rows or []):
        p = f"rows[{i}]"
        if not c.mapping(f, p, r):
            continue
        rid = c.require(f, p, r, "id", str)
        if rid in ids:
            c.err(f, f"{p}.id", f"duplicate id {rid!r}")
        ids.add(rid)
        st = c.require(f, p, r, "status", str)
        if st is not None and sv is not None and st not in sv:
            c.err(f, f"{p}.status", f"must be one of {sorted(sv)}, got {st!r}")
        b = c.require(f, p, r, "bodies", list)
        if b is not None and not set(b) <= set(BODIES):
            c.err(f, f"{p}.bodies", f"must be drawn from {list(BODIES)}, got {b!r}")
        c.unknown(f, p, r, {"id", "property", "target", "earth", "status", "bodies", "source", "provisional"})
    rel = lg.get("relevance")
    if rel is not None and c.mapping(f, "relevance", rel):
        for purpose, spec in rel.items():
            rr = spec.get("rows") if isinstance(spec, dict) else None
            if isinstance(rr, list):
                for x in rr:
                    if x not in ids:
                        c.err(f, f"relevance.{purpose}.rows", f"unknown ledger row id {x!r}")
            elif rr != "all":
                c.err(f, f"relevance.{purpose}.rows", f"must be 'all' or a list of row ids, got {rr!r}")
    c.unknown(f, "", lg, {"status_value", "rows", "relevance_provisional", "relevance"})


def _validate_features(c: _Check, ft: dict) -> None:
    f = "features.yaml"
    op = c.require(f, "", ft, "operator", dict)
    if op is not None:
        for k in ("slope_baseline_m", "rough_a_baseline_m", "rough_b_baseline_m", "tile_m"):
            v = c.require(f, "operator", op, k, NUM)
            if v is not None and v <= 0:
                c.err(f, f"operator.{k}", f"must be > 0, got {v}")
    cols = c.require(f, "", ft, "columns", dict)
    for name, spec in (cols or {}).items():
        if c.mapping(f, f"columns.{name}", spec):
            c.require(f, f"columns.{name}", spec, "unit", str)


def _validate_run(c: _Check, r: dict) -> None:
    f = "run.yaml"
    seed = c.require(f, "", r, "master_seed", int)
    if seed is not None and seed < 0:
        c.err(f, "master_seed", f"must be >= 0, got {seed}")
    for k in ("runs", "batch_runs", "tile_m"):
        v = c.require(f, "", r, k, int if k != "tile_m" else NUM)
        if v is not None and v <= 0:
            c.err(f, k, f"must be > 0, got {v}")
    tf = c.require(f, "", r, "top_fracs", list)
    if tf is not None and (not tf or not all(_is(x, NUM) and 0 < x <= 1 for x in tf)):
        c.err(f, "top_fracs", f"must be a non-empty list of fractions in (0, 1], got {tf!r}")
    rb = c.require(f, "", r, "robust", dict)
    if rb is not None:
        mem = c.require(f, "robust", rb, "membership", str)
        if mem is not None and not re.fullmatch(r"top\d+(\.\d+)?", mem):
            c.err(f, "robust.membership", f"must look like 'top5', got {mem!r}")
        mf = c.require(f, "robust", rb, "min_freq", NUM)
        if mf is not None and not 0 < mf <= 1:
            c.err(f, "robust.min_freq", f"must be in (0, 1], got {mf}")
    cd = c.require(f, "", r, "candidates", dict)
    if cd is not None:
        tfc = c.require(f, "candidates", cd, "top_frac", NUM)
        if tfc is not None and not 0 < tfc <= 1:
            c.err(f, "candidates.top_frac", f"must be in (0, 1], got {tfc}")
        c.require(f, "candidates", cd, "max_candidates", int)
    rf = c.require(f, "", r, "ram_fraction", NUM)
    if rf is not None and not 0 < rf <= 1:
        c.err(f, "ram_fraction", f"must be in (0, 1], got {rf}")
    rad = c.require(f, "", r, "site_match_radius_km", NUM)
    if rad is not None and rad <= 0:
        c.err(f, "site_match_radius_km", f"must be > 0, got {rad}")
    for k in ("discovery", "ml", "compare"):
        c.require(f, "", r, k, dict)
    cp = c.require(f, "", r, "convergence_checkpoints", list)
    if cp is not None and not all(isinstance(x, int) and x > 0 for x in cp):
        c.err(f, "convergence_checkpoints", f"must be a list of positive integers, got {cp!r}")
    tl = r.get("tiles")
    if tl is not None and c.mapping(f, "tiles", tl):
        for k in ("expected_land_tiles", "chunk_rows"):
            v = c.require(f, "tiles", tl, k, int)
            if v is not None and v <= 0:
                c.err(f, f"tiles.{k}", f"must be > 0, got {v}")
        ff = c.require(f, "tiles", tl, "far_off_frac", NUM)
        if ff is not None and not 0 < ff < 1:
            c.err(f, "tiles.far_off_frac", f"must be in (0, 1), got {ff}")
        c.unknown(f, "tiles", tl, {"expected_land_tiles", "far_off_frac", "chunk_rows"})
    dc = r.get("drop_columns")
    if dc is not None and not (isinstance(dc, list) and all(isinstance(x, str) for x in dc)):
        c.err(f, "drop_columns", f"must be a list of column names, got {dc!r}")
    c.unknown(f, "", r, {"master_seed", "runs", "batch_runs", "tile_m", "grid_crs", "top_fracs", "robust", "candidates",
                         "convergence_checkpoints", "ram_fraction", "site_match_radius_km", "discovery", "ml",
                         "compare", "drop_columns", "operator_check", "tiles"})


def check(cfg: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Returns (errors, warnings) for a parsed config dict. Never raises."""
    c = _Check()
    for n in NAMES:
        if n not in cfg:
            c.err(f"{n}.yaml", "", "missing")
    if c.errors:
        return c.errors, c.warnings
    families = _validate_weights(c, cfg["weights"])
    _validate_purposes(c, cfg["purposes"], families)
    _validate_gates(c, cfg["gates"])
    _validate_targets(c, cfg["targets"])
    _validate_sites(c, cfg["known_sites"])
    _validate_ledger(c, cfg["ledger"])
    _validate_features(c, cfg["features"])
    _validate_run(c, cfg["run"])
    return c.errors, c.warnings


def validate(cfg: dict[str, Any]) -> list[str]:
    """Raises ConfigError (one line, all problems joined by ' | ') or returns the list of warnings, which are also
    emitted as ConfigWarning."""
    errors, warns = check(cfg)
    if errors:
        n = len(errors)
        raise ConfigError(f"{n} config problem{'s' if n > 1 else ''}: " + " | ".join(errors))
    for w in warns:
        warnings.warn(w, ConfigWarning, stacklevel=3)
    return warns


def load_all(config_dir: Path | str | None = None, validate_config: bool = True) -> dict[str, Any]:
    cfg = load_raw(config_dir)
    if validate_config:
        validate(cfg)
    return cfg


def cfg_hash(cfg: dict[str, Any]) -> str:
    return config_hash(cfg)


# --------------------------------------------------------------------------- typed access

class RunConfig:
    """`cfg.run.seed`, `cfg.run.runs`, ... Any key of run.yaml is an attribute; `seed` is master_seed."""

    def __init__(self, d: dict[str, Any]):
        self._d = d

    @property
    def seed(self) -> int:
        return int(self._d["master_seed"])

    def __getattr__(self, name: str) -> Any:
        try:
            return self._d[name]
        except KeyError:
            raise AttributeError(f"run.yaml has no key {name!r}") from None

    def __getitem__(self, key: str) -> Any:
        return self._d[key]


class Config:
    """Validated config with typed accessors. `Config.load()` reads `config/`; `Config(dict)` wraps a parsed dict."""

    def __init__(self, raw: dict[str, Any], validate_config: bool = True):
        if validate_config:
            validate(raw)
        self.raw = raw

    @classmethod
    def load(cls, config_dir: Path | str | None = None) -> "Config":
        return cls(load_raw(config_dir))

    @property
    def hash(self) -> str:
        return cfg_hash(self.raw)

    def weights(self, body: str) -> dict[str, Any]:
        return self.raw["weights"][_body(body)]

    def alt_weight_sets(self, body: str) -> dict[str, Any]:
        return self.raw["weights"]["alt_weight_sets"][_body(body)]

    def profiles(self, body: str) -> list[str]:
        return list(self.raw["purposes"]["profiles"][_body(body)])

    def targets(self, body: str) -> dict[str, Any]:
        return self.raw["targets"][_body(body)]

    @property
    def gates(self) -> dict[str, Any]:
        return self.raw["gates"]

    @property
    def purposes(self) -> dict[str, Any]:
        return self.raw["purposes"]

    @property
    def known_sites(self) -> dict[str, Any]:
        return self.raw["known_sites"]

    @property
    def ledger(self) -> dict[str, Any]:
        return self.raw["ledger"]

    @property
    def features(self) -> dict[str, Any]:
        return self.raw["features"]

    @property
    def run(self) -> RunConfig:
        return RunConfig(self.raw["run"])


def _body(body: str) -> str:
    if body not in BODIES:
        raise ConfigError(f"body must be one of {list(BODIES)}, got {body!r}")
    return body


def data_dir(sub: str) -> Path:
    p = ROOT / "data" / sub
    p.mkdir(parents=True, exist_ok=True)
    return p


def results_dir(body: str | None = None) -> Path:
    p = ROOT / "results" / body if body else ROOT / "results"
    p.mkdir(parents=True, exist_ok=True)
    return p
