# GSOP simulation spec

Written to let a person outside the team re-implement the score from this file alone. Where this file and the code disagree, that is a bug in one of them: open an issue. Every deviation from the published plan is listed in section 11.

## 1. What is computed

- For each Moon or Mars target and each purpose profile, every 6 km land tile on Earth gets a similarity score from 0 to 100.
- A Monte Carlo over the weights and the data gives a score band, a rank band and the share of runs in which a tile is in the top 1, 5 and 10 percent.
- A tile in the top 5 percent in at least 90 percent of runs is `robust`.
- The limits ledger and fidelity are reported beside the score. They never enter it.

## 2. Grid and tiles (D1)

- Equal-area grid EPSG:6933, cells of 6000 m. Extent x of plus or minus 17,367,530.445 m and y of plus or minus 7,342,230.136 m (pole to pole). The standard EASE-Grid rows stop at 85.04 degrees; we do not, so no land is dropped silently.
- `tile_id = iy * ncols + ix`, with ix east from the left edge and iy south from the top. ncols = 5790, nrows = 2448.
- A tile is land when `land_frac >= 0.5`. Polar ice and open water are removed by the gates below, not by the mask.

## 3. Features

Columns and sources: `config/features.yaml`. Families and their columns: `config/weights.yaml`.

- Terrain operator (one definition, `src/gsop/operators.py`, used on Earth, Moon and Mars):
  1. Block-mean the DEM to a 500 m baseline.
  2. Horn 3x3 slope in degrees on that grid.
  3. Per tile: `slope_med` and `slope_p90` are the 50th and 90th percentile of the slope cells; `relief` is max minus min of the 500 m elevation cells.
  4. Roughness at baseline b: split the native DEM into b by b windows, fit and remove a plane, take the RMS residual per window. The tile value is the median window RMS. `rough_a` uses 100 m and `rough_b` 1000 m. TODO: confirm both baselines with Vihaan.
  5. A window with any NaN is NaN. Tile reductions ignore NaN cells but return NaN when fewer than 90 percent are valid. Nothing is filled.
- `water_index` and `silica_index` are cross-instrument proxies and are the two weakest comparisons in the project. Treat their similarity as indicative.
- A feature that cannot be built is `unavailable`. See section 7.

## 3b. Terrain on Earth: the Earth Engine route against the numpy operator (issue #2)

The numpy operator (`operators.py`) is the definition. The Earth Engine implementation (`earth/gee_operators.py`) must give the same numbers; `gsop check-operators` compares them on one window (default: 5 x 5 tiles near Lonar, `config/run.yaml operator_check`) and fails if a checked feature differs by more than the configured threshold (10 percent: mean absolute difference over mean absolute numpy value). Step by step:

| Step | numpy (`operators.py`) | Earth Engine (`gee_operators.py`) | Where they can differ |
|---|---|---|---|
| Working surface | the DEM on a square grid | `resample('bilinear').reproject` onto a 25 m EPSG:6933 grid aligned to the tiles; the check downloads this same surface for numpy | none in the check (same numbers); the 30 m NASADEM and the 25 m grid are not the same surface, which is why 25 m is used (100 / 30 is not a whole number) |
| Slope baseline | block mean to `slope_baseline_m` | `reduceResolution(mean)` then `reproject` to a tile-aligned grid of that size | none expected |
| Slope | Horn 3x3 (`slope_deg`) | `convolve` with the two Horn kernels (not `ee.Terrain.slope`, whose stencil is different) | none expected |
| Ground scale | `kx = cos(lat) / cos(30 deg)`: a projected cell is `base * kx` m east-west and `base / kx` m north-south | `cos` of the `pixelLonLat` latitude | spherical `kx`, under 1 percent against the ellipsoid |
| `slope_med`, `slope_p90` | numpy percentile, linear | `reduceResolution(percentile)` with `maxRaw` above the cell count, so it uses raw values | numpy interpolates; Earth Engine picks an order statistic |
| `relief` | max minus min of the baseline cells | `reduceResolution(max)` minus `reduceResolution(min)` | none expected |
| `rough_a`, `rough_b` | plane removal in b x b windows of the native DEM, RMS, tile median | window mean removed first, then the moments E[d^2], E[d xi], E[d yi] with `reduceResolution(mean)`; RMS = sqrt(E[d^2] - (E[d xi]^2 + E[d yi]^2) / S); tile median | same algebra (tested in numpy); removing the window mean first is needed in float32, where E[z^2] - E[z]^2 cancels to 0 on elevations |
| Validity | tile is NaN below 90 percent valid cells | `reduceResolution(count)` below `MIN_VALID_FRAC` cells is masked | none expected |

