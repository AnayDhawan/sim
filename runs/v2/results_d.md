# Results D: fitted thermal terms, leave-one-site-out

Fitted and cross-validated on a very small labelled set. Never replaces Role A's headline. Exploratory; nothing here is a success claim.

Pre-registration `runs/v2/PREREG_D.md`, sha256 `78b4c00cd1df5219ca8dbc2919d744d0414083aeba2e0cc35b5086e41a529610` (recorded in `prereg_d.sha256`). Thermal layer: Role A earth_features_v2_6km.parquet, MODIS MOD11A2 2019-2023, copied 2026-11-15 11:45 IST, sha256 `701a743a82556db243f33c5c629c7d5d070587a2fbee9ae081ee75b80c01ced5`.

## Gates (headline: M3, held-out, Moon without illumination, single-tile percentiles)

| Gate | Value (M3 held-out) | Threshold | Shuffled range | Status |
|---|---|---|---|---|
| D1 | 1.0% | at most 10% | 11.4% to 34.8% | NOT TESTED (thermal layer valid share 73.4% below 85% in latitude -55 to 60) |
| D2 (descriptive only) | 0.0% | at least 50% | 0.0% to 75.0% | would be NOT TESTED, descriptive only (thermal layer valid share 73.4% below 85% in latitude -55 to 60) |
| Moon recall | n/a | n/a | n/a | NOT TESTED (two Moon positives, one not scorable) |

Inside the shuffled-feature range, so not distinguishable from chance on this check: gate.D2.

Outside the shuffled-feature range: gate.D1 (gate status is still NOT TESTED, see reason)

## M0 to M3 metrics, Moon without illumination (primary)

Each cell: value, then the shuffled-feature chance range over 1000 draws (min to max, median). M3 values are held-out outcomes of the leave-one-site-out fit.

| Metric | M0 | M1 | M2 | M3 |
|---|---|---|---|---|
| Moon false-positive rate, top 25% | 21.4% (no thermal term) | 2.0% [chance 11.4% to 25.9%, med 17.9%] | 1.0% [chance 13.9% to 32.3%, med 22.4%] | 1.0% [chance 11.4% to 34.8%, med 18.4%] |
| same, 200 tiles only | 21.6% (no thermal term) | 2.0% [chance 11.6% to 25.6%, med 18.1%] | 1.0% [chance 14.1% to 32.2%, med 22.1%] | 1.0% [chance 11.1% to 34.7%, med 18.6%] |
| Namib sand sea percentile | 49.6 (no thermal term) | 9.4 [chance 3.1 to 84.6, med 36.9] | 6.2 [chance 0.9 to 92.6, med 39.1] | 5.8 [chance 0.2 to 97.1, med 38.3] |
| Rub' al Khali percentile | 12.5 (no thermal term) | 2.9 [chance 0.0 to 80.3, med 29.9] | 3.4 [chance 0.0 to 90.4, med 35.3] | 4.3 [chance 0.1 to 97.6, med 31.2] |
| Mars recall top 5% | 0.0% (no thermal term) | 0.0% [chance 0.0% to 0.0%, med 0.0%] | 0.0% [chance 0.0% to 50.0%, med 0.0%] | 0.0% [chance 0.0% to 50.0%, med 0.0%] |
| Mars recall top 10% | 0.0% (no thermal term) | 0.0% [chance 0.0% to 0.0%, med 0.0%] | 0.0% [chance 0.0% to 75.0%, med 0.0%] | 0.0% [chance 0.0% to 75.0%, med 0.0%] |
| Mars recall top 25% | 0.0% (no thermal term) | 0.0% [chance 0.0% to 25.0%, med 0.0%] | 0.0% [chance 0.0% to 75.0%, med 0.0%] | 0.0% [chance 0.0% to 75.0%, med 0.0%] |
| Mars primary median percentile | 28.1 (no thermal term) | 26.1 [chance 26.5 to 56.5, med 26.6] | 25.8 [chance 24.4 to 95.3, med 24.5] | 27.1 [chance 18.7 to 95.3, med 25.5] |
| AUC positives vs negatives (Mars profile) | 0.037 (no thermal term) | 0.039 [chance 0.025 to 0.305, med 0.036] | 0.052 [chance 0.020 to 0.744, med 0.039] | 0.112 [chance 0.021 to 0.822, med 0.037] |
| Negatives at top 25%, Mars profile (supplementary) | 36.8% (no thermal term) | 34.3% [chance 34.8% to 42.8%, med 37.8%] | 30.3% [chance 33.3% to 44.8%, med 38.3%] | 25.9% [chance 18.9% to 44.8%, med 38.3%] |
| Mars percentile, lonar | n/a (no thermal term) | n/a | n/a | n/a |
| Mars percentile, haughton | 27.9 (no thermal term) | 26.5 [chance 26.4 to 60.4, med 26.4] | 28.9 [chance 24.3 to 97.5, med 24.4] | 43.8 [chance 3.1 to 98.8, med 25.4] |
| Mars percentile, mcmurdo_dry_valleys | n/a (no thermal term) | n/a | n/a | n/a |
| Mars percentile, atacama_salars | 39.7 (no thermal term) | 37.3 [chance 38.0 to 75.8, med 38.1] | 33.0 [chance 35.0 to 98.2, med 35.0] | 32.0 [chance 1.7 to 98.4, med 36.6] |
| Mars percentile, ladakh_puga | 9.7 (no thermal term) | 8.4 [chance 8.6 to 30.1, med 8.6] | 8.2 [chance 8.2 to 95.9, med 8.3] | 8.1 [chance 1.8 to 98.2, med 8.4] |
| Mars percentile, mdrs_utah | 28.2 (no thermal term) | 25.8 [chance 26.6 to 60.7, med 26.7] | 22.7 [chance 24.5 to 97.5, med 24.6] | 22.2 [chance 3.6 to 99.4, med 25.6] |

