"""Time the Monte Carlo engine on synthetic data (issue #6). Reproduces the numbers in docs/SPEC.md section 8b.

    uv run python scripts/bench_mc.py --workers 8 --runs 2000 --chunk-tiles 200000 --out bench_mc.json

Data: `--tiles` rows (default 4,000,000) of uniform float32 random numbers, generated with numpy `default_rng(--data-seed)`
(default 0), one row per column of the chosen body's families in config/weights.yaml (Moon: 12 columns, 8 families).
Target value 0.5 and sigma 0.2 for every column; no measurement or Earth uncertainty. Everything else (master seed, batch
size, top fractions, candidate settings, robust rule) comes from config/run.yaml, exactly as `gsop s5 simulate` uses it.
The script prints one JSON line and writes it to --out. It also samples the summed resident memory of this process and its
workers, which double-counts the pages of X that the workers share.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import psutil

from gsop import montecarlo as MC
from gsop.config import load_all


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--body", default="moon", choices=["moon", "mars"])
    ap.add_argument("--tiles", type=int, default=4_000_000)
    ap.add_argument("--runs", type=int, default=2000)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--chunk-tiles", type=int, default=200_000)
    ap.add_argument("--data-seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=Path("bench_mc.json"))
    a = ap.parse_args()

    cfg = load_all()
    body = cfg["weights"][a.body]
    fam = {f: v["columns"] for f, v in body.items()}
    cols = list(dict.fromkeys(c for v in fam.values() for c in v))
    X = np.random.default_rng(a.data_seed).random((len(cols), a.tiles), dtype=np.float32)
    run = cfg["run"]
    spec = MC.MCSpec(columns=cols, families=fam, ranges={f: tuple(v["range"]) for f, v in body.items()}, multipliers={},
                     target={c: 0.5 for c in cols}, meas_unc={}, earth_unc={}, sigma={c: 0.2 for c in cols},
                     batch_runs=run["batch_runs"], master_seed=run["master_seed"], top_fracs=tuple(run["top_fracs"]))

    me, peak, stop = psutil.Process(), [0], threading.Event()

    def sample() -> None:
        while not stop.is_set():
            try:
                peak[0] = max(peak[0], me.memory_info().rss + sum(c.memory_info().rss for c in me.children(recursive=True)))
            except psutil.Error:
                pass
            stop.wait(0.25)

    vm = psutil.virtual_memory()
    work = Path(tempfile.mkdtemp(prefix="gsop_bench_"))
    th = threading.Thread(target=sample)
    th.start()
    t0 = time.perf_counter()
    try:
        res = MC.simulate(X, spec, a.runs, work, workers=a.workers, chunk_tiles=a.chunk_tiles,
                          cand_cfg=run["candidates"], robust_cfg=run["robust"], checkpoints=[])
    finally:
        stop.set()
        th.join()
        shutil.rmtree(work, ignore_errors=True)
    wall = time.perf_counter() - t0
    out = {"body": a.body, "tiles": a.tiles, "columns": len(cols), "families": len(fam), "runs": a.runs, "workers": a.workers,
           "chunk_tiles": a.chunk_tiles, "data_seed": a.data_seed, "candidates": int(res.convergence["candidates"]),
           "wall_s": round(wall, 1), **{k: round(v, 1) for k, v in res.timings_s.items()},
           "peak_rss_tree_gb": round(peak[0] / 2**30, 2), "ram_total_gb": round(vm.total / 2**30, 1),
           "ram_free_gb_at_start": round(vm.available / 2**30, 1), "cpu_logical": os.cpu_count()}
    print(json.dumps(out))
    a.out.write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
