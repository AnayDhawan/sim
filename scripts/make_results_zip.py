"""Zip results/<body>/ for sending back. Leaves out the two big per-tile files unless --full.

    uv run python scripts/make_results_zip.py mars [--full]
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIG = {"base_scores.parquet", "mc_counts.npz"}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    full = "--full" in sys.argv
    if len(args) != 1 or args[0] not in ("moon", "mars"):
        print(__doc__)
        return 1
    body = args[0]
    src = ROOT / "results" / body
    if not (src / "run_meta.json").exists():
        print(f"{src / 'run_meta.json'} not found: run `uv run gsop run --body {body}` first.")
        return 1
    out = ROOT / f"results-{body}.zip"
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.rglob("*")):
            if p.is_file() and ".done" not in p.parts and ".stages" not in p.parts and (full or p.name not in BIG):
                z.write(p, f"{body}/{p.relative_to(src).as_posix()}")
                n += 1
    print(f"{out}  ({n} files, {out.stat().st_size / 2**20:.1f} MB). Send it with run_meta.json (already inside).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
