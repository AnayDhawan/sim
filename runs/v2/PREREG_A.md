# PREREG_A: Earth thermal layer from MODIS and the v2 gates (ROLE A)

Registered: 2026-11-15 IST, before any Earth Engine pixel pull, before any download of Moon or Mars thermal products, and before any re-scoring. This file is not edited after the hash is recorded. Deviations go in the Deviations section of `runs/v2/results_a.md`.

Seed: 20261114 (the v1 Monte Carlo master seed, `config/run.yaml`). Hard stop: 17:00 IST Sun 15 Nov 2026. Words "validated", "discovered", "undiscovered" and "new sites" are not used in any text this run writes.

## Scope

- Role: Earth thermal features, re-scoring with the v1 engine plus thermal columns, and the v2 gates G1 to G3.
- Starting point: `origin/main` ca9a816 (branch `v2/a-scoring`). v1 Earth features: `earth_features_6km.parquet` from `gsop_v1_results_2026-11-14.zip` (3,972,955 land tiles, EPSG:6933, 6 km, `grid.json`). v1 has no thermal columns on Earth (its `t_mean`, `t_coldest`, `ti_proxy` were dropped by `run.yaml drop_columns`).
- Reference side (Moon, Mars): Role B file `data/reference/thermal_refs.csv` (branch `data/thermal-refs`) and its limits document. Role B did not keep the body-wide distributions, so the ranking sets below are rebuilt from the same raw products, checked by sha256 against `thermal_refs_files.csv`. If a hash differs, that layer is NOT TESTED.
- Never used: the LLM-estimated numbers in the site CSVs; any invented value; any fill for a missing pixel.

## Source and product (Earth)

- Earth Engine catalog check, 2026-11-15, project `gsop-earthengine`: `MODIS/061/MOD11C3` returns "asset not found", so the monthly 0.05 degree product is not used.
- Product used: `MODIS/061/MOD11A2` (8-day composite, 1 km), bands `LST_Day_1km`, `LST_Night_1km`, `QC_Day`, `QC_Night`, scale 0.02 K.
- Years: 2019 to 2023 inclusive (composites with start date 2019-01-01 to 2023-12-31).
- QC rule: a day value is kept only if `QC_Day` bits 0-1 equal 0 (LST produced, good quality); a night value only if `QC_Night` bits 0-1 equal 0. No other QC bits are used. Pixels masked by the catalog valid range stay masked.

## Earth thermal features

Per 1 km pixel, then aggregated to the v1 6 km tile:

1. Monthly value: for each year and calendar month, the mean of the kept composite values whose start date falls in that month. Day and night are handled separately; a month is valid for a quantity only if every band it uses has at least one kept composite.
2. `th_mean_K`: mean over all valid months of (day_month + night_month) / 2. Pixel is valid if at least 36 of 60 months are valid.
3. `th_max_K`: for each year, the maximum over months of the monthly day value (year counts only if at least 9 months have a valid day value); mean of the yearly maxima over counted years. Pixel is valid if at least 3 years count.
4. `th_dn_K`: mean over valid months of (day_month - night_month). Pixel is valid if at least 36 of 60 months are valid.
5. Tile aggregation: `reduceResolution` mean of the valid 1 km pixels onto the 6 km EPSG:6933 grid (origin and size from v1 `grid.json`, same `tile_id = iy * 5790 + ix`). A tile is valid for a feature if at least 50 percent of its 1 km pixels are valid for it. The valid share is exported as `th_valid_frac` next to the features. Tiles below the share stay NaN.
6. Export in blocks. Each block is retried up to 3 times; failures are logged in `STATUS_A.md` and the block stays NaN. No gap is filled from neighbours, a climatology or another product. Block size is an engineering choice and is not outcome-affecting; changes go in the Deviations section.

## Ranking and pairs

Every pair is compared by percentile rank inside each body's own set, never by absolute value. Rank of value v in set S: `100 * (n_below + 0.5 * n_equal) / n`, with n the set size. The set is fixed before any gating.

| Column | Moon or Mars reference | Earth partner |
|---|---|---|
| `th_mean` (Moon) | PRP `temp_avg` | rank of `th_mean_K` |
| `th_max` (Moon) | PRP `temp_max` | rank of `th_max_K` |
| `th_ti` (Mars, label "proxy") | TES thermal inertia, mean of day and night per pixel | rank of `-th_dn_K` (inverted day-minus-night) |