## M0 to M3 metrics, Moon with illumination (variant, feeds no gate)

| Metric | M0 | M1 | M2 | M3 |
|---|---|---|---|---|
| Moon false-positive rate, top 25% | 21.4% (no thermal term) | 3.5% [chance 10.9% to 25.4%, med 17.4%] | 0.5% [chance 13.9% to 33.8%, med 23.4%] | 0.5% [chance 11.9% to 39.8%, med 19.9%] |
| same, 200 tiles only | 21.6% (no thermal term) | 3.5% [chance 11.1% to 25.1%, med 17.6%] | 0.5% [chance 14.1% to 33.7%, med 23.1%] | 0.5% [chance 12.1% to 40.2%, med 20.1%] |
| Namib sand sea percentile | 49.6 (no thermal term) | 9.7 [chance 3.4 to 84.0, med 36.8] | 5.9 [chance 0.6 to 94.1, med 40.3] | 5.9 [chance 0.2 to 97.1, med 43.2] |
| Rub' al Khali percentile | 12.5 (no thermal term) | 2.8 [chance 0.0 to 79.6, med 29.6] | 3.6 [chance 0.0 to 92.4, med 37.2] | 3.6 [chance 0.2 to 97.6, med 30.2] |
| Mars recall top 5% | 0.0% (no thermal term) | 0.0% [chance 0.0% to 0.0%, med 0.0%] | 0.0% [chance 0.0% to 50.0%, med 0.0%] | 0.0% [chance 0.0% to 50.0%, med 0.0%] |
| Mars recall top 10% | 0.0% (no thermal term) | 0.0% [chance 0.0% to 0.0%, med 0.0%] | 0.0% [chance 0.0% to 75.0%, med 0.0%] | 0.0% [chance 0.0% to 75.0%, med 0.0%] |
| Mars recall top 25% | 0.0% (no thermal term) | 0.0% [chance 0.0% to 25.0%, med 0.0%] | 0.0% [chance 0.0% to 75.0%, med 0.0%] | 0.0% [chance 0.0% to 75.0%, med 0.0%] |
| Mars primary median percentile | 28.1 (no thermal term) | 26.1 [chance 26.5 to 56.5, med 26.6] | 25.8 [chance 24.4 to 95.3, med 24.5] | 25.8 [chance 18.7 to 95.3, med 25.5] |
| AUC positives vs negatives (Mars profile) | 0.037 (no thermal term) | 0.039 [chance 0.025 to 0.305, med 0.036] | 0.052 [chance 0.020 to 0.744, med 0.039] | 0.052 [chance 0.021 to 0.822, med 0.037] |
| Negatives at top 25%, Mars profile (supplementary) | 36.8% (no thermal term) | 34.3% [chance 34.8% to 42.8%, med 37.8%] | 30.3% [chance 33.3% to 44.8%, med 38.3%] | 30.3% [chance 18.9% to 44.8%, med 37.8%] |
| Mars percentile, lonar | n/a (no thermal term) | n/a | n/a | n/a |
| Mars percentile, haughton | 27.9 (no thermal term) | 26.5 [chance 26.4 to 60.4, med 26.4] | 28.9 [chance 24.3 to 97.5, med 24.4] | 28.9 [chance 3.1 to 98.8, med 25.4] |
| Mars percentile, mcmurdo_dry_valleys | n/a (no thermal term) | n/a | n/a | n/a |
| Mars percentile, atacama_salars | 39.7 (no thermal term) | 37.3 [chance 38.0 to 75.8, med 38.1] | 33.0 [chance 35.0 to 98.2, med 35.0] | 33.0 [chance 1.7 to 98.6, med 36.6] |
| Mars percentile, ladakh_puga | 9.7 (no thermal term) | 8.4 [chance 8.6 to 30.1, med 8.6] | 8.2 [chance 8.2 to 95.9, med 8.3] | 8.2 [chance 1.8 to 98.2, med 8.4] |
| Mars percentile, mdrs_utah | 28.2 (no thermal term) | 25.8 [chance 26.6 to 60.7, med 26.7] | 22.7 [chance 24.5 to 97.5, med 24.6] | 22.7 [chance 3.6 to 99.4, med 25.6] |

