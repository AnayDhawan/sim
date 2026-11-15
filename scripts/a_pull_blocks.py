"""Pull all Earth thermal blocks (PREREG_A). Resumable: a block with a cached .npy is skipped. Failures logged, never filled."""
from __future__ import annotations
import json, sys, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
import a_modis_thermal as M

ROOT = M.ROOT
B = 50
LOGS = ROOT / "runs" / "v2" / "logs"
LAND = ROOT / "data" / "interim" / "a_thermal" / "land_ixiy.parquet"
V1 = ROOT / "data/raw/v1/gsop_v1/data/processed/earth_features_6km.parquet"


def land_blocks():
    if not LAND.exists():
        LAND.parent.mkdir(parents=True, exist_ok=True)
        pd.read_parquet(V1, columns=["tile_id", "ix", "iy"]).to_parquet(LAND)
    d = pd.read_parquet(LAND)
    bx, by = d["ix"].to_numpy() // B, d["iy"].to_numpy() // B
    keys = sorted(set(zip(by.tolist(), bx.tolist())))
    out = []
    for r, c in keys:
        ix0, iy0 = c * B, r * B
        out.append((ix0, iy0, min(B, M.NCOLS - ix0), min(B, M.NROWS - iy0)))
    return out


def main(workers=8):
    LOGS.mkdir(parents=True, exist_ok=True); M.CACHE.mkdir(parents=True, exist_ok=True)
    M.init()
    blocks = land_blocks()
    todo = [w for w in blocks if not (M.CACHE / f"done_{w[0]}_{w[1]}.flag").exists()]
    print(f"{len(blocks)} land blocks, {len(todo)} to do", flush=True)
    state = {"done": len(blocks) - len(todo), "failed": []}
    lock = threading.Lock(); t0 = time.time()

    def work(w):
        stack = [w]
        while stack:
            cw = stack.pop()
            f = M.CACHE / f"b_{cw[0]}_{cw[1]}_{cw[2]}_{cw[3]}.npy"
            if f.exists():
                continue
            try:
                a = M.fetch_block(cw, retries=2)
                np.save(f, a)
            except Exception as e:  # noqa: BLE001
                if cw[2] <= 10 and cw[3] <= 10:
                    raise
                hw, hh = (cw[2] + 1) // 2, (cw[3] + 1) // 2
                for dx, dy in ((0, 0), (hw, 0), (0, hh), (hw, hh)):
                    ww, hh2 = min(hw, cw[2] - dx), min(hh, cw[3] - dy)
                    if ww > 0 and hh2 > 0:
                        stack.append((cw[0] + dx, cw[1] + dy, ww, hh2))
        (M.CACHE / f"done_{w[0]}_{w[1]}.flag").write_text("1")
        return w

    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(work, w): w for w in todo}
        for f in as_completed(futs):
            w = futs[f]
            with lock:
                try:
                    f.result(); state["done"] += 1
                except Exception as e:  # noqa
                    state["failed"].append({"window": list(w), "error": str(e)[:300]})
                if (state["done"] + len(state["failed"])) % 10 == 0:
                    print(f"{time.strftime('%H:%M:%S')} done {state['done']}/{len(blocks)} failed {len(state['failed'])} elapsed {time.time()-t0:.0f}s", flush=True)
                    (LOGS / "pull_state.json").write_text(json.dumps({"total": len(blocks), **state, "t": time.strftime('%H:%M:%S')}))
    (LOGS / "pull_state.json").write_text(json.dumps({"total": len(blocks), **state, "finished": True}))
    print("finished", state["done"], "failed", len(state["failed"]), flush=True)

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8)
