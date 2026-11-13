# Status, 2026-11-13 (Phase 1 done, on synthetic data)

## Done and tested (39 + 3 tests pass on Windows 11)
- Config in `config/*.yaml`, weights derived by code (match the plan to 4 decimals), purpose profiles, gates, ledger, fidelity.
- Similarity, sigma rule, gates with per-tile reasons, Mars target check (warn by default).
- Terrain operators in numpy (`operators.py`), equal-area grid, local raster loader for 6 km GeoTIFFs.
- Monte Carlo engine: fixed batches, resumable, determinism across worker counts (1 vs 4 identical), disk-backed pass 2, convergence, memory test at 4,000,000 tiles.
- ML second opinion, validation with pre-registered criteria, discovery, export with sha256 manifest, compare, merge, golden slice.
- CLI: `doctor`, `s1` to `s9`, `run`, `golden`, `verify-data`, `compare`, `merge`, `check-operators`.

## Not done (all of this needs real data or a login)
- Earth Engine export (`earth/gee_export.py` is a stub): needs Anay's `earthengine authenticate` and Cloud project ID. Issue #1.
- `gsop check-operators` Earth Engine side. Issue #2.
- Moon target profiles beyond terrain and the illumination rule: water_index, Diviner temperatures, silica, ti_proxy. Issue #3.
- Mars target profiles and the Arcadia centre. Issue #4. Arcadia stays `unscored: no target data`.
- No real run has happened: no real Earth file, no real target profile, so no real result and no measured run time.

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
