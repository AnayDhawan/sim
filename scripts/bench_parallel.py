"""Speedup of the spawn-safe parallel harness on a synthetic array (issue A18).

    uv run python scripts/bench_parallel.py --tiles 2000000 --workers 1 4 8 --out bench_parallel.json

The array is `--cols` x `--tiles` float32 uniform random numbers (numpy default_rng, `--seed`). It lives in one shared-memory
block; every task carries only its name, shape and dtype. The kernel is the Gaussian similarity of the Monte Carlo inner
loop. Prints a table and, with --out, a JSON file. Worker counts above the machine's cores are allowed and show the limit.
"""

from __future__ import annotations

import argparse
import json

from gsop.parallel import benchmark, physical_cores


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tiles", type=int, default=2_000_000)
    ap.add_argument("--cols", type=int, default=15)
    ap.add_argument("--workers", type=int, nargs="+", default=[1, 4, 8])
    ap.add_argument("--reps", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rows = benchmark(a.tiles, a.cols, a.workers, a.reps, seed=a.seed)
    print(f"physical cores: {physical_cores()}; array {rows[0]['array_mb']:.0f} MB; "
          f"pickled per task: {rows[0]['bytes_pickled_per_task']} bytes")
    print(f"{'workers':>7} {'seconds':>9} {'speedup':>8} {'parent RSS growth (MB)':>24}")
    for r in rows:
        print(f"{r['workers']:>7} {r['seconds']:>9.2f} {r['speedup']:>8.2f} {r['parent_rss_growth_mb']:>24.1f}")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
