"""Monte Carlo on the similarity score (D2, D8).

Per run (run_id r, master seed S):
  streams   : SeedSequence(S, spawn_key=(r,)).spawn(3) -> [weights, target jitter, Earth bias].
              This equals SeedSequence(S).spawn(n)[r], so results never depend on the worker count.
              (Recycled from the IRIS batch runner's run_streams.)
  weights   : each family weight ~ U(range), renormalise, apply purpose multipliers, renormalise.
  data      : effective target value t_k = value_k + N(0, measurement_unc_k) - N(0, earth_unc_k).
              A systematic Earth bias b_k shifts every tile, which is the same as shifting the target by -b_k.
              Per-tile noise is NOT applied (documented in docs/SPEC.md).
  score     : 100 * sum_f w_f * mean_k exp(-0.5 ((x_k - t_k) / sigma_k)^2)   (sigma fixed, see similarity.py)
No N x runs matrix is kept. Pass 1 stores per-batch counters (top 1/5/10% membership) and the score sum.
Pass 2 re-runs the same seeds and stores scores and rank percentiles for candidate tiles only (disk memmap).
Batches are fixed blocks of run_ids and are merged in id order, so output is identical for any worker count.
"""

from __future__ import annotations

import gc
import math
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from tqdm import tqdm

from .parallel import run_tasks
from .provenance import atomic_savez, config_hash, read_json, sha256_file, write_json
from .similarity import column_similarity
from .weights import draw_weights


@dataclass
class MCSpec:
    columns: list[str]
    families: dict[str, list[str]]
    ranges: dict[str, tuple[float, float]]
    multipliers: dict[str, float]
    target: dict[str, float]
    meas_unc: dict[str, float]
    earth_unc: dict[str, float]
    sigma: dict[str, float]
    master_seed: int = 20261114
    batch_runs: int = 50
    top_fracs: tuple[float, ...] = (0.01, 0.05, 0.10)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ranges"] = {k: list(v) for k, v in self.ranges.items()}
        d["top_fracs"] = list(self.top_fracs)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MCSpec":
        d = dict(d)
        d["ranges"] = {k: tuple(v) for k, v in d["ranges"].items()}
        d["top_fracs"] = tuple(d["top_fracs"])
        return cls(**d)

    def hash(self) -> str:
        return config_hash(self.as_dict())


# --------------------------------------------------------------------------- memory plan

