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


def atomic_savez(path: Path | str, compressed: bool = False, **arrays: np.ndarray) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.npz")
    (np.savez_compressed if compressed else np.savez)(tmp, **arrays)
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


def code_version() -> str:
    """First 10 hex chars of sha256 over every .py file of the gsop package (LF-normalised, path-sorted).
    A change to the engine code invalidates finished stages; a docs or test change does not."""
    pkg = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for f in sorted(pkg.rglob("*.py")):
        h.update(f.relative_to(pkg).as_posix().encode())
        h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:10]


class StageStore:
    """Resumable stages. A stage is skipped when its marker exists, the marker's key (stage, config hash, input hashes,
    code version) equals the current key, and every output it recorded still exists.
    Markers live in <results dir>/.stages/<stage>.json. They are written only after the stage finished, and removed
    before a rerun starts, so a crash never leaves a marker that vouches for a half-written stage."""

    DIRNAME = ".stages"

    def __init__(self, root: Path | str, code: str | None = None):
        self.root = Path(root)
        self.dir = self.root / self.DIRNAME
        self.code = code if code is not None else code_version()

    def key(self, stage: str, config: str, inputs: dict[str, str]) -> dict:
        return {"stage": stage, "config_hash": config, "inputs": inputs, "code_version": self.code}

    def _path(self, stage: str) -> Path:
        return self.dir / f"{stage}.json"

    def read(self, stage: str) -> dict | None:
        p = self._path(stage)
        if not p.exists():
            return None
        try:
            return read_json(p)
        except (json.JSONDecodeError, OSError):
            return None

    def key_hash(self, stage: str) -> str:
        """Identity of a finished stage, for downstream stages to use as an input. 'missing' when not finished."""
        m = self.read(stage)
        return config_hash(m["key"]) if m else "missing"

    def check(self, stage: str, config: str, inputs: dict[str, str]) -> tuple[bool, str]:
        """(done, reason). reason says why a stage has to run, or 'up to date'."""
        m = self.read(stage)
        if m is None:
            return False, "no finished marker"
        have, want = m.get("key", {}), self.key(stage, config, inputs)
        if have.get("code_version") != want["code_version"]:
            return False, "code changed"
        if have.get("config_hash") != want["config_hash"]:
            return False, "config changed"
        hi, wi = have.get("inputs", {}), want["inputs"]
        changed = sorted(k for k in set(hi) | set(wi) if hi.get(k) != wi.get(k))
        if changed:
            return False, "input changed: " + ", ".join(changed)
        missing = [o for o in m.get("outputs", []) if not (self.root / o).exists()]
        if missing:
            return False, "output missing: " + ", ".join(missing)
        return True, "up to date"

    def is_done(self, stage: str, config: str, inputs: dict[str, str]) -> bool:
        return self.check(stage, config, inputs)[0]

    def invalidate(self, stage: str) -> None:
        self._path(stage).unlink(missing_ok=True)

    def mark(self, stage: str, config: str, inputs: dict[str, str], seconds: float,
             outputs: list[Path | str] | None = None) -> None:
        outs = sorted(Path(o).resolve().relative_to(self.root.resolve()).as_posix() for o in (outputs or []))
        write_json(self._path(stage), {"key": self.key(stage, config, inputs), "seconds": seconds, "outputs": outs,
                                       "finished": time.strftime("%Y-%m-%d %H:%M:%S%z")})


def atomic_to_parquet(df: Any, path: Path | str, **kw: Any) -> Path:
    """DataFrame.to_parquet through a temp file and os.replace, so a crash never leaves a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        df.to_parquet(tmp, **kw)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path


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