Earth Engine facts the code depends on (found on a real run, 2026-11-13): the CRS must be passed as a WKT1_GDAL string (`gee_operators.ee_crs`); images made by collection reducers need `setDefaultProjection` before `reduceResolution`; `.map()` drops `system:time_start`; `maxPixels` must cover the cell ratio; the unversioned `COPERNICUS/DEM/GLO30` is deprecated (`GLO30_2024_1` is used). These Earth Engine calls were corrected after that run but have not been run again.

## 3c. Terrain from the open-data fallback (issue #8)

When Earth Engine is not available, `gsop s2 open-data` builds the 6 km rasters from downloaded files (`earth/open_data.py`). Terrain is then **coarser and partial**, and nothing is substituted:

- Slope and relief use the same operator with a 500 m baseline, measured in projected metres of the equal-area grid (see the anisotropy note below), so the DEM needs cells of at most 500 m. A global relief grid of about 1.8 km (for example ETOPO 60 arcsec) **cannot** give a 500 m baseline slope, so `slope_med`, `slope_p90` and `relief` are left out and the reason is logged. A 15 arcsec grid (about 460 m) can give them, but at a baseline close to its own cell size.
- `rough_a` and `rough_b` need native cells of at most 33 m and 333 m and are always left out by the fallback.
- A left-out column is absent from the raster, so the missing-data gate (section 6) rejects every tile for a target that needs it and says why; scoring stops loudly (section 7) unless a person lists the column in `run.yaml drop_columns`.
- Only the slope gradient is corrected for the projection's ground scale (section 11). The 500 m slope cell, the roughness windows and the 6 km tile are still projected metres, so they are not square on the ground (see the anisotropy note below).
- Climate layers are only resampled; no temporal aggregation is done.

**Anisotropy note (Earth tiles against Moon and Mars windows).** EPSG:6933 is cylindrical equal-area. A projected distance `d` is `d * kx` ground metres east-west and `d / kx` ground metres north-south, with `kx = cos(lat) / cos(30 deg)`. `operators.slope_deg(kx=...)` uses this to correct the *gradient* (dz/dx and dz/dy), and nothing else. Everything that is a length is still in projected metres, so on Earth:

| Latitude | 500 m slope cell on the ground (E-W x N-S) | 6 km tile on the ground | 100 m roughness window |
|---|---|---|---|
| 30 deg | 500 x 500 m | 6.0 x 6.0 km | 100 x 100 m |
| 60 deg | 289 x 866 m | 3.5 x 10.4 km | 58 x 173 m |
| 80 deg | 100 x 2,494 m | 1.2 x 29.9 km | 20 x 499 m |

Moon and Mars targets use square ground cells (polar-stereographic and cylindrical rasters near their targets, windows of 6 km and 500 m on the ground). So a Moon slope at a 500 m baseline and an Earth slope at "500 m" away from 30 deg latitude are measured over different ground footprints, and Earth roughness at 100 m and 1000 m is taken over elongated windows. The gradient is right; the footprint is not the same. This is open (see `docs/UNVERIFIED.md`); it is not a bug in the arithmetic.

## 4. Similarity

For a column k, tile value x, target value t:

    s_k = exp(-0.5 * ((x - t) / sigma_k)^2)            in [0, 1]
    S_f = mean of s_k over the columns of family f
    score = 100 * sum_f w_f * S_f

Sigma rule:

    sigma_k = max(target_spread_k, measurement_uncertainty_k, 0.25 * IQR_k)

