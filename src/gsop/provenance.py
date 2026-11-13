"""Hashes, atomic writes, run metadata and resumable stage markers.

Recycled from the IRIS three-body code (runs/batch.py, scripts/seal_manifest.py, analysis/export_web.py):
canonical config hash, atomic tmp -> rename writes, manifest-mismatch refusal, sha256 manifests.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def _jsonable(o: Any) -> Any:
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        v = float(o)
        return None if v != v else v
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, Path):
        return str(o)
    return str(o)


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_jsonable)


def config_hash(obj: Any) -> str:
    """First 10 hex chars of sha256 of the canonical JSON dump."""
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()[:10]


def sha256_file(path: Path | str, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_bytes(path: Path | str, data: bytes) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return path


def atomic_write_text(path: Path | str, text: str) -> Path:
    return atomic_write_bytes(path, text.encode("utf-8"))


def write_json(path: Path | str, obj: Any) -> Path:
    return atomic_write_text(path, json.dumps(obj, indent=1, default=_jsonable) + "\n")


def read_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_savez(path: Path | str, **arrays: np.ndarray) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.npz")
    np.savez(tmp, **arrays)
    os.replace(tmp, path)
    return path


def git_sha(repo: Path = ROOT) -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=str(repo))
        sha = r.stdout.strip() or "unknown"
        dirty = subprocess.run(["git", "diff", "--quiet", "HEAD"], cwd=str(repo), capture_output=True).returncode != 0
        return sha + ("-dirty" if dirty else "")
    except OSError:
        return "unknown"


def package_versions() -> dict[str, str]:
    from importlib import metadata
    names = ["numpy", "pandas", "pyarrow", "scipy", "scikit-learn", "rasterio", "pyproj", "shapely",
             "psutil", "pyyaml", "typer", "earthengine-api"]
    out = {}
    for n in names:
        try:
            out[n] = metadata.version(n)
        except metadata.PackageNotFoundError:
            out[n] = "missing"
    return out


def machine_info() -> dict[str, Any]:
    import psutil
    vm = psutil.virtual_memory()
    return {"os": platform.platform(), "python": sys.version.split()[0], "cores": os.cpu_count(),
            "ram_total_gb": round(vm.total / 2**30, 2), "ram_free_gb": round(vm.available / 2**30, 2),
            "machine": platform.machine()}


def run_meta(cfg_hash: str, seeds: dict, timings: dict, extra: dict | None = None) -> dict[str, Any]:
    meta = {"git_commit": git_sha(), "config_hash": cfg_hash, "package_versions": package_versions(),
            "machine": machine_info(), "seeds": seeds, "timings_s": timings,
            "written": time.strftime("%Y-%m-%d %H:%M:%S%z")}
    if extra:
        meta.update(extra)
    return meta


class StageStore:
    """Resumable stages. A stage is skipped when its marker exists with identical input hashes and config hash.
    Markers live in <results dir>/.done/<stage>.json."""

    def __init__(self, root: Path | str):
        self.dir = Path(root) / ".done"

    def key(self, stage: str, config: str, inputs: dict[str, str]) -> dict:
        return {"stage": stage, "config_hash": config, "inputs": inputs}

    def is_done(self, stage: str, config: str, inputs: dict[str, str]) -> bool:
        p = self.dir / f"{stage}.json"
        if not p.exists():
            return False
        try:
            return read_json(p).get("key") == self.key(stage, config, inputs)
        except (json.JSONDecodeError, OSError):
            return False

    def mark(self, stage: str, config: str, inputs: dict[str, str], seconds: float) -> None:
        write_json(self.dir / f"{stage}.json", {"key": self.key(stage, config, inputs), "seconds": seconds,
                                                "finished": time.strftime("%Y-%m-%d %H:%M:%S%z")})


def write_manifest(directory: Path | str, files: list[Path | str], name: str = "MANIFEST.json") -> Path:
    """sha256 manifest of the given files (relative names). Verbatim copies, no number is edited."""
    directory = Path(directory)
    entries = {}
    for f in sorted(Path(x) for x in files):
        entries[f.relative_to(directory).as_posix()] = {"sha256": sha256_file(f), "bytes": f.stat().st_size}
    return write_json(directory / name, {"written": time.strftime("%Y-%m-%d %H:%M:%S%z"), "files": entries})


def verify_manifest(directory: Path | str, name: str = "MANIFEST.json") -> list[str]:
    directory = Path(directory)
    man = read_json(directory / name)
    problems = []
    for rel, info in man["files"].items():
        p = directory / rel
        if not p.exists():
            problems.append(f"missing: {rel}")
        elif sha256_file(p) != info["sha256"]:
            problems.append(f"sha256 mismatch: {rel}")
    return problems
