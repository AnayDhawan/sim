# Performance

Measured numbers only. Machine and date are on every line. Re-measure with the command given.

## Similarity kernel (issue C07)

`uv run python -c "from gsop import similarity as S; print(S.throughput(2_000_000))"`

| date | machine | tiles | columns | tiles per second per core |
|---|---|---|---|---|
| 2026-11-13 | Apple silicon Mac, 8 cores, 8 GB, Python 3.11, numpy 2.4 | 2,000,000 | 15 (8 families) | 30.4 million (best of 3, one core) |

This is the scoring arithmetic alone (the shared `score_block`), on uniform random float32 data. A Monte Carlo run
adds weight and target draws, the top-k selection per run and the memory-mapped reads, so end-to-end speed is lower:
see docs/SPEC.md section 8b (332 s per target x profile at 4M tiles and 2,000 runs).

## Parallel harness (issue A18)

`uv run python scripts/bench_parallel.py --tiles 2000000 --reps 40 --workers 1 4 8`

| date | machine | workers | seconds | speedup |
|---|---|---|---|---|
| 2026-11-13 | Apple silicon Mac, 8 cores (4 performance), 8 GB | 1 | 2.67 | 1.00 |
| | | 4 | 0.90 | 2.96 |
| | | 8 | 0.86 | 3.11 |

Tasks carry 114 bytes (a shared-memory spec), not the 114 MB array. Not yet run on Windows.
