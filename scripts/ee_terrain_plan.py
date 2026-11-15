"""Terrain-on-survivors plan from a folder of gate GeoTIFFs. No Earth Engine call, nothing is exported.

    uv run python scripts/ee_terrain_plan.py PATH_TO_GATE_FOLDER [--max-regions 150] [--block 10] [--json OUT.json]

Prints survivors, occupied 60 km blocks, regions, exported cells and the waste factor (exported cells per survivor).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gsop.earth import terrain_plan as TP


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--max-regions", type=int, default=TP.MAX_REGIONS)
    ap.add_argument("--block", type=int, default=TP.BLOCK)
    ap.add_argument("--max-side", type=int, default=TP.MAX_SIDE)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    cells = TP.survivor_cells(args.folder)
    plan = TP.plan_regions(cells, args.block, args.max_regions, args.max_side)
    print(json.dumps(plan["stats"], indent=1))
    for r in plan["regions"][:10]:
        print("region", r)
    if args.json:
        args.json.write_text(json.dumps(plan, indent=1))
    return 0 if plan["stats"]["all_survivors_covered"] else 1


if __name__ == "__main__":
    sys.exit(main())
