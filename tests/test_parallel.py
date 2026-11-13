"""A18: spawn-safe harness, shared memory without pickling the array, cleanup on exceptions."""

import os
import pickle

import numpy as np
import pytest
from multiprocessing.shared_memory import SharedMemory

from gsop import parallel as PAR
from gsop.parallel import SharedArray, attach, run_tasks


def _gone(name: str) -> bool:
    try:
        SharedMemory(name=name).close()
    except FileNotFoundError:
        return True
    return False


def test_default_workers_is_physical_cores_and_overridable():
    assert PAR.default_workers() == PAR.physical_cores() >= 1
    assert PAR.default_workers(3) == 3
    with pytest.raises(ValueError):
        PAR.default_workers(0)


def test_shared_array_roundtrip_and_release():
    x = np.arange(60, dtype=np.float32).reshape(3, 20)
    with SharedArray(x) as sh:
        name = sh.spec.name
        assert np.array_equal(attach(sh.spec), x)
        assert not attach(sh.spec).flags.writeable
        PAR.detach_all()
    assert _gone(name)


def test_no_leak_after_exception_in_the_parent():
    name = None
    with pytest.raises(RuntimeError):
        with SharedArray(np.zeros((2, 10), np.float32)) as sh:
            name = sh.spec.name
            raise RuntimeError("boom")
    assert _gone(name)


def test_close_is_idempotent():
    sh = SharedArray(np.ones((2, 4), np.float32))
    sh.close()
    sh.close()
    assert _gone(sh.spec.name)


def test_tasks_carry_the_spec_not_the_array():
    x = np.random.default_rng(0).random((15, 400_000), dtype=np.float32)       # 24 MB
    with SharedArray(x) as sh:
        assert len(pickle.dumps((sh.spec, 0, 10))) < 300
        assert len(pickle.dumps((sh.spec, 0, 10))) * 10_000 < x.nbytes


def test_workers_see_the_data_under_spawn_and_match_in_process():
    x = np.random.default_rng(1).random((5, 1000), dtype=np.float32)
    with SharedArray(x) as sh:
        tasks = [(sh.spec, a, a + 250) for a in range(0, 1000, 250)]
        serial = run_tasks(PAR.sum_rows_task, tasks, workers=1, progress=False)
        PAR.detach_all()
        par = run_tasks(PAR.sum_rows_task, tasks, workers=2, progress=False)
    assert par == serial
    assert sum(par) == pytest.approx(float(x.astype(np.float64).sum()))


def test_pool_really_uses_other_processes():
    with SharedArray(np.zeros((1, 100), np.float32)) as sh:
        pids = run_tasks(PAR.pid_task, [(sh.spec, 0, 1)] * 4, workers=2, progress=False)
    assert os.getpid() not in pids


def test_no_segment_left_after_a_worker_exception():
    with pytest.raises(RuntimeError, match="on purpose"):
        with SharedArray(np.zeros((2, 100), np.float32)) as sh:
            name = sh.spec.name
            run_tasks(PAR.raise_task, [(sh.spec, 0, 1)] * 4, workers=2, progress=False)
    assert _gone(name)


def test_interrupt_cancels_pending_tasks_and_keeps_finished_results():
    seen = []

    def stop_after_first(r):
        seen.append(r)
        raise KeyboardInterrupt

    with SharedArray(np.ones((1, 100), np.float32)) as sh:
        with pytest.raises(KeyboardInterrupt):
            run_tasks(PAR.sum_rows_task, [(sh.spec, 0, 100)] * 6, workers=2, on_result=stop_after_first,
                      progress=False)
        name = sh.spec.name
    assert seen == [100.0]
    assert _gone(name)


def test_benchmark_runs_and_reports_speedup():
    rows = PAR.benchmark(n_tiles=40_000, n_cols=4, worker_counts=(1, 2), reps=1, n_tasks=8)
    assert [r["workers"] for r in rows] == [1, 2]
    assert rows[0]["speedup"] == pytest.approx(1.0)
    assert rows[0]["checksum"] == pytest.approx(rows[1]["checksum"])
    assert rows[0]["bytes_pickled_per_task"] < 300
