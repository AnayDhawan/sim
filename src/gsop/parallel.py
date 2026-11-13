"""Spawn-safe parallel harness. Works the same on Windows and macOS, where processes are spawned, not forked.

* `run_tasks`: ProcessPoolExecutor with the spawn context. Every worker function is a top-level, importable function;
  the CLI entry point has an `if __name__ == "__main__"` guard. On any error or Ctrl-C the pending tasks are cancelled,
  running ones finish, and the pool is shut down before the exception continues, so no worker is left behind.
* `SharedArray`: a big array (the ~4M-tile feature matrix) is copied once into a named `multiprocessing.shared_memory`
  block by the parent. Tasks carry only a tiny `SharedSpec` (name, shape, dtype); workers attach with `attach()` and
  read the same pages. Nothing big is pickled. The parent unlinks the block on exit and on exceptions (Windows frees a
  block when its last handle closes; Linux and macOS need the unlink), and a finalizer covers a forgotten `close()`.
  The Monte Carlo engine uses the file-backed variant of the same idea (a memory-mapped X.npy) because its work folder
  must survive a restart; this module is for work that does not need to.
* `default_workers`: physical cores, overridable.
* `benchmark`: speedup of 1 vs 4 vs 8 workers on a synthetic array (`scripts/bench_parallel.py`).
"""

from __future__ import annotations

import os
import time
import weakref
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from multiprocessing import get_context, util
from multiprocessing.shared_memory import SharedMemory
from typing import Any, Callable, Sequence

import numpy as np
import psutil
from tqdm import tqdm


def physical_cores() -> int:
    n = psutil.cpu_count(logical=False)
    return int(n or os.cpu_count() or 1)


def default_workers(requested: int | None = None) -> int:
    """`requested` if given (at least 1), else the number of physical cores (8 on both team machines)."""
    if requested is not None:
        if requested < 1:
            raise ValueError(f"workers must be at least 1, got {requested}")
        return int(requested)
    return physical_cores()


# --------------------------------------------------------------------------- shared memory

@dataclass(frozen=True)
class SharedSpec:
    """What a task carries instead of the array. Pickles to a few dozen bytes."""
    name: str
    shape: tuple[int, ...]
    dtype: str


def _release(shm: SharedMemory) -> None:
    try:
        shm.close()
    except (BufferError, OSError):
        pass
    try:
        shm.unlink()
    except (FileNotFoundError, OSError):
        pass


class SharedArray:
    """Parent-owned shared array. Use as a context manager: the block is released on exit, also on exceptions."""

    def __init__(self, arr: np.ndarray):
        arr = np.ascontiguousarray(arr)
        self._shm: SharedMemory | None = SharedMemory(create=True, size=max(1, arr.nbytes))
        self._finalizer = weakref.finalize(self, _release, self._shm)
        self.array: np.ndarray | None = np.ndarray(arr.shape, dtype=arr.dtype, buffer=self._shm.buf)
        self.array[...] = arr
        self.spec = SharedSpec(self._shm.name, tuple(arr.shape), arr.dtype.str)

    def close(self) -> None:
        """Idempotent. Drops the parent's view, closes and unlinks the block."""
        if self._shm is None:
            return
        self.array = None                       # an exported buffer pointer would make shm.close() raise
        self._finalizer.detach()
        _release(self._shm)
        self._shm = None

    def __enter__(self) -> "SharedArray":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


_ATTACHED: dict[str, tuple[SharedMemory, np.ndarray]] = {}


def detach_all() -> None:
    for shm, _ in list(_ATTACHED.values()):
        try:
            shm.close()
        except (BufferError, OSError):
            pass
    _ATTACHED.clear()


def attach(spec: SharedSpec) -> np.ndarray:
    """Worker side: a read-only view of the shared block, attached once per process."""
    if spec.name not in _ATTACHED:
        if not _ATTACHED:
            util.Finalize(None, detach_all, exitpriority=10)     # runs when a pool worker exits
        shm = SharedMemory(name=spec.name)
        arr = np.ndarray(spec.shape, dtype=np.dtype(spec.dtype), buffer=shm.buf)
        arr.flags.writeable = False
        _ATTACHED[spec.name] = (shm, arr)
    return _ATTACHED[spec.name][1]


