# Status, 2026-11-13 (Phase 1 done, on synthetic data)

## Done and tested (39 + 3 tests pass on Windows 11)
- Config in `config/*.yaml`, weights derived by code (match the plan to 4 decimals), purpose profiles, gates, ledger, fidelity.
- Similarity, sigma rule, gates with per-tile reasons, Mars target check (warn by default).
- Terrain operators in numpy (`operators.py`), equal-area grid, local raster loader for 6 km GeoTIFFs.
- Monte Carlo engine: fixed batches, resumable, determinism across worker counts (1 vs 4 identical), disk-backed pass 2, convergence, memory test at 4,000,000 tiles.
- ML second opinion, validation with pre-registered criteria, discovery, export with sha256 manifest, compare, merge, golden slice.
- CLI: `doctor`, `s1` to `s9`, `run`, `golden`, `verify-data`, `compare`, `merge`, `check-operators`.

## Added after the first status (2026-11-13, branch fix/open-issues, issues #1 to #11)
- CI workflow for Windows and macOS (`.github/workflows/ci.yml`): not run on GitHub yet. A macOS memory-budget test failure was fixed in `montecarlo.memory_plan`. 72 tests pass on an Apple-silicon Mac.
- Measured 4M-tile Monte Carlo: 332 s per target x profile (SPEC 8b). No optimisation needed.
- SPEC gaps found by an independent re-implementation are fixed in `docs/SPEC.md`. One agent did it, not a human: issue #7 stays open for a person.
- Known-site coordinates checked against opened sources; six confirmed, the rest listed with reasons. Manicouagan gate-test point is the reservoir, not the structure (`docs/UNVERIFIED.md`).
- Earth Engine export, operator check and open-data fallback written (`earth/`). Earth Engine parts are NOT RUN (login needed); the open-data fallback and all maths are tested on synthetic data only.
- Moon `water_index` from a PSR raster; Mars elevation and air density from a MOLA window. Everything else in issues #3 and #4 is blocked on data or decisions listed in `docs/UNVERIFIED.md`.

## Still not done (needs a login, real data, or a person's decision)
- Earth Engine: `gsop s2 earth --source gee --verify`, `gsop check-operators`, a Lonar test export. Needs Anay's login (issues #1, #2).
- Moon `t_mean`, `t_coldest`, `ti_proxy`, `silica_index`; Mars most columns; the Arcadia centre (issues #3, #4).
- A real run: no real Earth file or target profile exists, so there is no real result.
- Sign-off by people: ledger relevance matrix (#11), known-site list (#10), uncertainty choices (#9), a human read of SPEC (#7).

## UNVERIFIED (see `docs/UNVERIFIED.md`)
- All known-site coordinates. Every validation result is stamped provisional.
- Barker 2021 uncertainty midpoints, Earth Engine dataset IDs, the satellite surface minimum for the cold-traps row, electrostatic dust and regolith mechanics rows.

## Measured
- Golden slice (5,000 tiles, 50 runs, both bodies): about 5 s.
- Full test suite: about 80 s.
- Synthetic 4,000,000-tile Monte Carlo: memory stays inside the doctor budget. Run time at 2,000 runs is NOT measured yet (issue #6).
- `gsop doctor` on this machine: 16 logical cores, 23.3 GB RAM total, only 1.9 GB free at the time, so the 40 percent budget (0.8 GB) did not fit an all-core 4M-tile run. Close other programs or use `--workers`.

## A human must confirm
- Known-site coordinates (Shaurya).
- Arcadia centre from the SWIM ice map.
- Ledger relevance matrix (Anay and Vihaan).
- Sigma floors (measurement uncertainties) and the cross-machine tolerances.
- `rough_a` and `rough_b` baselines (100 m and 1000 m) with Vihaan.
- The validation site-score rule (mean over targets).
