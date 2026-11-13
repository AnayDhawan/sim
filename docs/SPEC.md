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
- `IQR_k` is the interquartile range of column k over all gated Earth tiles. This term stops the score collapsing to zero everywhere for variables Earth cannot match, for example polar lighting.
- All arithmetic on tile values is float32.

## 5. Weights

- Derived: `weight_f = (paper_score_f / sum paper_score) * matchability_f`, then rescaled to sum 1. The code computes this; the table in `weights.yaml` holds only the inputs.
- Moon derived values (family order of the file): 0.3042, 0.1806, 0.1483, 0.1198, 0.1141, 0.0608, 0.0532, 0.0190. Mars: 0.2289, 0.1937, 0.1497, 0.1132, 0.0906, 0.0792, 0.0755, 0.0377, 0.0314.
- D3: the lunar thermal-inertia weight is 0.019. The published 0.03 is a rounding-up artifact that makes the column sum to 1. Both are kept in config; the derived value drives the run. Every derived weight is within 0.012 of the published one (tested).
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
- Per run:
  1. Each family weight is drawn uniformly in its `range`, renormalised to 1, multiplied by the purpose factors and renormalised again.
  2. Effective target value `t_k = value_k + N(0, measurement_unc_k) - N(0, earth_unc_k)`. A systematic Earth bias shifts every tile equally, which is the same as shifting the target the other way. All normals are drawn for every column in file order.
  3. Score all tiles.
- Per-tile noise is NOT applied (it was optional in the plan).
- Pass 1: per run, the top 1, 5 and 10 percent tiles are found with `argpartition` and counted in uint16 counters per batch. The score sum per tile is kept. Runs are grouped into fixed batches of 50 run ids, saved to disk and merged in id order.
- Pass 2: candidate tiles are the union of the robust tiles, the top 3 percent by mean score and the top 3 percent by top-5 membership, capped at 250,000. Pass 2 re-runs the same seeds, keeps each candidate's score and its rank percentile among all tiles (`searchsorted` on the sorted run scores) in a disk memmap, and reads exact median, 5th and 95th percentiles.
- Outputs: `mc_mean`, `mc_median`, `mc_p05`, `mc_p95`, `rank_pct_p05/p50/p95`, `freq_top1/5/10`, `robust`.
- Convergence: Jaccard overlap of the top-1 percent set after 500, 1000, 1500 runs against the final set. The set is ordered by top-1 membership count with ties broken by score sum. The same is reported for the set ordered by mean score.
- Memory: one run holds a few float32 arrays of the tile count; the cell chunk is sized to at most 40 percent of free RAM (`gsop doctor`). The feature array is shared through a read-only memmap, never pickled.

## 9. Checks run beside the Monte Carlo

- Alternative weight sets (no Monte Carlo): Moon `liu2025`, `no_illumination` (D4), `equal`; Mars `mashal2025`, `equal`. For each: top-1 percent overlap (Jaccard) and Spearman against the primary base score.
- The primary Moon run follows the published weights, illumination included. `no_illumination` is the sensitivity variant; the report says whether the robust tiles survive.
- Earth cannot match polar lighting, so `illum_match` (the illumination or sunlight family similarity alone) is written for every tile.
- ML (D9): second opinion only. k-means terrain archetypes (k by silhouette) and logistic regression plus random forest on the primary sites, leave-one-site-out with a 100 km spatial block. There are very few positive sites; the output says "no added signal" unless the mean leave-one-site-out AUC is at least 0.6 with at least 3 sites.
- Discovery: robust tiles more than 100 km from every known site. `process_tag` is left empty for a person.

## 10. Validation

- Pass criteria are written into `validation.json`, with a sha256, before anything is computed: median rank percentile of the primary sites for their intended body at least 90; negative controls below the 25th percentile; all three gate tests rejected. Weights are never tuned to pass.
- Site score: for each scored target, the base-profile rank percentile (among that target's gated tiles) of the best tile within 20 km of the site; the site value is the mean over the body's scored targets. ASSUMPTION: Anay to confirm. For Moon this averages Connecting Ridge C1 and Shackleton rim.
- Gate tests use the tile nearest the point. A point with no land tile within 6 km counts as rejected with that reason.
- Every site coordinate is unconfirmed. Results are stamped `provisional: true` and the run prints the list of unconfirmed sites.

## 11. Deviations and assumptions

- Grid extends to the poles (section 2).
- Barker 2021 uncertainty midpoints (section 4), UNVERIFIED.
- Roughness baselines 100 m and 1000 m, TODO.
- Per-tile noise not applied (section 8).
- Site score for validation averages over targets (section 10).
- Ledger relevance matrix is a draft (`ledger.yaml`, `provisional: true`).
- Cross-machine tolerances (`run.yaml: compare`) are a first guess.
- Earth Engine route, Moon and Mars target profiles are not built yet (see `STATUS.md`).
