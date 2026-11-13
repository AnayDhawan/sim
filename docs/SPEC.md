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

## 4. Similarity

For a column k, tile value x, target value t:

    s_k = exp(-0.5 * ((x - t) / sigma_k)^2)            in [0, 1]
    S_f = mean of s_k over the columns of family f
    score = 100 * sum_f w_f * S_f

Sigma rule:

    sigma_k = max(target_spread_k, measurement_uncertainty_k, 0.25 * IQR_k)

- `target_spread_k` is IQR / 1.349 over the 6 km tiles (stride 3 km) inside the 15 km target window.
- `measurement_uncertainty_k` comes from `features.yaml` with a source. A missing value counts as 0. Current values for the Moon (slope 2.0 deg, relief 0.4 m) are midpoints of the ranges in Barker 2021 chosen by the assistant. They are UNVERIFIED.
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

Measured on a MacBook (Apple silicon, 8 logical cores, 8 GB RAM, about 1.3 GB free at the time), macOS, Python 3.11, numpy 2.4, synthetic data: 4,000,000 tiles, the 12 Moon columns in the 8 Moon families, base profile, 2,000 runs, 8 workers, `chunk_tiles` 200,000, default candidate settings (125,781 candidates). Script: a plain call of `montecarlo.simulate`; the numbers are from one run, not an average.

| Part | Time |
|---|---|
| Pass 1 (score all tiles, top-k counts) | 137 s |
| Pass 2 (re-run seeds, candidate scores and ranks) | 162 s |
| Total, one target x profile | 332 s (5.5 min) |
| Peak memory, sum of resident sizes of all processes | 2.8 GB (this double-counts the pages of X that the workers share) |

Single-process profile of one run at 4M tiles: scoring 105 ms, `argpartition` for the top-k sets 77 ms, full `np.sort` for rank percentiles 80 ms, `searchsorted` 23 ms, counters and score sum under 5 ms. Pass 1 is about 190 ms per run and pass 2 about 210 ms, so 2,000 runs on one core is about 13 minutes of work, and eight workers cut it to 5.5 minutes (memory bandwidth, not cores, is the limit). Chunk size between 50,000 and 1,000,000 changes the scoring time by under 10 percent.

Moon has 2 targets x 4 profiles = 8 jobs and Mars 2 x 5 = 10, so at most 8 x 5.5 = 44 min and 10 x 5.5 = 55 min on this machine, if every job had 4M gated tiles. Real jobs have fewer (the gates remove water, ice, vegetation and built-up land) and `landing_mobility` has fewer still, so this is an upper bound. The real Earth file has not been built yet, so this is not measured on real data. Per the issue, no code change was made: the cheap wins were not needed, and `numba` was not tried.

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
- Barker 2021 uncertainty midpoints (section 4), UNVERIFIED.
- Roughness baselines 100 m and 1000 m, TODO.
- Per-tile noise not applied (section 8).
- Site score for validation averages over targets (section 10).
- Ledger relevance matrix is a draft (`ledger.yaml`, `provisional: true`).
- Cross-machine tolerances (`run.yaml: compare`) are a first guess.
- Earth Engine route (`earth/gee_export.py`, `gee_operators.py`, `check_operators.py`) is written but has not been run (needs a login). Three Earth columns (`water_index`, `silica_index`, `dust_index`) are not built (see `config/earth_layers.yaml`).
- Earth `sun_max_elev`, `sun_low_share`, `insol_annual` use latitude and obliquity only, not slope and aspect (`earth/solar.py`).
- Terrain on the EPSG:6933 grid is corrected for the projection's ground scale in the open-data fallback and in the Earth Engine operator (`operators.slope_deg(kx=...)`); the default call is unchanged, so Moon, Mars and the golden slice are unaffected.
- Moon and Mars target profiles are only partly built (see `docs/UNVERIFIED.md`).
