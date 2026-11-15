# Performance on the Windows laptop (measured 2026-11-14)

Every number below was measured on one machine, once, unless it says otherwise. Run times of finished jobs are read from the `run_meta.json` and `summary.json` files the runs wrote. The macOS numbers in `docs/SPEC.md` section 8b are Yash's and were not repeated here.

## Hardware and conditions

| Item | Value |
|---|---|
| CPU | AMD Ryzen AI 7 350 with Radeon 860M, 8 cores, 16 logical, 2.0 GHz nominal |
| RAM | 23.3 GB total (24,422,764 KB visible to Windows) |
| Free RAM at the start of each finished run | Moon 3.07 GB, Moon latitude 20 to 40 3.60 GB, Mars 2.57 GB (`run_meta.json machine.ram_free_gb`) |
| Free RAM during the checks in this file | 2.4 to 3.3 GB (read from Windows before each step) |
| OS, Python | Windows 11 10.0.26300, Python 3.11.18, numpy 2.4.6, pandas 3.1.1 |
| Commit of the finished runs | `170c76d` (`run_meta.json git_commit`), master seed 20261114, 2,000 runs, 16 workers |

The laptop was also doing other work (usually 3 to 4 GB free), so these are not clean-machine times.

## Earth table and gated tiles

- Earth table: 3,972,955 land tiles (`earth_coverage.json land_tiles`); 2,210,031 have complete terrain (55.6 percent), 1,762,924 have none and are rejected as `missing_data` (413,415 of them north of 60 N, 299,419 south of 56 S; the other 1,050,090 lie inside 56 S to 60 N, which fits the gate-first export that left terrain empty under tiles failing a land-cover gate, E10, but that split was not checked here). Source split: 2,179,377 tiles from SRTM90, 30,654 from GLO30, none in both.
- Tiles passing the gates (`gates__<profile>.json`):

| Job set | Profile | Tiles passed | Rejected: missing_data | vegetated | open_water_or_ice | built_or_cropland | extra_gate |
|---|---|---|---|---|---|---|---|
| Moon, 3,972,955 tiles | base | 964,573 | 1,762,924 | 1,218,997 | 15,282 | 11,179 | 0 |
| Moon | landing_mobility | 882,216 | 1,762,924 | 1,218,997 | 15,282 | 11,179 | 82,357 |
| Moon | power_night | 964,573 | 1,762,924 | 1,218,997 | 15,282 | 11,179 | 0 |
| Moon, latitude 20 to 40, 1,220,300 tiles | base | 549,225 | 265,636 | 397,242 | 1,194 | 7,003 | 0 |
| Moon, latitude 20 to 40 | landing_mobility | 507,413 | 265,636 | 397,242 | 1,194 | 7,003 | 41,812 |
| Moon, latitude 20 to 40 | power_night | 549,225 | 265,636 | 397,242 | 1,194 | 7,003 | 0 |
| Mars, 3,972,955 tiles | base | 964,933 | 1,761,383 | 1,220,162 | 15,285 | 11,192 | 0 |
| Mars | landing_mobility | 955,180 | 1,761,383 | 1,220,162 | 15,285 | 11,192 | 9,753 |
| Mars | power_night | 964,933 | 1,761,383 | 1,220,162 | 15,285 | 11,192 | 0 |
| Mars | ice_resources | 964,933 | 1,761,383 | 1,220,162 | 15,285 | 11,192 | 0 |

So a job scores about 0.96 million tiles, not 4 million, for the full Earth run (the 4,000,000-tile figure in SPEC section 8b is the synthetic upper bound).

## Finished runs, 2,000 Monte Carlo runs each, 16 workers

Wall time of the whole `gsop run` as recorded in `run_meta.json timings_s.total`. The stages add up to the total within 1.1 s (the `export` stage is not timed separately).

| Stage | Moon (6 jobs) | Share | Moon latitude 20 to 40 (6 jobs) | Mars (4 jobs) |
|---|---|---|---|---|
| gates | 3.6 s | 0.5% | 1.4 s | 4.5 s |
| score | 13.5 s | 2.0% | 7.8 s | 5.4 s |
| simulate (Monte Carlo) | 639.6 s | 92.6% | 387.9 s | 409.4 s |
| ml | 24.9 s | 3.6% | 21.4 s | 55.0 s |
| validate | 5.8 s | 0.8% | 1.8 s | 6.4 s |
| discover | 2.3 s | 0.3% | 1.3 s | 1.9 s |
| **Total** | **690.8 s (11.5 min)** | | **422.7 s (7.0 min)** | **483.7 s (8.1 min)** |