def memory_plan(n_tiles: int, n_cols: int, workers: int, free_bytes: float, frac: float = 0.40) -> dict[str, Any]:
    """Cell chunk sized so all workers' temporaries stay within `frac` of free RAM.
    Fixed per-worker arrays (scores, argpartition indices, counters, score sum, sorted copy) are counted separately.
    X itself is memory-mapped by every worker. The pages are shared, so they count once, but they show up in each
    process's RSS, so the budget has to cover them (found on macOS: the old plan ignored them and the memory test
    failed by about 10 MB on an 8 GB Mac)."""
    budget = frac * free_bytes
    fixed_per_worker = n_tiles * (4 + 8 + 3 * 2 + 8 + 4)
    x_shared = n_tiles * n_cols * 4
    per_tile_temp = 4 * (n_cols + 6)
    avail = budget - workers * fixed_per_worker - x_shared
    chunk = int(max(1_000, avail // max(1, workers * per_tile_temp))) if avail > 0 else 1_000
    chunk = min(chunk, n_tiles)
    return {"budget_bytes": int(budget), "fixed_per_worker_bytes": int(fixed_per_worker),
            "x_shared_bytes": int(x_shared), "chunk_tiles": chunk, "fits": avail > 0}


# --------------------------------------------------------------------------- one run

def run_streams(master: int, run_id: int) -> list[np.random.Generator]:
    ss = np.random.SeedSequence(int(master), spawn_key=(int(run_id),))
    return [np.random.default_rng(c) for c in ss.spawn(3)]


def draw_run(spec: MCSpec, run_id: int) -> tuple[dict[str, float], dict[str, float]]:
    rw, rt, rb = run_streams(spec.master_seed, run_id)
    w = draw_weights(rw, spec.ranges, spec.multipliers)
    zt = rt.standard_normal(len(spec.columns))
    zb = rb.standard_normal(len(spec.columns))
    t = {c: spec.target[c] + spec.meas_unc.get(c, 0.0) * zt[i] - spec.earth_unc.get(c, 0.0) * zb[i]
         for i, c in enumerate(spec.columns)}
    return w, t


def score_tiles(X: np.ndarray, spec: MCSpec, w: dict[str, float], t: dict[str, float], chunk: int) -> np.ndarray:
    """X is (n_cols, N) float32 in spec.columns order. Returns (N,) float32 scores."""
    idx = {c: i for i, c in enumerate(spec.columns)}
    n = X.shape[1]
    out = np.empty(n, dtype=np.float32)
    for a in range(0, n, chunk):
        b = min(a + chunk, n)
        acc = np.zeros(b - a, dtype=np.float32)
        for fam, cols in spec.families.items():
            wf = np.float32(w[fam])
            fs = None
            for c in cols:
                s = column_similarity(X[idx[c], a:b], t[c], spec.sigma[c])
                fs = s if fs is None else fs + s
            acc += wf * (fs / np.float32(len(cols)))
        out[a:b] = np.float32(100.0) * acc
    return out


def _top_sets(scores: np.ndarray, ks: list[int]) -> list[np.ndarray]:
    n = scores.size
    kmax = ks[-1]
    part = np.argpartition(scores, n - kmax)[n - kmax:]
    order = np.argsort(scores[part], kind="stable")[::-1]
    ranked = part[order]
    return [ranked[:k] for k in ks]


def top_ks(n: int, fracs: tuple[float, ...]) -> list[int]:
    return [max(1, math.ceil(f * n)) for f in fracs]


# --------------------------------------------------------------------------- workers

_CTX: dict[str, Any] = {}


def _ctx(spec_d: dict, x_path: str, chunk: int) -> tuple[MCSpec, np.ndarray]:
    key = f"{x_path}|{chunk}"
    if key not in _CTX:
        _CTX.clear()
        _CTX[key] = (MCSpec.from_dict(spec_d), np.load(x_path, mmap_mode="r"))
    return _CTX[key]


def _batch_runs(batch_id: int, spec: MCSpec, n_runs: int) -> range:
    return range(batch_id * spec.batch_runs, min((batch_id + 1) * spec.batch_runs, n_runs))


def pass1_batch(spec_d: dict, x_path: str, work: str, batch_id: int, n_runs: int, chunk: int) -> int:
    spec, X = _ctx(spec_d, x_path, chunk)
    n = X.shape[1]
    ks = top_ks(n, spec.top_fracs)
    cnt = np.zeros((len(ks), n), dtype=np.uint16)
    ssum = np.zeros(n, dtype=np.float64)
    runs = _batch_runs(batch_id, spec, n_runs)
    wrec = np.zeros((len(runs), len(spec.families)))
    for i, r in enumerate(runs):
        w, t = draw_run(spec, r)
        s = score_tiles(X, spec, w, t, chunk)
        ssum += s
        for j, idx in enumerate(_top_sets(s, ks)):
            cnt[j, idx] += 1
        wrec[i] = [w[f] for f in spec.families]
    atomic_savez(Path(work) / "pass1" / f"batch_{batch_id:05d}.npz", cnt=cnt, ssum=ssum, weights=wrec)
    return batch_id


def pass2_batch(spec_d: dict, x_path: str, work: str, batch_id: int, n_runs: int, chunk: int, n_cand: int) -> int:
    spec, X = _ctx(spec_d, x_path, chunk)
    n = X.shape[1]
    cand = np.load(Path(work) / "candidates.npy")
    sc = np.memmap(Path(work) / "cand_scores.f32", dtype=np.float32, mode="r+", shape=(n_runs, n_cand))
    rk = np.memmap(Path(work) / "cand_rank.f32", dtype=np.float32, mode="r+", shape=(n_runs, n_cand))
    for r in _batch_runs(batch_id, spec, n_runs):
        w, t = draw_run(spec, r)
        s = score_tiles(X, spec, w, t, chunk)
        srt = np.sort(s)
        cs = s[cand]
        sc[r] = cs
        rk[r] = 100.0 * np.searchsorted(srt, cs, side="left") / n
    sc.flush()
    rk.flush()
    del sc, rk
    (Path(work) / "pass2").mkdir(exist_ok=True)
    (Path(work) / "pass2" / f"batch_{batch_id:05d}.done").write_text("ok")
    return batch_id


def _run_batches(fn, args_list: list[tuple], workers: int, desc: str) -> None:
    """Batches are saved one file each as they finish, so an interrupt (Ctrl-C included) loses at most the running
    batches and the next call resumes from the saved ones. `run_tasks` cancels pending batches and joins the pool."""
    run_tasks(fn, args_list, workers=workers, desc=desc)


# --------------------------------------------------------------------------- orchestration

@dataclass
class MCResult:
    n_runs: int
    counts: np.ndarray                      # (len(top_fracs), N) int32 membership counts
    mean_score: np.ndarray                  # (N,) float64
    candidates: pd.DataFrame                # tile index (row index into X) + MC statistics
    convergence: dict[str, Any]
    weight_stats: dict[str, dict[str, float]]
    robust_mask: np.ndarray                 # (N,) bool
    timings_s: dict[str, float] = field(default_factory=dict)


def _check_manifest(work: Path, spec: MCSpec, x_hash: str, chunk_ok: bool = True) -> None:
    man = work / "manifest.json"
    want = {"spec_hash": spec.hash(), "x_hash": x_hash, "batch_runs": spec.batch_runs}
    if man.exists():
        have = read_json(man)
        if have != want:
            raise RuntimeError(f"{work}: manifest mismatch {have} vs {want}. Refusing to mix chunkings or inputs. "
                               "Delete the folder to start over.")
    else:
        write_json(man, want)


def simulate(X: np.ndarray, spec: MCSpec, n_runs: int, work: Path | str, workers: int = 1,
             chunk_tiles: int | None = None, cand_cfg: dict[str, Any] | None = None,
             robust_cfg: dict[str, Any] | None = None, checkpoints: list[int] | None = None,
             keep_work: bool = False) -> MCResult:
    """X is (n_cols, N) float32, columns in spec.columns order. Resumable through `work`."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    cand_cfg = cand_cfg or {"top_frac": 0.03, "max_candidates": 250_000}
    robust_cfg = robust_cfg or {"membership": "top5", "min_freq": 0.90}
    n = X.shape[1]
    chunk = int(chunk_tiles or min(n, 500_000))
    x_path = work / "X.npy"
    if not x_path.exists():
        tmp = work / "X.tmp.npy"
        np.save(tmp, np.ascontiguousarray(X, dtype=np.float32))
        os.replace(tmp, x_path)
    _check_manifest(work, spec, sha256_file(x_path))
    spec_d = spec.as_dict()
    n_batches = math.ceil(n_runs / spec.batch_runs)
    t0 = time.perf_counter()

    todo = [b for b in range(n_batches) if not (work / "pass1" / f"batch_{b:05d}.npz").exists()]
    _run_batches(pass1_batch, [(spec_d, str(x_path), str(work), b, n_runs, chunk) for b in todo], workers, "pass 1")
    t_p1 = time.perf_counter() - t0

    # merge in id order
    fr = list(spec.top_fracs)
    ks = top_ks(n, spec.top_fracs)
    counts = np.zeros((len(fr), n), dtype=np.int32)
    ssum = np.zeros(n, dtype=np.float64)
    wrec = []
    snaps: dict[int, np.ndarray] = {}
    snaps_mean: dict[int, np.ndarray] = {}
    cps = {c for c in (checkpoints or []) if c <= n_runs and c % spec.batch_runs == 0}
    done_runs = 0
    for b in range(n_batches):
        z = np.load(work / "pass1" / f"batch_{b:05d}.npz")
        counts += z["cnt"]
        ssum += z["ssum"]
        wrec.append(z["weights"])
        done_runs += len(_batch_runs(b, spec, n_runs))
        if done_runs in cps:
            snaps[done_runs] = np.lexsort((-ssum, -counts[0]))[:ks[0]]
            snaps_mean[done_runs] = np.argsort(-ssum, kind="stable")[:ks[0]]
    wrec = np.concatenate(wrec)
    final_set = set(np.lexsort((-ssum, -counts[0]))[:ks[0]].tolist())
    final_mean_set = set(np.argsort(-ssum, kind="stable")[:ks[0]].tolist())

    def jac(a: set, b: set) -> float:
        return len(a & b) / len(a | b) if (a | b) else 1.0

    convergence = {
        "metric": "Jaccard overlap of the top-1% tile set (by top-1% membership count, ties by score sum) "
                  "after n runs against the final set",
        "n_tiles_top1pct": ks[0],
        "overlap_membership": {str(k): jac(set(v.tolist()), final_set) for k, v in sorted(snaps.items())},
        "overlap_mean_score": {str(k): jac(set(v.tolist()), final_mean_set) for k, v in sorted(snaps_mean.items())},
    }
    weight_stats = {f: {"mean": float(wrec[:, i].mean()), "p05": float(np.percentile(wrec[:, i], 5)),
                        "p95": float(np.percentile(wrec[:, i], 95))} for i, f in enumerate(spec.families)}

    # robust and candidates
    j_rob = fr.index(float(_membership_frac(robust_cfg["membership"])))
    freq = counts / n_runs
    robust_mask = freq[j_rob] >= robust_cfg["min_freq"]
    kc = max(1, math.ceil(cand_cfg["top_frac"] * n))
    mean_score = ssum / n_runs
    by_mean = np.argsort(-mean_score, kind="stable")[:kc]
    by_freq = np.lexsort((-mean_score, -counts[j_rob]))[:kc]
    robust_idx = np.flatnonzero(robust_mask)
    robust_idx = robust_idx[np.argsort(-mean_score[robust_idx], kind="stable")]
    pool = np.concatenate([robust_idx, by_mean, by_freq])
    _, first = np.unique(pool, return_index=True)
    cand = pool[np.sort(first)][: cand_cfg["max_candidates"]]      # priority order: robust, mean, freq
    truncated = int(len(np.unique(pool)) > cand_cfg["max_candidates"])
    cand = np.sort(cand)
    np.save(work / "candidates.npy", cand)
    nc = cand.size
    for name in ("cand_scores.f32", "cand_rank.f32"):
        p = work / name
        if not p.exists() or p.stat().st_size != n_runs * nc * 4:
            np.memmap(p, dtype=np.float32, mode="w+", shape=(n_runs, nc)).flush()
            for d in (work / "pass2").glob("*.done") if (work / "pass2").exists() else []:
                d.unlink()
    t1 = time.perf_counter()
    todo2 = [b for b in range(n_batches) if not (work / "pass2" / f"batch_{b:05d}.done").exists()]
    _run_batches(pass2_batch, [(spec_d, str(x_path), str(work), b, n_runs, chunk, nc) for b in todo2], workers, "pass 2")
    t_p2 = time.perf_counter() - t1

    sc = np.memmap(work / "cand_scores.f32", dtype=np.float32, mode="r", shape=(n_runs, nc))
    rk = np.memmap(work / "cand_rank.f32", dtype=np.float32, mode="r", shape=(n_runs, nc))
    cols: dict[str, list[np.ndarray]] = {k: [] for k in ("mc_p05", "mc_median", "mc_p95", "rank_pct_p05",
                                                         "rank_pct_p50", "rank_pct_p95")}
    step = 20_000
    for a in range(0, nc, step):
        s_blk = np.array(sc[:, a:a + step])        # real copies, so no view keeps the memmap open
        r_blk = np.array(rk[:, a:a + step])
        p = np.percentile(s_blk, [5, 50, 95], axis=0)
        q = np.percentile(r_blk, [5, 50, 95], axis=0)
        for k, v in zip(("mc_p05", "mc_median", "mc_p95"), p):
            cols[k].append(v)
        for k, v in zip(("rank_pct_p05", "rank_pct_p50", "rank_pct_p95"), q):
            cols[k].append(v)
        del s_blk, r_blk
    del sc, rk
    df =pd.DataFrame({"row": cand.astype(np.int64), "mc_mean": mean_score[cand]})
    for k, parts in cols.items():
        df[k] = np.concatenate(parts) if parts else np.array([])
    for j, f in enumerate(fr):
        df[f"freq_top{int(round(f * 100))}"] = freq[j][cand]
    df["robust"] = robust_mask[cand]
    convergence["candidates"] = int(nc)
    convergence["candidates_truncated"] = bool(truncated)
    res = MCResult(n_runs=n_runs, counts=counts, mean_score=mean_score, candidates=df, convergence=convergence,
                   weight_stats=weight_stats, robust_mask=robust_mask,
                   timings_s=_timings(t0, t_p1, t1, t_p2))
    _CTX.clear()          # release the in-process memmap of X (Windows cannot delete an open file)
    gc.collect()
    if not keep_work:
        _cleanup(work)
    return res


def _timings(t0: float, t_p1: float, t1: float, t_p2: float) -> dict[str, float]:
    """Wall-clock split of `simulate`, all measured from the start of pass 1.
    pass1 / pass2: the two worker passes. merge_select: after pass 1 and before pass 2 (merging the per-batch counters,
    the convergence sets, the candidate selection and creating the two candidate memmaps). finalise: after pass 2
    (percentiles of every candidate over all runs, the result table). total = the four added together."""
    total = time.perf_counter() - t0
    merge_select = (t1 - t0) - t_p1
    return {"pass1": t_p1, "merge_select": merge_select, "pass2": t_p2,
            "finalise": total - t_p1 - merge_select - t_p2, "total": total}


def _membership_frac(name: str) -> float:
    if not name.startswith("top"):
        raise ValueError(f"robust.membership must look like 'top5', got {name!r}")
    return float(name[3:]) / 100.0


def _cleanup(work: Path) -> None:
    """Drop the bulky per-batch files once the result is built. Keeps manifest, X.npy hash and nothing else heavy."""
    import shutil
    for sub in ("pass1", "pass2"):
        shutil.rmtree(work / sub, ignore_errors=True)
    for name in ("cand_scores.f32", "cand_rank.f32", "X.npy", "candidates.npy", "manifest.json"):
        (work / name).unlink(missing_ok=True)