- `target_spread_k` is IQR / 1.349 over the 6 km tiles (stride 3 km) inside the 15 km target window.
- `measurement_uncertainty_k` comes from `features.yaml` with a source. A missing value counts as 0. Current values for the Moon (slope 2.0 deg, relief 0.4 m) are the midpoints of the ranges in Barker et al. 2021 (Planet. Space Sci. 203:105119: "typical RMS values of ~0.30-0.50 m and ~1.5-2.5 deg"; source opened, see `config/features.yaml`). The paper gives one range for four south-pole sites, so taking the midpoint is a choice (the upper ends would be the conservative alternative), and the figures are for 5 m pixels, not for the 500 m baseline this project uses; no source gives the error at that baseline.
- `IQR_k` is the 75th minus the 25th percentile of column k over the Earth tiles that pass every gate for this target and profile, including the landing-mobility extra gate (so it is computed per target and profile view, and differs between `base` and `landing_mobility`). This term stops the score collapsing to zero everywhere for variables Earth cannot match, for example polar lighting.
- A target spread that is 0 or NaN contributes 0 to the `max`. Sigma is computed once from the base target value and is not recomputed under Monte Carlo jitter.
- All percentiles in this project use `numpy.percentile(..., method='linear')` (the numpy default). Other methods change golden scores by 0.04 to 0.07.
- All arithmetic on tile values is float32: x, t, sigma, the similarities, the weights cast to float32, the sum over families (in family order) and the factor 100. Float64 would also pass the 1e-4 golden check, so this is not binding.

## 5. Weights

- Derived: `weight_f = (paper_score_f / sum paper_score) * matchability_f`, then rescaled to sum 1. The code computes this; the table in `weights.yaml` holds only the inputs. "Family order of the file" below means the order of the families in `config/weights.yaml`.
- Moon derived values (family order of the file): 0.3042, 0.1806, 0.1483, 0.1198, 0.1141, 0.0608, 0.0532, 0.0190. Mars: 0.2289, 0.1937, 0.1497, 0.1132, 0.0906, 0.0792, 0.0755, 0.0377, 0.0314.
- D3: the lunar thermal-inertia weight is 0.019. The published 0.03 is a rounding-up artifact that makes the column sum to 1. Both are kept in config; the derived value drives the run. Every derived weight is within 0.012 of the published one (tested; the largest gaps are 0.0110 on the Moon and 0.0045 on Mars). The other seven published Moon weights are the derived values rounded to two decimals; rounding 0.0190 gives 0.02 and the column would sum to 0.99, so the published table carries 0.03 to make it sum to 1.00. Using 0.03 instead of 0.019 moves golden scores by about 0.8 to 1.0 points.
- The derived lunar thermal-inertia weight (0.019) lies just OUTSIDE its own Monte Carlo range [0.02, 0.04] in `weights.yaml`. This is by design of the data as given: Monte Carlo draws use the ranges exactly as written and never clip toward the derived value, so the base score and the Monte Carlo centre differ slightly for that family. Nobody has decided whether the range should be widened; that is an open question for Anay and Vihaan, not something the code decides.
- Purpose profiles multiply the base weights by the factors in `purposes.yaml`, then renormalise. Moon has `base`, `landing_mobility`, `power_night`, `ice_resources`. Mars adds `geology_life`. No Moon life-detection profile (D5). Mars `landing_mobility` and `power_night` are labelled `confidence: low`.

## 6. Gates

A tile failing any gate is rejected and the first failing reason is logged per tile. Priority order:

1. Missing data for any feature column the target's families use (including the gate layers).
2. Landing-mobility extra gate: Moon `slope_med <= 8`, Mars `slope_p90 <= 30`.
3. Built-up or cropland share above 0.20.
4. Median NDVI above 0.2.
5. Open water or permanent ice share above 0.50.

Reasons are reported in the order `open_water_or_ice`, `vegetated`, `built_or_cropland`, `extra_gate`, `missing_data`. A tile with missing data is always reported as `missing_data`. Thresholds live in `gates.yaml`.

Mars target check (D6): target latitude within 50 deg, elevation below 2 km, thermal inertia at least 100. Default mode is `warn`: a failing target still runs and every output is labelled `fails_own_gate: true`. `strict` skips it.