# --------------------------------------------------------------------------- pool

def run_tasks(fn: Callable[..., Any], args_list: Sequence[tuple], workers: int = 1, desc: str = "",
              on_result: Callable[[Any], None] | None = None, progress: bool = True) -> list[Any]:
    """Call `fn(*args)` for every tuple, results in task order. `fn` must be a top-level function of an importable
    module (spawn). workers <= 1 runs in this process. On any exception, including KeyboardInterrupt, tasks that have
    not started are cancelled, running ones finish, the pool is shut down, then the exception is re-raised.
    `on_result(result)` is called in the parent as results come back (used for progress saving)."""
    args_list = list(args_list)
    if not args_list:
        return []
    results: list[Any] = []
    if workers <= 1:
        for a in tqdm(args_list, desc=desc, leave=False, disable=not progress):
            r = fn(*a)
            results.append(r)
            if on_result:
                on_result(r)
        return results
    ex = ProcessPoolExecutor(max_workers=min(workers, len(args_list)), mp_context=get_context("spawn"))
    try:
        futs = [ex.submit(fn, *a) for a in args_list]
        for f in tqdm(futs, desc=desc, leave=False, disable=not progress):
            r = f.result()
            results.append(r)
            if on_result:
                on_result(r)
    except BaseException:
        ex.shutdown(wait=True, cancel_futures=True)
        raise
    ex.shutdown(wait=True)
    return results


# --------------------------------------------------------------------------- benchmark and self-test workers

def sum_rows_task(spec: SharedSpec, lo: int, hi: int) -> float:
    """Sum of columns lo:hi of the shared matrix. Cheap; used by the tests."""
    return float(attach(spec)[:, lo:hi].astype(np.float64).sum())


def similarity_task(spec: SharedSpec, lo: int, hi: int, reps: int) -> float:
    """A Gaussian-similarity kernel over columns lo:hi, the same arithmetic as the Monte Carlo inner loop."""
    x = attach(spec)[:, lo:hi]
    acc = 0.0
    for r in range(reps):
        z = (x - np.float32(0.5 + 0.01 * r)) / np.float32(0.2)
        acc += float(np.exp(np.float32(-0.5) * z * z).mean(axis=0).sum())
    return acc


def raise_task(spec: SharedSpec, lo: int, hi: int) -> None:
    attach(spec)
    raise RuntimeError("worker failed on purpose")


def pid_task(spec: SharedSpec, lo: int, hi: int) -> int:
    attach(spec)
    return os.getpid()


def benchmark(n_tiles: int = 2_000_000, n_cols: int = 15, worker_counts: Sequence[int] = (1, 4, 8), reps: int = 40,
              n_tasks: int = 64, seed: int = 0) -> list[dict[str, Any]]:
    """Time the similarity kernel on a synthetic (n_cols, n_tiles) float32 array for each worker count.
    Reports seconds, speedup against the first count, the parent's resident memory growth while the pool ran and the
    bytes pickled per task (to show the array is not copied)."""
    import pickle
    rng = np.random.default_rng(seed)
    X = rng.random((n_cols, n_tiles), dtype=np.float32)
    bounds = np.linspace(0, n_tiles, n_tasks + 1).astype(int)
    rows: list[dict[str, Any]] = []
    proc = psutil.Process()
    with SharedArray(X) as sh:
        tasks = [(sh.spec, int(a), int(b), reps) for a, b in zip(bounds[:-1], bounds[1:])]
        for w in worker_counts:
            rss0 = proc.memory_info().rss
            t0 = time.perf_counter()
            total = sum(run_tasks(similarity_task, tasks, workers=w, progress=False))
            dt = time.perf_counter() - t0
            rows.append({"workers": w, "seconds": dt, "checksum": total,
                         "parent_rss_growth_mb": (proc.memory_info().rss - rss0) / 2**20,
                         "bytes_pickled_per_task": len(pickle.dumps(tasks[0])), "array_mb": X.nbytes / 2**20})
    base = rows[0]["seconds"]
    for r in rows:
        r["speedup"] = base / r["seconds"]
    return rows