## AUC bootstrap intervals (95 percent, 1000 draws, too narrow because negatives cluster)

- M0: 0.002 to 0.095 (4 positives, 201 negative units)
- M1: 0.004 to 0.092 (4 positives, 201 negative units)
- M2: 0.010 to 0.108 (4 positives, 201 negative units)
- M3: 0.007 to 0.248 (4 positives, 201 negative units)
- M3_insample: 0.005 to 0.258 (4 positives, 201 negative units)

## Fit

- w fitted on all units (in-sample, Moon without illumination): 0.75
- Held-out folds choosing each w: 0.0: 0, 0.25: 0, 0.5: 1, 0.75: 204, 1.0: 0
- M1 thermal group weight: Moon without illumination 2/7, Moon with illumination 2/9, Mars 1/7. M2 is 0.5.

## Universe

- Moon: 804789 tiles; Mars: 818255 tiles (v1 gates plus valid thermal values).
- Share of v1 land tiles in latitude -55 to 60 with a valid `th_mean`: 73.4%.
- Engine check against v1 base scores: reproduced to 1e-3.

## Labelled sites that cannot be scored by their own tile

| Site | Group | Moon profile | Mars profile |
|---|---|---|---|
| lonar | positive | not scored: own tile fails the v1 NDVI gate (median NDVI above 0.2) | not scored: own tile fails the v1 NDVI gate (median NDVI above 0.2) |
| haughton | positive | scored | scored |
| mcmurdo_dry_valleys | positive | not scored: the point lies outside every v1 land tile (under 50 percent land in the tile or off the grid) | not scored: the point lies outside every v1 land tile (under 50 percent land in the tile or off the grid) |
| atacama_salars | positive | scored | scored |
| ladakh_puga | positive | scored | scored |
| mdrs_utah | positive | scored | scored |
| namib_sand_sea | negative control | scored | scored |
| rub_al_khali | negative control | scored | scored |

Of the 200 sampled negative tiles, 1 is not scored under the Moon profile: own tile has no valid MODIS thermal value.

## Earth tiles with missing thermal values, by latitude band

Tiles are v1 land tiles. A thermal value is missing where the MODIS layer is NaN or the valid share is under 0.5. Bands with |latitude| above 60 are the polar bands (south polar: -90 to -60; north polar: 60 to 90).