## 7. Unavailable columns

- If a column used by a family is `unavailable` for the target, or missing or all-NaN on Earth, scoring stops with an explicit error.
- A human can drop a column on purpose with `run.yaml: drop_columns`. The column leaves its family (an empty family leaves the weights), weights are renormalised, and the dropped list is written into every output.
- Nothing is substituted silently.

## 8. Monte Carlo (D2, D8)

- Master seed 20261114. Run r uses `SeedSequence(master, spawn_key=(r,))`, which equals `SeedSequence(master).spawn(n)[r]`. Three child streams: weights, target jitter, Earth bias. Results do not depend on worker count.
- Per run r, exactly: `ss = np.random.SeedSequence(master, spawn_key=(r,))`, `w_rng, j_rng, b_rng = [np.random.default_rng(c) for c in ss.spawn(3)]` (PCG64). `w_rng` draws the weights, `j_rng` the measurement jitter, `b_rng` the Earth-bias normals.
  1. One scalar `w_rng.uniform(lo, hi)` per family, in `weights.yaml` family order, using the `range` column (the ranges are not centred on the derived weight). Divide by the sum, multiply by the purpose factors (a missing factor is 1) and divide by the sum again.
  The weight vector of run r is the pure function `montecarlo.weights_for_run(spec, r)`: it uses only `w_rng` of run r, so it is the same on any machine, for any call order and any worker count.
  2. Effective target value `t_k = value_k + measurement_unc_k * z_k - earth_unc_k * y_k`, with `z` and `y` standard normals. A systematic Earth bias shifts every tile equally, which is the same as shifting the target the other way. `cols` is the ordered list of distinct columns used by the body's families: walk the families in `weights.yaml` order, then each family's `columns` in listed order, keeping the first occurrence of each. (This is NOT the order of `features.yaml`; using that order gives Moon medians off by up to 0.11.) For Moon `cols` is slope_med, slope_p90, sun_max_elev, sun_low_share, water_index, rough_a, rough_b, relief, t_mean, t_coldest, silica_index, ti_proxy. One normal per column in `cols` order is drawn from `j_rng`, and one from `b_rng`, even when that column's uncertainty is 0. The Earth-bias draw is not exercised by the golden test because `earth_uncertainty` is empty, so this part was not independently reproduced.
  3. Score all tiles.
- Per-tile noise is NOT applied (it was optional in the plan).
- Pass 1: per run, the top 1, 5 and 10 percent tiles are found with `argpartition` and counted in uint16 counters per batch. The score sum per tile is kept. Runs are grouped into fixed batches of 50 run ids, saved to disk and merged in id order.
- Pass 2: candidate tiles are the union of the robust tiles, the top 3 percent by mean score and the top 3 percent by top-5 membership, capped at 250,000. Pass 2 re-runs the same seeds, keeps each candidate's score and its rank percentile among all tiles (`searchsorted` on the sorted run scores) in a disk memmap, and reads exact median, 5th and 95th percentiles.
- Top-p percent sets have `k = ceil(p * n_gated)` tiles, where `n_gated` is the number of tiles passing the gates for that target and profile. Ties are broken by stable argsort; `top1pct_mc_mean` is ranked by the sum of the run scores. `robust` is top 5 percent (k5 = ceil(0.05 * n_gated)) in at least 90 percent of runs.
- Outputs: `mc_mean`, `mc_median`, `mc_p05`, `mc_p95`, `rank_pct_p05/p50/p95`, `freq_top1/5/10`, `robust`.
- Convergence: Jaccard overlap of the top-1 percent set after 500, 1000, 1500 runs against the final set. The set is ordered by top-1 membership count with ties broken by score sum. The same is reported for the set ordered by mean score.
- Memory: one run holds a few float32 arrays of the tile count; the cell chunk is sized to at most 40 percent of free RAM (`gsop doctor`). The feature array is shared through a read-only memmap, never pickled.

## 8b. Measured run time (issue #6)

Reproduce with the committed script (`scripts/bench_mc.py`):

    uv run python scripts/bench_mc.py --workers 8 --runs 2000 --chunk-tiles 200000 --out bench_mc.json