- Earth sets: all v1 land tiles with a valid value for that feature (after the 50 percent rule).
- Moon set: all records of `dlre_prp_south.tab` with the value in (0, 500] K (the file's whole coverage, 2,880,000 records before exclusions). Site value (target): median of the ranks of the triangles whose centroid lies within R = 5 km of the site centre (Role B selection, sphere radius 1737.4 km). Target spread: IQR / 1.349 of the same ranks.
- Mars set: all pixels of `global_ti_day_2007.img` and `global_ti_night_2007.img` that are non-zero in both and not interpolated in either mask (mask value 0 marks interpolated). Pixel value: (day + night) / 2. Site value: median of the pixel ranks within R = 10 km of Jezero (Role B selection, sphere radius 3389.5 km). Target spread: IQR / 1.349 of the same ranks.
- Cross-check: my site medians in value space (K for the Moon, SI units for Mars) must equal Role B's `median` rows to within 0.5 percent. A larger difference is reported in the Deviations section and the affected layer is NOT TESTED.
- Not scored: Moon `ice_depth` (context only), Moon diurnal range (no source), Moon cold-trap share (no Earth partner), Mars surface temperature (no source). Arcadia has no thermal reference and no centre in the v1 target list, so that target is NOT TESTED.

## Re-scoring

- Engine: the v1 code at `ca9a816`, unchanged (`src/gsop`). New inputs only: an Earth parquet with the v1 columns plus `th_mean`, `th_max`, `th_ti` (rank percentiles, 0 to 100), and target profiles with the three thermal rows added.
- Config changes, and nothing else: Moon family `temperature` columns become `[th_mean, th_max]`; Mars family `thermal_inertia` columns become `[th_ti]` (`dust_index` stays dropped). Weight derivation, ranges, purpose multipliers, gates, sigma rule (including 0.25 * IQR of the gated Earth tiles) and the v1 `drop_columns` lists stay as in v1. The Mars `temperature` family stays empty and leaves the weights, as in v1. The Moon `thermal_inertia` family stays dropped.
- Gating adds missing-data rejection for tiles with NaN in the thermal columns of the family used, by the v1 rule.
- Monte Carlo: 2000 runs, seed 20261114, base profile of `connecting_ridge_c1`, `shackleton_rim` and `jezero`. Other profiles are not re-run in this role.
- Terrain-only baseline: the same engine with the v1 config and the v1 Earth file, no thermal column.

## Gates

Each gate is reported as PASS, FAIL or NOT TESTED. A FAIL is a result. Nothing is tuned after seeing a result.

- **G1 (data pulled, smoke test).** PASS if all of:
  - every export block finished or its failure is logged, and at least 85 percent of v1 land tiles with latitude between -55 and 60 degrees have a valid `th_mean_K`;
  - at five fixed points (Rub' al Khali 21.0 N 51.0 E, Namib sand sea -24.8853 N 15.4078 E, Amazon -2.9 N -60.0 E, Lonar 19.98 N 76.51 E, Haughton 75.37 N -89.68 E), the nearest v1 tile has `th_mean_K`, `th_max_K` in [200, 360] K and `th_max_K` above `th_mean_K`;
  - `th_mean_K` is in [270, 320] K at Rub' al Khali, Namib, Amazon and Lonar, and in [220, 270] K at Haughton;
  - `th_max_K` at Rub' al Khali is above `th_max_K` at Amazon, and `th_dn_K` at Rub' al Khali is above `th_dn_K` at Amazon.
  FAIL if the data exist and any condition fails; NOT TESTED if the pull did not finish.
- **G2 (scoring).** Three clauses, each PASS, FAIL or NOT TESTED:
  - (a) Moon negative controls: with the thermal layers in, the base-profile site rank percentile (v1 `validate_body` rule, mean over the Moon targets) of Namib sand sea and of Rub' al Khali is at most 25.0 for both.
  - (b) Held-out recall, Mars only: positives are the six Mars primary sites in `config/known_sites.yaml` (lonar, haughton, mcmurdo_dry_valleys, atacama_salars, ladakh_puga, mdrs_utah). A positive counts as recalled if its Mars base-profile site rank percentile is at least 95.0 (top 5 percent). Denominator: positives with status `scored` (v1 amendment E28: gated-out and no-gated-tile sites are not scorable); the share over all six is also reported. PASS at 60 percent or more. Nothing in the scoring is fitted to the positives; the Mars thermal target comes from Jezero only. Moon layer-2 recall is NOT TESTED (two positives, one of them gated out).
  - (c) Terrain-only baseline reproduces v1: Namib 90.2, Rub' al Khali 75.6 (Moon rank percentiles) and Mars primary median 61.3, each equal to v1 after rounding to one decimal.
  G2 is FAIL if any clause is FAIL; otherwise NOT TESTED if any of (a) to (c) is NOT TESTED; otherwise PASS.
- **G3 (regions supported, MODIS only).** A v2 region is a cluster of at least 100 tiles, 8-neighbour joined with wrap at the date line, of tiles flagged top 5 percent in at least 90 percent of runs in the v2 base profile of one target, with no tile within 100 km of any site in `known_sites.yaml` (v1 `discovery.min_distance_km`; this is the v1 region rule, counted before any top-N cut). A region is supported if (i) at least half of its tiles are also flagged robust in the v1 base run of the same target, and (ii) the median thermal-family similarity of its tiles is at least the median over all gated tiles of that view. Target: 3 or more supported regions summed over the three targets. PASS at 3 or more, FAIL below 3, NOT TESTED if the Monte Carlo did not finish.
- Also reported: count of valid Earth tiles (valid in all three thermal features, and per view the number passing the gates).

## Outputs

`runs/v2/metrics.json`, `ledger.json`, `claims_a.csv`, `results_a.md`, `STATUS_A.md`; `runs/v2/prereg_a.sha256` holds the sha256 of this file (LF-normalised) and its git blob id. Large rasters and parquet files stay out of git (`data/` is ignored) and are listed with sha256 in `ledger.json`. Metrics entries use the v1 site fields (`id`, `group`, `label`, `unit`, `value`, `display`, `source_file`, `sha256`, `what_this_means_for_the_analogy`) plus `status` on gate entries. Claims rows use `claim,number,source_file,sha256` as in `claims_c.csv`.

## Supervision

A stage that fails twice is logged in `STATUS_A.md`, the affected gate is marked NOT TESTED with the reason, and the run moves on. A crashed stage is restarted up to 5 times. At 17:00 IST data pulls stop and final results are written from what is complete. Nothing is merged to `main`.
