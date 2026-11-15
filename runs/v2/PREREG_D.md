# PREREG_D: fitted thermal terms with leave-one-site-out cross-checking (ROLE D)

Registered: 2026-11-15 IST, before any Earth thermal value is read, before any scoring that includes a thermal column, and before any Moon or Mars thermal reference value is computed. This file is not edited after its hash is recorded in `prereg_d.sha256`. Deviations go in the Deviations section of `runs/v2/results_d.md`.

Label for everything this role produces: **fitted and cross-validated on a very small labelled set**. It never replaces Role A's headline, which uses no fitted weight.

Seed: 20261114 (the v1 master seed). Hard stop: 17:00 IST Sun 15 Nov 2026.

## Instructions added after the first draft of the role brief

Given by Anay on 15 Nov 2026 before this file was committed:

1. Tile-level metrics only. A site score is the percentile of the site's own single tile. No best-of-radius.
2. A shuffled-feature chance baseline (seed 20261114, 1000 draws, range) is reported next to every number.
3. Moon `ice_depth` and the Moon illumination family are not scored. Moon scores are reported with and without the illumination family.
4. D1 and D2 stay as below but use the single-tile percentile.

## What was read before this registration

- v1 results of 14 Nov 2026 (`gsop_v1_results_2026-11-14.zip`): I know the v1 site percentiles, which are best-of-radius values (Moon: Namib sand sea 90.2, Rub' al Khali 75.6; Mars: Haughton 97.2, Atacama salars 61.3, Mdrs Utah 83.3, Ladakh Puga 16.2, McMurdo no gated tile, Lonar gated out). I do not know any single-tile percentile.
- Role A's PREREG and the stage line of `STATUS_A.md` (layer definition, stage, path). No Role A score, control, recall or gate result has been read.
- Role B's `thermal_refs.csv` (value-space site medians). No Earth thermal value of any tile has been read.

## Inputs

- Engine: the v1 run engine at commit a7d96d9 (brought into this branch in its first commit; `origin/main` ca9a816 does not contain it). Config as in v1, unchanged: weights, ranges, gates, sigma rule, `drop_columns`, base profile. Moon family changes are described under Moon variants.
- v1 Earth features: `earth_features_6km.parquet` from the v1 zip (sha256 `df31e93c4034ecb908a2d378ab2335d817e8751b32616e135de8febc0182a966`, 3,972,955 land tiles). v1 target profiles `targets_moon.parquet`, `targets_mars.parquet` from the same zip.
- Earth thermal layer: Role A's assembled file `C:\Users\lenovo\sim-a\data\processed\earth_features_v2_6km.parquet`, columns `th_mean_K`, `th_max_K`, `th_dn_K` and valid-share columns `th_valid_mean`, `th_valid_max`, `th_valid_dn` (MODIS MOD11A2, 2019-2023, 6 km tile; definitions in PREREG_A). I use it only after `STATUS_A.md` lists the global layer as finished. I copy it to `data/raw/a_layer/`, record its sha256 in `ledger_d.json`, and read only my copy. A tile value is valid if the K column is finite and its valid-share column is at least 0.5. Nothing is filled.
- Moon and Mars reference sides: rebuilt by me from the raw products Role B used (`dlre_prp_south.tab`, `global_ti_day_2007.img`, `global_ti_night_2007.img`, `global_ti_msk_day_2007.img`, `global_ti_msk_night_2007.img`), read from `sim-a\data\raw\ref` and checked by sha256 against `data/reference/thermal_refs_files.csv` of branch `data/thermal-refs`. A hash mismatch makes that body's thermal group NOT TESTED. My site medians in value space must equal Role B's `median` rows within 0.5 percent, otherwise the same consequence.
- Never used: LLM-estimated numbers in site CSVs, any invented value, any fill for a missing pixel or tile.

## Thermal feature pairs

Each pair is compared by percentile rank inside the body's own set, `rank(v) = 100 * (n_below + 0.5 * n_equal) / n`. Terrain keeps the v1 transform (raw value, v1 sigma rule).

| Column | Reference body value | Earth partner |
|---|---|---|
| `th_mean` (Moon) | rank of PRP `temp_avg` | rank of `th_mean_K` |
| `th_max` (Moon) | rank of PRP `temp_max` | rank of `th_max_K` |
| `th_ti` (Mars, label "proxy") | rank of TES thermal inertia, mean of day and night | rank of minus `th_dn_K` |

- Earth sets: all v1 land tiles with a valid value for that feature.
- Moon set: all records of `dlre_prp_south.tab` with the value in (0, 500] K. Site value: median of the ranks of records within 5 km of the site centre (sphere radius 1737.4 km). Target spread: IQR / 1.349 of those ranks. Sites: `connecting_ridge_c1`, `shackleton_rim` (coordinates in `config/targets.yaml`).
- Mars set: pixels non-zero in both day and night TI images and not interpolated in either mask (mask 0 is interpolated). Pixel value: (day + night) / 2. Site value: median rank of pixels within 10 km of Jezero (sphere radius 3389.5 km). Target spread: IQR / 1.349 of those ranks.
- Moon `ice_depth` is context only and is not scored. Moon diurnal range, cold-trap share and Mars surface temperature have no source or no Earth partner and are not scored. Arcadia has no centre and no thermal reference: NOT TESTED.
- Similarity of a thermal column: `exp(-0.5 * ((rank - target_rank) / sigma)^2)`, with `sigma = max(target_spread, 0.25 * IQR of the Earth rank column over the universe below)`. No measurement-uncertainty term. The thermal group score `H` is the mean of its columns' similarities, as a v1 family.

## Moon variants

- **Moon, no illumination (primary, used by every gate and by the M3 fit)**: the v1 Moon families slope, roughness and relief only (columns `slope_med`, `slope_p90`, `rough_a`, `rough_b`, `relief`, 5 terrain columns), v1 derived weights renormalised over those three families. Reason: Earth cannot match polar lighting.
- **Moon, with illumination (reported variant)**: the v1 Moon base profile as run on 14 Nov (adds the illumination family `sun_max_elev`, `sun_low_share`, 7 terrain columns). Every Moon metric is reported for both variants. The with-illumination variant has its own M3 fit (same rules) and never feeds a gate.
- Mars keeps its v1 families (sunlight, slope, relief, elevation_density; 6 terrain columns).

## Universe and score

- Universe `U_b` for body b: tiles that pass the v1 base-profile gates for b (the missing-data rule covers the terrain columns of the v1 base profile and the thermal columns of b) AND have valid values for every thermal column of b. The two Moon variants share one `U_Moon`. All models and variants are ranked inside the same `U_b`. Terrain sigma is the v1 rule evaluated over `U_b`.
- Terrain score `T`: the v1 tile score (family weights as above), 0 to 100, per target. Moon targets: `connecting_ridge_c1`, `shackleton_rim`. Mars target: `jezero`.
- Model score for thermal group weight `g` in [0, 1]: `score_g = (1 - g) * T + g * 100 * H`.
- Engine check, not a result: on the v1 universe (v1 gates, no thermal validity) my terrain score of the Moon with-illumination variant and of Mars must equal the per-tile `score` in the v1 `base_scores.parquet` of each target to 1e-3. If not, every number is labelled "engine not reproduced".

## Models

- **M0**: `g = 0`. Terrain only, ranked inside `U_b`.
- **M1**: `g = n_thermal / (n_terrain + n_thermal)`, equal weight per column. Moon no illumination 2/7, Moon with illumination 2/9, Mars 1/7. Inside terrain, family weights are kept.
- **M2**: `g = 0.5`.
- **M3 (HEADLINE, fixed now)**: `g = w`, one scalar shared by both bodies, chosen from {0, 0.25, 0.5, 0.75, 1} by leave-one-site-out scoring (below). One scalar is used because the objective mixes a Mars metric and a Moon metric. M3 headline uses the Moon no-illumination variant.

## Site and tile scores (tile level only)

- A site is scored by its **own tile**: the v1 grid tile that contains the site point (EPSG:6933, `grid.json`, `tile_id = iy * 5790 + ix`). No search radius, no best tile.
- The percentile of a tile is `rank_pct = 100 * mean(scores < tile_score)` over all `U_b` scores of that target (v1 rule). A unit whose tile is not in `U_b` is not scorable (reason listed: not a land tile, gated out, missing terrain, invalid thermal) and is left out of the denominators.
- Moon rank of a unit is the mean over the two Moon targets of its tile percentile (v1 rule). "Top q percent" means `rank_pct >= 100 - q`.
- A negative unit is a false positive when its Moon rank is at least 75.0. Mars recall at top 5, 10, 25 percent is the share of scorable positives with Mars rank at least 95, 90, 75.

## Labelled sets

- **Positives P**: the six Mars primary sites in `config/known_sites.yaml` (lonar, haughton, mcmurdo_dry_valleys, atacama_salars, ladakh_puga, mdrs_utah), each by its own tile under the Mars profile. The share over all six is also reported. Fewer than 2 scorable positives makes M3 NOT TESTED.
- **Negative set N**: 200 tiles plus the two sand-sea sites Namib sand sea and Rub' al Khali (`config/known_sites.yaml`, each by its own tile). The 200 tiles are fixed in `runs/v2/negative_set_d.csv` (sha256 in `prereg_d.sha256`), drawn before any thermal value was read, from the v1 Earth file using non-thermal columns only:
  - absolute latitude at most 30, `elev_mean` at most 1000 m, all v1 terrain columns finite;
  - `ndvi_median` at most 0.10 and `water_ice_frac + built_crop_frac` at most 0.20;
  - no tile within 100 km of any of the six positives;
  - 158,250 tiles met the rule; sample of 200 without replacement with `numpy.random.default_rng(20261114)` on the tile list sorted by `tile_id`.
  - Registration note: the v1 Earth file has no share of bare or sparse cover. The rule "bare or sparse cover at least 80 percent" is replaced by the proxy above (low NDVI median, little water, ice, built or crop). This is a stated change from the role brief, made at registration, not after seeing a result.
- The 200 tiles are spatially clustered in a few deserts and are not independent. Bootstrap intervals treat them as independent and are therefore too narrow. This limit is stated in the results.

## Fitting M3 by leave-one-site-out

- Units: each scorable positive, each scorable negative (the 200 tiles and the two sites).
- For a held-out unit u: the other units form the fit set. For each w in the grid, `objective(w) = 0.5 * recall10(w; positives in fit set) + 0.5 * (1 - fpr25(w; negatives in fit set))`, with `recall10` the Mars recall at top 10 percent and `fpr25` the Moon false-positive rate at top 25 percent. `w_u` is the argmax; a tie goes to the smallest w. The held-out outcome of u (its rank percentile under `w_u`) is the only value that enters every M3 headline metric, gate and AUC.
- The w fitted on all units (`w_full`) and the distribution of `w_u` are reported. Any metric computed with `w_full` is labelled in-sample and is never used for a gate.

## Metrics (reported for M0, M1, M2, M3, for both Moon variants where Moon applies, each with its counts)

1. Negative-set false-positive rate, Moon, top 25 percent, over all scorable negative units. Also over the 200 tiles alone, and the two sites one by one.
2. Mars recall (leave-one-out for M3, direct for M0 to M2) at top 5, 10, 25 percent, over scorable positives, and over all six.
3. Rank-based separation (AUC) of positives against negative units, both scored under the Mars profile by their Mars rank percentile (ties count one half). 95 percent interval: 1000 bootstrap draws resampling positives and negatives with replacement, seed 20261114, percentile method.
4. Namib sand sea and Rub' al Khali: Moon rank percentile of their own tile, with and without illumination, next to the terrain-only value (M0).
5. Mars primary median: median Mars rank percentile of scorable positives.
6. Supplementary, not a gate and not in the objective: negative-set false-positive rate under the Mars profile at top 25 percent.

## Shuffled-feature chance baseline

- Next to every number that depends on a thermal column, the same number is recomputed with the Earth thermal rank columns permuted across the tiles of `U_b` (all thermal columns of a body permuted together by one permutation, so their correlation is kept and their link to place is broken). Terrain columns, targets and units stay as they are.
- 1000 draws; draw d uses `numpy.random.default_rng([20261114, d])`, one permutation per body. For M3, each draw repeats the full leave-one-site-out fit on the shuffled features, so the baseline contains the selection step.
- Reported per number: minimum, median and maximum over the draws. For M0 the thermal weight is zero, so the baseline equals the number and says so. Counts and units that do not depend on thermal data carry no baseline.
- The baseline is context. No new gate is made from it; where an M3 number lies relative to its range is stated in the results.

## Gates

Each is PASS, FAIL or NOT TESTED. A FAIL is a result. Nothing is tuned after a result is seen. Both use single-tile percentiles, M3 held-out outcomes and the Moon no-illumination variant.

- **D1**: the negative-set false-positive rate (metric 1) for M3 is at most 10 percent.
- **D2**: Mars leave-one-out recall at top 10 percent (metric 2) for M3 is at least 50 percent of scorable positives.
- Moon recall: NOT TESTED (two Moon positives, one of them not scorable).
- D1 and D2 are NOT TESTED if the thermal layer has under 85 percent valid `th_mean_K` among v1 land tiles with latitude -55 to 60, if a reference hash or cross-check fails, if the engine check fails to run, or if the fit cannot run. The reason is written next to the gate.

## Outputs

`runs/v2/metrics_d.json` (v1 site fields `id, group, label, unit, value, display, source_file, sha256, what_this_means_for_the_analogy`, plus the chance-baseline range; gate entries add `status` as the literal strings PASS, FAIL, NOT TESTED), `ledger_d.json` (source, hash, limit per entry), `claims_d.csv` (`claim,number,source_file,sha256`, every number reported), `results_d.md` (models, M0 to M3 metric table, gate table, what failed, what is NOT TESTED, deviations, hash of this file beside the headline numbers), `STATUS_D.md` (time IST, stage, done, next, failures, updated every stage). Rasters, parquet files and copied layers stay out of git (`data/` is ignored) and are listed with sha256 in `ledger_d.json`.

## Supervision

A stage that fails twice is logged in `STATUS_D.md`, the affected gate is marked NOT TESTED with the reason, and the run moves on. A crashed stage is restarted up to 5 times. If Role A's global layer is not listed by 14:00 IST, D is marked NOT RUN with that reason. At 17:00 IST work stops and final results are written from what is complete. Nothing is merged to `main`.