Inputs: 4,000,000 rows of uniform float32 random numbers from `numpy.random.default_rng(0)`, one per column of the 8 Moon families in `config/weights.yaml` (12 columns); target 0.5 and sigma 0.2 for every column; no measurement or Earth uncertainty; base profile (no purpose multipliers); everything else (master seed, `batch_runs` 50, top fractions, candidates `top_frac` 0.03 and `max_candidates` 250,000, robust rule) from `config/run.yaml`, as `gsop s5 simulate` uses it. The script calls `montecarlo.simulate` directly and prints one JSON line.

Measured on a MacBook with Apple silicon (8 logical cores, 8.0 GB RAM, **1.4 GB free at the start**), macOS, Python 3.11, numpy 2.4, 125,781 candidates:

| Part of `simulate` | Time |
|---|---|
| Pass 1: score all tiles, top-k counters (2,000 runs) | 100.2 s |
| Merge and select: merge the 40 batch files, convergence sets, candidate selection, create the two candidate memmaps | 4.4 s |
| Pass 2: re-run the same seeds, candidate scores and ranks | 134.5 s |
| Finalise: 5th, 50th and 95th percentile of every candidate over all runs (two 2,000 x 125,781 float32 memmaps), result table | 26.6 s |
| **Total, one target x profile** | **265.6 s (4.4 min)** (wall clock 266.8 s) |

Peak memory, summed over the process and its workers: 2.83 GB. This double-counts the pages of X that the workers share, so it overstates the real use.

**Run-to-run variation is large on this machine.** The first measurement of the same configuration (the earlier, uncommitted script) took 331 s: pass 1 137 s, pass 2 162 s. With only 1.4 GB free on an 8 GB machine that was also running other things, 20 percent spread between two runs is normal; treat the figures as "about 4.5 to 5.5 minutes", not as a precise number. The 33 s that the first version of this section left unexplained is the merge/select and finalise parts above (4.4 + 26.6 = 31 s on this run), which were not timed separately before. `MCResult.timings_s` now reports all four parts, and `summary.json` carries them.

Single-process profile of one run at 4M tiles (an earlier, smaller script): scoring 105 ms, `argpartition` for the top-k sets 77 ms, full `np.sort` for rank percentiles 80 ms, `searchsorted` 23 ms, counters and score sum under 5 ms. Chunk size between 50,000 and 1,000,000 changed the scoring time by under 10 percent.

Moon has 2 targets x 4 profiles = 8 jobs and Mars 2 x 5 = 10, so at most 8 x 4.4 = 35 min and 10 x 4.4 = 44 min on this machine if every job had 4M gated tiles (about 45 and 55 minutes at the slower first measurement). Real jobs have fewer tiles (the gates remove water, ice, vegetation and built-up land), and `landing_mobility` has fewer still, so this is an upper bound. Only the Moon base layout was timed; the other profiles and Mars were not measured separately. Nothing was measured on real data or on the Windows machine. No code change was made for speed; `numba` was not tried.

## 9. Checks run beside the Monte Carlo

- Alternative weight sets (no Monte Carlo): Moon `liu2025`, `no_illumination` (D4), `equal`; Mars `mashal2025`, `equal`. For each: top-1 percent overlap (Jaccard) and Spearman against the primary base score.
- The primary Moon run follows the published weights, illumination included. `no_illumination` is the sensitivity variant; the report says whether the robust tiles survive.
- Earth cannot match polar lighting, so `illum_match` (the illumination or sunlight family similarity alone) is written for every tile.
- ML (D9): second opinion only. k-means terrain archetypes (k by silhouette) and logistic regression plus random forest on the primary sites, leave-one-site-out with a 100 km spatial block. There are very few positive sites; the output says "no added signal" unless the mean leave-one-site-out AUC is at least 0.6 with at least 3 sites.
- Discovery: robust tiles more than 100 km from every known site. `process_tag` is left empty for a person.

## 9b. Golden slice (`gsop golden`)

