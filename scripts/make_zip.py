"""Zip the tracked files of this repo (plus uv.lock) for S. No data/, results/, .venv/ or untracked files.

    uv run python scripts/make_zip.py [out.zip]
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if not sha:
        print("No commit yet: commit first so the zip matches a known version.")
        return 1
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty:
        print("WARNING: uncommitted changes are NOT in the zip (tracked files at the last commit only):")
        print(dirty)
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / f"gsop-sim-{sha}.zip"
    files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True).stdout.decode().split("\0")
    files = [f for f in files if f and not f.startswith(("data/", "results/"))]
    if "uv.lock" not in files:
        print("uv.lock is not tracked: commit it, S needs identical package versions.")
        return 1
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            # read from the last commit, not the working tree
            blob = subprocess.run(["git", "show", f"HEAD:{f}"], cwd=ROOT, capture_output=True).stdout
            z.writestr(f"gsop-sim/{f}", blob)
    print(f"{out}  ({len(files)} files, commit {sha})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