| Band | Region | Land tiles | Missing th_mean | Missing th_max | Missing th_ti | Missing share th_mean |
|---|---|---|---|---|---|---|
| -90 to -80 | south polar | 75513 | 75513 | 75513 | 75513 | 100.0% |
| -80 to -70 | south polar | 182347 | 112769 | 112494 | 112769 | 61.8% |
| -70 to -60 | south polar | 41559 | 986 | 545 | 986 | 2.4% |
| -60 to -50 |  | 6011 | 3905 | 3583 | 3905 | 65.0% |
| -50 to -40 |  | 27466 | 19877 | 18849 | 19877 | 72.4% |
| -40 to -30 |  | 114057 | 50629 | 49203 | 50629 | 44.4% |
| -30 to -20 |  | 258253 | 130137 | 127686 | 130137 | 50.4% |
| -20 to -10 |  | 261471 | 36190 | 37214 | 36190 | 13.8% |
| -10 to 0 |  | 284437 | 161553 | 126600 | 161553 | 56.8% |
| 0 to 10 |  | 278225 | 147557 | 140263 | 147557 | 53.0% |
| 10 to 20 |  | 311118 | 38289 | 45037 | 38289 | 12.3% |
| 20 to 30 |  | 419041 | 36621 | 47668 | 36621 | 8.7% |
| 30 to 40 |  | 428949 | 67211 | 63478 | 67211 | 15.7% |
| 40 to 50 |  | 439060 | 34221 | 34420 | 34221 | 7.8% |
| 50 to 60 |  | 401379 | 132979 | 147588 | 132979 | 33.1% |
| 60 to 70 | north polar | 340659 | 164288 | 166728 | 164288 | 48.2% |
| 70 to 80 | north polar | 92249 | 36521 | 34793 | 36521 | 39.6% |
| 80 to 90 | north polar | 11161 | 2094 | 2166 | 2094 | 18.8% |

Polar bands hold 392171 of the 1251340 tiles missing `th_mean`.

## What failed and what the fit decided

- No gate was tested, so no gate returned PASS or FAIL.
- Mars recall at top 5, 10 and 25 percent is 0 for M0 to M3. The highest Mars percentile any scorable positive reaches at any grid weight (0, 0.25, 0.5, 0.75, 1) is 85.8; positives at or above the 90th percentile over the whole grid: 0.
- Because positive recall at top 10 percent is 0 at every grid weight, the M3 fit is decided by the false-positive term alone. Moon false-positive rate by grid weight (0, 0.25, 0.5, 0.75, 1): 21.4%, 4.0%, 1.0%, 0.5%, 0.5%. The fit picks the smallest weight at the minimum.
- Reading, interpretation and not a metric: the lunar polar targets are cold and the negative tiles are hot deserts, so any thermal term pushes deserts down. A lower false-positive rate here says the thermal columns separate hot Earth deserts from cold targets. It does not say thermal terms pull known Mars analog sites up; they did not.

## D2 is descriptive only

D2 (Mars leave-one-out recall at top 10 percent) was registered as a gate. Anay instructed on 15 Nov, after registration, that D2 is descriptive only. The table shows what it would read against the threshold; it is not a pass or fail claim, because it rests on a handful of scorable positives.

## NOT TESTED

- gate.D1 NOT TESTED: thermal layer valid share 73.4% below 85% in latitude -55 to 60
- gate.D2 NOT TESTED: thermal layer valid share 73.4% below 85% in latitude -55 to 60
- Moon recall NOT TESTED: two Moon positives, one not scorable.
- Arcadia: no centre, no thermal reference.

## Units not scorable (own tile not scored)

- lonar: vegetated
- mcmurdo_dry_valleys: not a v1 land tile
- neg199: thermal value invalid

## Limits

- The fit uses 4 scorable Mars positives and 201 negative units. One positive moves recall by 25 points or more.
- Role A's Earth thermal layer has a valid th_mean for 73.4 percent of v1 land tiles between 55S and 60N. The registered rule needs 85 percent. Tiles without a value (polar blocks and areas where the pre-registered MODIS QC rule leaves no value) are outside the universe.
- The 200 negative tiles were drawn from bare, low, near-equatorial land. They cluster in a few deserts and are not independent.
- The v1 Earth file has no share of bare or sparse cover. The negative set uses NDVI median at most 0.10 and little water, ice, built or crop.
- The Earth partner of Mars thermal inertia is the rank of minus the MODIS day-minus-night swing. It is a proxy, not thermal inertia.
- Moon PRP temp_avg and temp_max are modelled values; the Earth partners are satellite skin temperatures from MODIS composites.

## Deviations

- D2 treated as descriptive only, by instruction of 15 Nov after PREREG_D was recorded. The D2 entry keeps its threshold comparison and carries `descriptive_only: true`.
- Two sections added at Anay's request on 15 Nov: unscored labelled sites, and missing thermal values by latitude band.
- Negative-set cover rule uses a low-NDVI proxy, stated in PREREG_D at registration.
- Negative units scorable under the Mars profile but not the Moon profile use `w_full` for their Mars rank in the M3 AUC (they are not in the fit set).
- Role A's layer was copied after its pull finished; layer sha256 is above.