- Inputs are `tests/golden/earth_slice.parquet` (5,000 synthetic tiles) and `targets_golden.parquet` (targets `golden_a`, `golden_b`, 15 columns each, plus `aux_lat`, `aux_elevation_m`, `aux_thermal_inertia_si`). The target file has no body column; the body comes from the golden config: `golden_a` and `golden_b` are scored as Moon targets, and only `golden_a` is also scored as a Mars target (`golden_cfg` in `golden.py`). `mars/golden_b` is absent from `golden_expected.json` because the config does not list it, not because it fails anything.
- The golden run uses 50 Monte Carlo runs with batches of 25 (not the 2,000 of D2), so every golden Monte Carlo field is the 50-run statistic (an even count: the median is the mean of the two middle values).
- `score_first100` is the base score of the first 100 GATED tiles in ascending `tile_id` order, rounded to 6 places; non-gated tiles are skipped. `top1pct_base`, `top1pct_mc_mean` and `robust_tiles` hold `tile_id` values. `mc_median_top20` is keyed by `tile_id`.
- Gate predicates are strict: a tile is rejected when `x > threshold` (built or cropland 0.20, NDVI 0.2, water or ice 0.50) or when the extra gate fails (Moon `slope_med > 8`, Mars `slope_p90 > 30`). No golden tile sits on a threshold, so `<` against `<=` is not exercised. The extra-gate expression lives in `purposes.yaml` (`extra_gate`), and `gates.yaml` holds the other thresholds; the two files are the single source for their own gates. The slice has no NaN, so the missing-data gate is not exercised either.
- Issue #7 check: a Claude agent that was given only this spec, the config files and the golden data (not `src/` or the tests) re-implemented the base score and the Monte Carlo, and reproduced all 13 golden views to within 7.6e-6 once the points above were added. That is one independent reader, not a human review: a person outside the team should still try (issue #7 stays open for that).

## 10. Validation

- Pass criteria are written into `validation.json`, with a sha256, before anything is computed: median rank percentile of the primary sites for their intended body at least 90; negative controls below the 25th percentile; all three gate tests rejected. Weights are never tuned to pass.
- Site score: for each scored target, the base-profile rank percentile (among that target's gated tiles) of the best tile within 20 km of the site; the site value is the mean over the body's scored targets. ASSUMPTION: Anay to confirm. For Moon this averages Connecting Ridge C1 and Shackleton rim.
- Gate tests use the tile nearest the point. A point with no land tile within 6 km counts as rejected with that reason.
- Some site coordinates are still unconfirmed (see `docs/UNVERIFIED.md`). While any is, results are stamped `provisional: true` and the run prints the list of unconfirmed sites.

## 11. Deviations and assumptions

- Grid extends to the poles (section 2).
- Barker 2021 uncertainty midpoints (section 4): the source was opened and the range is quoted exactly; the midpoint is a choice, and the 5 m-pixel figures are applied at a 500 m baseline without a source for that.
- Roughness baselines 100 m and 1000 m, TODO.
- Per-tile noise not applied (section 8).
- Site score for validation averages over targets (section 10).
- Ledger relevance matrix is a draft (`ledger.yaml`, `provisional: true`).
- Cross-machine tolerances (`run.yaml: compare`) are a first guess.
- Earth Engine route (`earth/gee_export.py`, `gee_operators.py`, `check_operators.py`) is written but has not been run (needs a login). Three Earth columns (`water_index`, `silica_index`, `dust_index`) are not built (see `config/earth_layers.yaml`).
- Earth `sun_max_elev`, `sun_low_share`, `insol_annual` use latitude and obliquity only, not slope and aspect (`earth/solar.py`).
- Only the slope GRADIENT on the EPSG:6933 grid is corrected for the projection's ground scale (open-data fallback and Earth Engine operator, `operators.slope_deg(kx=...)`). The 500 m slope cell, the 100 m and 1000 m roughness windows and the 6 km tile stay projected metres, so away from 30 deg latitude they are not square on the ground (anisotropy note, section 3c). The default call is unchanged, so Moon, Mars and the golden slice are unaffected.
- Moon and Mars target profiles are only partly built (see `docs/UNVERIFIED.md`).