- Moon: simulate takes 97.5 to 111.2 s per job (mean 106.6 s). Mars: 99.9 to 106.3 s (mean 102.4 s). Moon latitude 20 to 40: 61.1 to 69.1 s (mean 64.7 s). The time follows the number of gated tiles: 549,225 tiles take about 64 s, 964,573 tiles about 106 s.
- Inside the Monte Carlo, summed over the jobs of the run (`summary.json mc_timings_s`):

| Part | Moon | Moon latitude 20 to 40 | Mars |
|---|---|---|---|
| Pass 1 (score all tiles, top-k counters) | 284.1 s | 174.3 s | 182.0 s |
| Merge and select | 27.3 s | 17.9 s | 18.2 s |
| Pass 2 (candidate scores and ranks) | 268.3 s | 162.8 s | 168.7 s |
| Finalise (percentiles over runs) | 33.2 s | 17.8 s | 27.2 s |
| Monte Carlo total | 613.0 s | 372.8 s | 396.1 s |

  The `simulate` stage (639.6 s for Moon) is 26.6 s longer than the Monte Carlo total (613.0 s); that part was not split.
- Mars ml takes 12.4 to 14.7 s per job against 4.0 to 4.3 s for Moon. Mars jobs have more robust tiles (36,315 to 42,761 per job against 10,197 to 30,982 for Moon), which may be the cause; not investigated.
- Memory: `summary.json memory_plan` shows the chunk size the plan chose from 40 percent of free RAM (budget 0.97 GB for Moon, 1.35 GB for Mars); for the Moon jobs the chunk was 574,554 to 624,839 tiles, below the tile count, so the memory plan was binding. Peak memory of these runs was not recorded.

Total for the three finished runs: 1,597 s (26.6 min).

## Golden check (`uv run gsop golden --check`)

- Result: PASS, 68 checks, no FAIL. Wall time 51.8 s for the whole command including `uv run` start-up and imports (the golden run itself printed 8.3 s). One measurement, run right after `uv sync` with a cold file cache; it was not repeated.
- Tolerance statement: `config/run.yaml compare` allows a maximum absolute score difference of 1e-4, a Monte Carlo median difference of 1e-3 and a top-set Jaccard of at least 0.99. Measured here against the recorded `tests/golden/golden_expected.json`: maximum absolute difference 0.00e+00 on every base-score and every Monte Carlo median check (Moon golden_a and golden_b, 4 profiles each, and Mars golden_a, 5 profiles), Jaccard 1.0000 on every top-1-percent and robust set. The result is bit-identical to the recorded file on this machine. The one macOS comparison in `docs/UNVERIFIED.md` (under 8e-6) is Yash's and was not repeated.

## Monte Carlo benchmark on synthetic data (`scripts/bench_mc.py`, small size)

    uv run python scripts/bench_mc.py --tiles 1000000 --runs 200 --workers 4 --chunk-tiles 200000

Moon layout (12 columns, 8 families), 31,566 candidates, 4 workers, 2.9 GB free at the start:

| Part | Time |
|---|---|
| Pass 1 | 7.0 s |
| Merge and select | 0.9 s |
| Pass 2 | 7.2 s |
| Finalise | 0.5 s |
| Total (`simulate`) | 15.6 s (wall 15.8 s) |

Peak memory summed over the process and its workers: 0.79 GB (this double-counts the shared pages of X).

- Comparison with the real runs (inference from two different workloads, not a controlled test): the benchmark takes 35 ms per run for 1,000,000 tiles in pass 1 with 4 workers; the real Moon base job takes 24 ms per run for 964,573 tiles with 16 workers. Four times the workers gave about 1.4 times the throughput, so the 16 workers are far from scaling linearly (8 physical cores, memory traffic and background load are candidate causes; not tested).
- The benchmark was kept small on purpose because the laptop runs other work. The 4,000,000-tile, 2,000-run configuration of SPEC section 8b was not run here.

## Measured here and not measured here

Measured here (Windows laptop, this file):

- Stage and Monte Carlo timings of the three finished 2,000-run jobs sets (Moon, Moon latitude 20 to 40, Mars), read from their output files.
- Gated tile counts for every job.
- `gsop golden --check` result and wall time, and its difference from the recorded file.
- One small `bench_mc.py` run (1,000,000 tiles, 200 runs, 4 workers).

Not measured here:

- The macOS timings in SPEC section 8b (265.6 s per job at 4,000,000 synthetic tiles, 8 logical cores, 1.4 GB free) are Yash's. They are for a different data size and machine and are not comparable with the real-data jobs above.
- Peak memory of the real runs, run-to-run spread on this machine (one run per configuration), and the effect of closing other programs.
- 2,000 runs at 4,000,000 tiles on this machine, and any worker count other than 16 for the real jobs.
- Mars job timings with the Earth-wide `geology_life` profile (not run, config skips it) and Moon `ice_resources` (not run).
