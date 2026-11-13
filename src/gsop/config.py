"""Config loading. All numbers live in config/*.yaml; code reads them, never hard-codes them."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .provenance import ROOT, config_hash

CONFIG_DIR = ROOT / "config"
NAMES = ("weights", "gates", "purposes", "targets", "known_sites", "ledger", "features", "run")


def load_yaml(path: Path | str) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_all(config_dir: Path | str | None = None) -> dict[str, Any]:
    d = Path(config_dir) if config_dir else CONFIG_DIR
    return {n: load_yaml(d / f"{n}.yaml") for n in NAMES}


def cfg_hash(cfg: dict[str, Any]) -> str:
    return config_hash(cfg)


def data_dir(sub: str) -> Path:
    p = ROOT / "data" / sub
    p.mkdir(parents=True, exist_ok=True)
    return p


def results_dir(body: str | None = None) -> Path:
    p = ROOT / "results" / body if body else ROOT / "results"
    p.mkdir(parents=True, exist_ok=True)
    return p
