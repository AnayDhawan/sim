# results_a: Earth thermal layer from MODIS and the v2 gates (ROLE A)

- Pre-registration: `runs/v2/PREREG_A.md`, sha256 `1758b132701ea831dea51c82ee9ebc3bd5c2c3a9e1544fdfe3eb7cd7a1e7992e`.
- `runs/v2/PREREG_A_addendum1.md`, sha256 `8e4fb4c8c555b30d748d763bd18b88d597b291663a2cab732a33d1e7511c7d92`, was added after PREREG_A and before any v2 result (no v2 control score, positive score or Mars median had been computed or read; a 50-run smoke test on partial data was deleted unread). It sets the headline weights (H), the secondary site statistic and the illumination sensitivity.
- Seed 20261114. Engine: v1 run code at commit a7d96d9 (see Deviations). Earth thermal source: MODIS/061/MOD11A2, 2019 to 2023.

## Gates

| Gate | Status | Basis |
|---|---|---|
| G1 data pulled and smoke test | FAIL | {"coverage_band_ge_85pct": false, "points_finite": false} |
| G2 (a) Moon controls at most 25 | FAIL | {"rank_pct": {"namib_sand_sea": 58.17276329572098, "rub_al_khali": 37.97504687564069}, "status_by_control": {"namib_sand_sea": "scored", "rub_al_khali": "scored"}} |
| G2 (b) Mars recall at least 60% | FAIL | {"recalled": {"haughton": false, "atacama_salars": false, "ladakh_puga": false, "mdrs_utah": false}, "n_scorable": 4, "share_scorable": 0.0, "share_all_six": 0.0, "rank_pct": {"lonar": null, "haughton": 86.58743301293606, "mcmurdo_dry_valleys": 0.0, "atacama_salars": 52.68162125498775, "ladakh_puga" |
| G2 (c) terrain-only baseline reproduces v1 | PASS | {"values": {"namib": 90.19325708190695, "rub": 75.55875670923939, "mars_median": 61.28835026013856}, "v1": {"namib": 90.2, "rub": 75.6, "mars_median": 61.3}, "match": {"namib": true, "rub": true, "mars_median": true}} |
| G2 Moon layer-2 recall | NOT TESTED | Moon has 2 positives (lonar, haughton) and lonar is gated out |
| G2 overall | FAIL | FAIL if any clause FAIL |
| G3 supported regions (target 3 or more) | FAIL | 2 supported |

G2(a) cannot be met by construction under a best-of-35-tiles score; G2(b) passes by chance about 83% of the time. See ENGINE_AUDIT.md.

## Earth tiles

- v1 land tiles: 3,972,955. Valid in all three thermal features: 2,622,387. Valid `th_mean_K`: 2,721,615. Share valid between 55 S and 60 N: 0.7340.

### Tiles with missing thermal values by latitude band

| Latitude band | Land tiles | Missing th_mean_K | Missing share | Missing th_max_K | Note |
|---|---|---|---|---|---|
| -90 to -80 | 75,513 | 75,513 | 1.000 | 75,513 | Antarctica (south polar plateau) |
| -80 to -70 | 182,347 | 112,769 | 0.618 | 112,494 | Antarctica (interior, shelves and coast) |
| -70 to -60 | 41,559 | 986 | 0.024 | 545 | Antarctica (coast and peninsula) |
| -60 to -50 | 6,011 | 3,905 | 0.650 | 3,583 | Southern Ocean margin (sub-Antarctic islands, Patagonia tip) |
| -50 to -40 | 27,466 | 19,877 | 0.724 | 18,849 |  |
| -40 to -30 | 114,057 | 50,629 | 0.444 | 49,203 |  |
| -30 to -20 | 258,253 | 130,137 | 0.504 | 127,686 |  |
| -20 to -10 | 261,471 | 36,190 | 0.138 | 37,214 |  |
| -10 to 0 | 284,437 | 161,553 | 0.568 | 126,600 |  |
| 0 to 10 | 278,225 | 147,557 | 0.530 | 140,263 |  |
| 10 to 20 | 311,118 | 38,289 | 0.123 | 45,037 |  |
| 20 to 30 | 419,041 | 36,621 | 0.087 | 47,668 |  |
| 30 to 40 | 428,949 | 67,211 | 0.157 | 63,478 |  |
| 40 to 50 | 439,060 | 34,221 | 0.078 | 34,420 |  |
| 50 to 60 | 401,379 | 132,979 | 0.331 | 147,588 |  |
| 60 to 70 | 340,659 | 164,288 | 0.482 | 166,728 | Arctic fringe |
| 70 to 80 | 92,249 | 36,521 | 0.396 | 34,793 | Arctic (Greenland, Arctic islands) |
| 80 to 90 | 11,161 | 2,094 | 0.188 | 2,166 | high Arctic (north Greenland, Ellesmere) |

The lowest valid `th_mean_K` is 216.45 K. Tiles with no thermal value are left out of the Earth percentile set (it is built only from valid tiles) and are rejected as missing data when scoring. The polar plateau and the high-latitude interior are the least covered bands, so the coldest Earth tiles may be absent from the thermal ranking. A Moon polar value that ranks low within the Moon set is therefore compared with an Earth set that lacks the coldest Earth surfaces, and the low end of the Earth ranking is less reliable than the middle.


## Descriptive results, whatever the gate status

Percentiles are 100 * share of gated tiles of the view scoring below the site value. Best-of-radius is the v1 statistic (best gated tile within 20 km). Own tile is the tile nearest the site point. Chance = mean of 1000 shuffled-feature draws (seed 20261114) with the 2.5 to 97.5 percentile range and min to max. Mean over the body's targets. `gated_out` = no gated tile.

### Moon

| Weighting | Site | Role | Best-of-radius | chance (best) | Own tile | chance (own) |
|---|---|---|---|---|---|---|
| v1 (terrain only) | amazon_basin | control | n/a | n/a | n/a | 50.4 (2.6 to 97.4; min 0.1, max 99.9) |
| v1 (terrain only) | congo_basin | control | n/a | n/a | n/a | 49.2 (1.8 to 97.1; min 0.0, max 99.5) |
| v1 (terrain only) | haughton | positive | 85.8 | 97.5 (90.6 to 99.9; min 83.5, max 100.0) | 80.8 | 49.7 (2.3 to 96.8; min 0.1, max 99.9) |
| v1 (terrain only) | lonar | positive | n/a | n/a | n/a | 50.1 (2.3 to 97.6; min 0.1, max 99.8) |
| v1 (terrain only) | namib_sand_sea | control | 90.2 | 97.1 (89.3 to 99.9; min 80.6, max 100.0) | 41.9 | 50.2 (2.4 to 97.3; min 0.0, max 99.9) |
| v1 (terrain only) | rub_al_khali | control | 75.6 | 97.0 (89.4 to 99.9; min 71.2, max 100.0) | 11.5 | 49.3 (2.4 to 96.6; min 0.1, max 99.9) |
| v1 without illumination (post-PREREG sensitivity) | amazon_basin | control | n/a | n/a | n/a | 50.4 (2.7 to 97.4; min 0.1, max 99.9) |
| v1 without illumination (post-PREREG sensitivity) | congo_basin | control | n/a | n/a | n/a | 49.2 (1.8 to 97.1; min 0.0, max 99.5) |
| v1 without illumination (post-PREREG sensitivity) | haughton | positive | 85.8 | 97.5 (90.6 to 99.9; min 83.5, max 100.0) | 80.8 | 49.7 (2.3 to 96.8; min 0.1, max 99.9) |
| v1 without illumination (post-PREREG sensitivity) | lonar | positive | n/a | n/a | n/a | 50.1 (2.3 to 97.6; min 0.1, max 99.8) |
| v1 without illumination (post-PREREG sensitivity) | namib_sand_sea | control | 90.2 | 97.1 (89.3 to 99.9; min 80.6, max 100.0) | 41.9 | 50.2 (2.5 to 97.3; min 0.0, max 99.9) |
| v1 without illumination (post-PREREG sensitivity) | rub_al_khali | control | 75.6 | 97.0 (89.4 to 99.9; min 71.2, max 100.0) | 11.5 | 49.3 (2.5 to 96.6; min 0.1, max 99.9) |
| v2 headline H (thermal 0.5) | amazon_basin | control | n/a | n/a | n/a | 51.1 (2.9 to 98.0; min 0.2, max 100.0) |
| v2 headline H (thermal 0.5) | congo_basin | control | n/a | n/a | n/a | 50.6 (3.6 to 97.6; min 0.2, max 99.9) |
| v2 headline H (thermal 0.5) | haughton | positive | 71.9 | 97.3 (90.1 to 99.9; min 79.2, max 100.0) | 65.4 | 49.3 (2.5 to 97.7; min 0.1, max 99.8) |
| v2 headline H (thermal 0.5) | lonar | positive | n/a | n/a | n/a | 49.5 (2.3 to 97.1; min 0.1, max 99.9) |
| v2 headline H (thermal 0.5) | namib_sand_sea | control | 58.2 | 97.2 (90.1 to 99.9; min 80.1, max 100.0) | 5.1 | 50.4 (3.2 to 96.0; min 0.1, max 99.7) |
| v2 headline H (thermal 0.5) | rub_al_khali | control | 38.0 | 97.0 (89.9 to 99.9; min 82.2, max 100.0) | 3.4 | 50.1 (3.1 to 98.0; min 0.0, max 100.0) |
| S0 PREREG_A family weights (sensitivity) | amazon_basin | control | n/a | n/a | n/a | 50.5 (2.6 to 97.7; min 0.2, max 100.0) |
| S0 PREREG_A family weights (sensitivity) | congo_basin | control | n/a | n/a | n/a | 49.7 (3.8 to 97.8; min 0.2, max 99.7) |
| S0 PREREG_A family weights (sensitivity) | haughton | positive | 88.6 | 97.4 (91.1 to 99.9; min 85.2, max 100.0) | 85.2 | 49.0 (2.3 to 97.2; min 0.1, max 99.8) |
| S0 PREREG_A family weights (sensitivity) | lonar | positive | n/a | n/a | n/a | 49.3 (2.2 to 97.6; min 0.1, max 99.8) |
| S0 PREREG_A family weights (sensitivity) | namib_sand_sea | control | 92.5 | 97.2 (90.2 to 99.9; min 79.5, max 100.0) | 18.3 | 50.4 (3.0 to 96.2; min 0.1, max 99.7) |
| S0 PREREG_A family weights (sensitivity) | rub_al_khali | control | 78.8 | 97.0 (89.6 to 99.9; min 83.1, max 100.0) | 2.4 | 49.9 (2.9 to 96.9; min 0.0, max 100.0) |
| S1 equal per column (sensitivity) | amazon_basin | control | n/a | n/a | n/a | 50.8 (2.6 to 97.7; min 0.2, max 100.0) |
| S1 equal per column (sensitivity) | congo_basin | control | n/a | n/a | n/a | 50.1 (3.6 to 97.5; min 0.2, max 100.0) |
| S1 equal per column (sensitivity) | haughton | positive | 90.0 | 97.4 (90.5 to 99.9; min 84.9, max 100.0) | 84.1 | 49.1 (2.3 to 97.8; min 0.1, max 99.8) |
| S1 equal per column (sensitivity) | lonar | positive | n/a | n/a | n/a | 49.5 (2.2 to 97.4; min 0.1, max 99.9) |
| S1 equal per column (sensitivity) | namib_sand_sea | control | 91.7 | 97.2 (90.0 to 99.9; min 81.1, max 100.0) | 7.0 | 50.4 (2.9 to 96.6; min 0.1, max 99.8) |
| S1 equal per column (sensitivity) | rub_al_khali | control | 73.3 | 97.0 (88.7 to 99.9; min 75.7, max 100.0) | 2.6 | 49.9 (3.0 to 97.5; min 0.0, max 100.0) |
| S2 thermal 0.75 (sensitivity) | amazon_basin | control | n/a | n/a | n/a | 51.1 (3.1 to 97.7; min 0.2, max 100.0) |
| S2 thermal 0.75 (sensitivity) | congo_basin | control | n/a | n/a | n/a | 50.7 (3.6 to 98.0; min 0.3, max 100.0) |
| S2 thermal 0.75 (sensitivity) | haughton | positive | 47.1 | 97.3 (90.5 to 99.9; min 82.9, max 100.0) | 43.3 | 49.6 (2.5 to 98.1; min 0.1, max 100.0) |
| S2 thermal 0.75 (sensitivity) | lonar | positive | n/a | n/a | n/a | 49.5 (2.3 to 97.3; min 0.0, max 99.9) |
| S2 thermal 0.75 (sensitivity) | namib_sand_sea | control | 35.4 | 97.2 (90.1 to 99.9; min 79.0, max 100.0) | 5.4 | 50.5 (3.2 to 96.2; min 0.1, max 99.8) |
| S2 thermal 0.75 (sensitivity) | rub_al_khali | control | 17.9 | 97.1 (89.6 to 99.9; min 84.2, max 100.0) | 4.2 | 50.3 (2.6 to 97.8; min 0.0, max 99.9) |
| S3 H without illumination (post-PREREG sensitivity) | amazon_basin | control | n/a | n/a | n/a | 51.1 (2.8 to 97.9; min 0.2, max 100.0) |
| S3 H without illumination (post-PREREG sensitivity) | congo_basin | control | n/a | n/a | n/a | 50.5 (3.5 to 97.6; min 0.2, max 100.0) |
| S3 H without illumination (post-PREREG sensitivity) | haughton | positive | 77.1 | 97.3 (90.7 to 99.9; min 77.7, max 100.0) | 71.5 | 49.2 (2.4 to 97.6; min 0.1, max 99.8) |
| S3 H without illumination (post-PREREG sensitivity) | lonar | positive | n/a | n/a | n/a | 49.5 (2.3 to 97.0; min 0.1, max 99.9) |
| S3 H without illumination (post-PREREG sensitivity) | namib_sand_sea | control | 68.4 | 97.2 (89.5 to 99.9; min 83.2, max 100.0) | 5.3 | 50.4 (3.1 to 96.1; min 0.1, max 99.8) |
| S3 H without illumination (post-PREREG sensitivity) | rub_al_khali | control | 44.6 | 97.0 (90.0 to 99.9; min 80.6, max 100.0) | 3.1 | 50.0 (3.2 to 97.7; min 0.0, max 100.0) |

Chance column shows the first target's draw summary; the mean over targets is in `results/a_<variant>/secondary.json`.

### Mars

| Weighting | Site | Role | Best-of-radius | chance (best) | Own tile | chance (own) |
|---|---|---|---|---|---|---|
| v1 (terrain only) | amazon_basin | control | n/a | n/a | n/a | 50.2 (2.2 to 97.5; min 0.0, max 100.0) |
| v1 (terrain only) | atacama_salars | positive | 61.3 | 97.1 (89.7 to 99.9; min 77.8, max 100.0) | 42.3 | 50.5 (2.4 to 98.0; min 0.1, max 99.9) |
| v1 (terrain only) | congo_basin | control | n/a | n/a | n/a | 51.0 (2.6 to 98.1; min 0.0, max 99.9) |
| v1 (terrain only) | haughton | positive | 97.2 | 97.5 (91.3 to 99.9; min 85.8, max 100.0) | 35.0 | 50.5 (2.2 to 97.1; min 0.1, max 99.8) |
| v1 (terrain only) | ladakh_puga | positive | 16.2 | 97.3 (89.9 to 99.9; min 79.6, max 100.0) | 16.0 | 50.9 (3.2 to 97.6; min 0.2, max 99.8) |
| v1 (terrain only) | lonar | positive | n/a | n/a | n/a | 50.3 (3.0 to 97.5; min 0.1, max 99.7) |
| v1 (terrain only) | mcmurdo_dry_valleys | positive | n/a | n/a | n/a | 49.9 (2.8 to 96.4; min 0.0, max 99.8) |
| v1 (terrain only) | mdrs_utah | positive | 83.3 | 97.3 (90.7 to 99.9; min 81.8, max 100.0) | 37.1 | 49.2 (2.6 to 97.5; min 0.2, max 99.9) |
| v2 headline H (thermal 0.5) | amazon_basin | control | n/a | n/a | n/a | 49.2 (2.2 to 97.1; min 0.1, max 99.4) |
| v2 headline H (thermal 0.5) | atacama_salars | positive | 52.7 | 97.1 (89.9 to 99.9; min 83.3, max 100.0) | 31.2 | 49.0 (1.9 to 97.0; min 0.0, max 99.8) |
| v2 headline H (thermal 0.5) | congo_basin | control | n/a | n/a | n/a | 51.8 (2.2 to 97.6; min 0.0, max 100.0) |
| v2 headline H (thermal 0.5) | haughton | positive | 86.6 | 97.4 (90.8 to 99.9; min 87.2, max 100.0) | 27.8 | 49.0 (2.6 to 97.7; min 0.2, max 99.9) |
| v2 headline H (thermal 0.5) | ladakh_puga | positive | 8.3 | 97.0 (89.2 to 99.9; min 81.8, max 100.0) | 8.1 | 52.4 (3.5 to 98.0; min 0.0, max 99.7) |
| v2 headline H (thermal 0.5) | lonar | positive | n/a | n/a | n/a | 49.9 (2.4 to 98.1; min 0.0, max 100.0) |
| v2 headline H (thermal 0.5) | mcmurdo_dry_valleys | positive | n/a | n/a | n/a | 49.7 (1.9 to 97.8; min 0.1, max 100.0) |
| v2 headline H (thermal 0.5) | mdrs_utah | positive | 75.0 | 90.8 (67.3 to 99.7; min 38.3, max 100.0) | 24.7 | 51.4 (2.9 to 97.7; min 0.0, max 99.8) |
| S0 PREREG_A family weights (sensitivity) | amazon_basin | control | n/a | n/a | n/a | 49.0 (2.1 to 96.7; min 0.1, max 99.8) |
| S0 PREREG_A family weights (sensitivity) | atacama_salars | positive | 58.8 | 97.2 (90.1 to 99.9; min 81.7, max 100.0) | 36.3 | 48.6 (1.9 to 96.5; min 0.0, max 99.7) |
| S0 PREREG_A family weights (sensitivity) | congo_basin | control | n/a | n/a | n/a | 51.8 (2.2 to 98.6; min 0.1, max 100.0) |
| S0 PREREG_A family weights (sensitivity) | haughton | positive | 93.2 | 97.4 (90.9 to 99.9; min 84.5, max 100.0) | 26.0 | 49.3 (2.3 to 97.6; min 0.2, max 100.0) |
| S0 PREREG_A family weights (sensitivity) | ladakh_puga | positive | 8.4 | 97.2 (89.8 to 99.9; min 81.3, max 100.0) | 8.3 | 51.3 (3.6 to 97.3; min 0.0, max 99.9) |
| S0 PREREG_A family weights (sensitivity) | lonar | positive | n/a | n/a | n/a | 50.2 (2.4 to 97.9; min 0.0, max 100.0) |
| S0 PREREG_A family weights (sensitivity) | mcmurdo_dry_valleys | positive | n/a | n/a | n/a | 49.6 (1.9 to 97.0; min 0.1, max 99.9) |
| S0 PREREG_A family weights (sensitivity) | mdrs_utah | positive | 79.5 | 90.4 (69.3 to 99.6; min 41.4, max 100.0) | 24.8 | 51.7 (2.8 to 98.3; min 0.0, max 99.9) |
| S1 equal per column (sensitivity) | amazon_basin | control | n/a | n/a | n/a | 49.1 (2.2 to 97.1; min 0.1, max 99.9) |
| S1 equal per column (sensitivity) | atacama_salars | positive | 58.1 | 97.2 (90.3 to 99.9; min 81.8, max 100.0) | 35.1 | 48.6 (1.9 to 97.0; min 0.0, max 99.9) |
| S1 equal per column (sensitivity) | congo_basin | control | n/a | n/a | n/a | 51.9 (2.2 to 98.3; min 0.1, max 100.0) |
| S1 equal per column (sensitivity) | haughton | positive | 93.3 | 97.4 (90.9 to 100.0; min 83.7, max 100.0) | 24.8 | 49.2 (2.4 to 97.4; min 0.2, max 99.9) |
| S1 equal per column (sensitivity) | ladakh_puga | positive | 8.4 | 97.2 (89.8 to 99.9; min 81.6, max 100.0) | 8.3 | 51.3 (3.6 to 96.9; min 0.0, max 99.8) |
| S1 equal per column (sensitivity) | lonar | positive | n/a | n/a | n/a | 50.0 (2.4 to 97.9; min 0.0, max 100.0) |
| S1 equal per column (sensitivity) | mcmurdo_dry_valleys | positive | n/a | n/a | n/a | 49.6 (1.9 to 97.3; min 0.1, max 100.0) |
| S1 equal per column (sensitivity) | mdrs_utah | positive | 82.2 | 90.4 (69.0 to 99.7; min 42.6, max 100.0) | 27.5 | 51.7 (2.8 to 98.5; min 0.0, max 100.0) |
| S2 thermal 0.75 (sensitivity) | amazon_basin | control | n/a | n/a | n/a | 49.1 (2.2 to 96.8; min 0.1, max 99.3) |
| S2 thermal 0.75 (sensitivity) | atacama_salars | positive | 51.1 | 97.1 (89.1 to 99.9; min 80.3, max 100.0) | 30.5 | 49.3 (1.9 to 97.1; min 0.0, max 99.8) |
| S2 thermal 0.75 (sensitivity) | congo_basin | control | n/a | n/a | n/a | 51.7 (2.3 to 97.8; min 0.0, max 100.0) |
| S2 thermal 0.75 (sensitivity) | haughton | positive | 85.3 | 97.4 (90.4 to 99.9; min 83.6, max 100.0) | 44.2 | 48.8 (2.5 to 97.2; min 0.2, max 99.9) |
| S2 thermal 0.75 (sensitivity) | ladakh_puga | positive | 8.2 | 97.0 (89.5 to 99.9; min 81.6, max 100.0) | 8.1 | 52.7 (3.5 to 97.8; min 0.0, max 99.7) |
| S2 thermal 0.75 (sensitivity) | lonar | positive | n/a | n/a | n/a | 49.8 (2.4 to 98.4; min 0.0, max 100.0) |
| S2 thermal 0.75 (sensitivity) | mcmurdo_dry_valleys | positive | n/a | n/a | n/a | 49.4 (2.1 to 97.7; min 0.1, max 100.0) |
| S2 thermal 0.75 (sensitivity) | mdrs_utah | positive | 72.0 | 90.7 (67.4 to 99.7; min 37.3, max 100.0) | 24.0 | 51.4 (2.8 to 97.4; min 0.0, max 99.9) |

Chance column shows the first target's draw summary; the mean over targets is in `results/a_<variant>/secondary.json`.

### Mars positives, own-tile percentile (single nearest tile) against chance

Own tile = the tile nearest the site point, percentile among the gated tiles of the Jezero view. Chance = 1000 shuffled-feature draws, seed 20261114: mean (2.5 to 97.5 percentile range; min to max). `gated_out` = the nearest tile is rejected by a gate, so there is no number.

| Weighting | Site | Own tile | Chance, own tile | Best-of-radius | Chance, best-of-radius |
|---|---|---|---|---|---|
| v1 (terrain only) | atacama_salars | 42.3 | 50.5 (2.4 to 98.0; min 0.1, max 99.9) | 61.3 | 97.1 (89.7 to 99.9; min 77.8, max 100.0) |
| v1 (terrain only) | haughton | 35.0 | 50.5 (2.2 to 97.1; min 0.1, max 99.8) | 97.2 | 97.5 (91.3 to 99.9; min 85.8, max 100.0) |
| v1 (terrain only) | ladakh_puga | 16.0 | 50.9 (3.2 to 97.6; min 0.2, max 99.8) | 16.2 | 97.3 (89.9 to 99.9; min 79.6, max 100.0) |
| v1 (terrain only) | lonar | gated_out | 50.3 (3.0 to 97.5; min 0.1, max 99.7) | n/a | n/a |
| v1 (terrain only) | mcmurdo_dry_valleys | gated_out | 49.9 (2.8 to 96.4; min 0.0, max 99.8) | n/a | n/a |
| v1 (terrain only) | mdrs_utah | 37.1 | 49.2 (2.6 to 97.5; min 0.2, max 99.9) | 83.3 | 97.3 (90.7 to 99.9; min 81.8, max 100.0) |
| v2 headline H (thermal 0.5) | atacama_salars | 31.2 | 49.0 (1.9 to 97.0; min 0.0, max 99.8) | 52.7 | 97.1 (89.9 to 99.9; min 83.3, max 100.0) |
| v2 headline H (thermal 0.5) | haughton | 27.8 | 49.0 (2.6 to 97.7; min 0.2, max 99.9) | 86.6 | 97.4 (90.8 to 99.9; min 87.2, max 100.0) |
| v2 headline H (thermal 0.5) | ladakh_puga | 8.1 | 52.4 (3.5 to 98.0; min 0.0, max 99.7) | 8.3 | 97.0 (89.2 to 99.9; min 81.8, max 100.0) |
| v2 headline H (thermal 0.5) | lonar | gated_out | 49.9 (2.4 to 98.1; min 0.0, max 100.0) | n/a | n/a |
| v2 headline H (thermal 0.5) | mcmurdo_dry_valleys | gated_out | 49.7 (1.9 to 97.8; min 0.1, max 100.0) | n/a | n/a |
| v2 headline H (thermal 0.5) | mdrs_utah | 24.7 | 51.4 (2.9 to 97.7; min 0.0, max 99.8) | 75.0 | 90.8 (67.3 to 99.7; min 38.3, max 100.0) |
| S0 PREREG_A family weights (sensitivity) | atacama_salars | 36.3 | 48.6 (1.9 to 96.5; min 0.0, max 99.7) | 58.8 | 97.2 (90.1 to 99.9; min 81.7, max 100.0) |
| S0 PREREG_A family weights (sensitivity) | haughton | 26.0 | 49.3 (2.3 to 97.6; min 0.2, max 100.0) | 93.2 | 97.4 (90.9 to 99.9; min 84.5, max 100.0) |
| S0 PREREG_A family weights (sensitivity) | ladakh_puga | 8.3 | 51.3 (3.6 to 97.3; min 0.0, max 99.9) | 8.4 | 97.2 (89.8 to 99.9; min 81.3, max 100.0) |
| S0 PREREG_A family weights (sensitivity) | lonar | gated_out | 50.2 (2.4 to 97.9; min 0.0, max 100.0) | n/a | n/a |
| S0 PREREG_A family weights (sensitivity) | mcmurdo_dry_valleys | gated_out | 49.6 (1.9 to 97.0; min 0.1, max 99.9) | n/a | n/a |
| S0 PREREG_A family weights (sensitivity) | mdrs_utah | 24.8 | 51.7 (2.8 to 98.3; min 0.0, max 99.9) | 79.5 | 90.4 (69.3 to 99.6; min 41.4, max 100.0) |
| S1 equal per column (sensitivity) | atacama_salars | 35.1 | 48.6 (1.9 to 97.0; min 0.0, max 99.9) | 58.1 | 97.2 (90.3 to 99.9; min 81.8, max 100.0) |
| S1 equal per column (sensitivity) | haughton | 24.8 | 49.2 (2.4 to 97.4; min 0.2, max 99.9) | 93.3 | 97.4 (90.9 to 100.0; min 83.7, max 100.0) |
| S1 equal per column (sensitivity) | ladakh_puga | 8.3 | 51.3 (3.6 to 96.9; min 0.0, max 99.8) | 8.4 | 97.2 (89.8 to 99.9; min 81.6, max 100.0) |
| S1 equal per column (sensitivity) | lonar | gated_out | 50.0 (2.4 to 97.9; min 0.0, max 100.0) | n/a | n/a |
| S1 equal per column (sensitivity) | mcmurdo_dry_valleys | gated_out | 49.6 (1.9 to 97.3; min 0.1, max 100.0) | n/a | n/a |
| S1 equal per column (sensitivity) | mdrs_utah | 27.5 | 51.7 (2.8 to 98.5; min 0.0, max 100.0) | 82.2 | 90.4 (69.0 to 99.7; min 42.6, max 100.0) |
| S2 thermal 0.75 (sensitivity) | atacama_salars | 30.5 | 49.3 (1.9 to 97.1; min 0.0, max 99.8) | 51.1 | 97.1 (89.1 to 99.9; min 80.3, max 100.0) |
| S2 thermal 0.75 (sensitivity) | haughton | 44.2 | 48.8 (2.5 to 97.2; min 0.2, max 99.9) | 85.3 | 97.4 (90.4 to 99.9; min 83.6, max 100.0) |
| S2 thermal 0.75 (sensitivity) | ladakh_puga | 8.1 | 52.7 (3.5 to 97.8; min 0.0, max 99.7) | 8.2 | 97.0 (89.5 to 99.9; min 81.6, max 100.0) |
| S2 thermal 0.75 (sensitivity) | lonar | gated_out | 49.8 (2.4 to 98.4; min 0.0, max 100.0) | n/a | n/a |
| S2 thermal 0.75 (sensitivity) | mcmurdo_dry_valleys | gated_out | 49.4 (2.1 to 97.7; min 0.1, max 100.0) | n/a | n/a |
| S2 thermal 0.75 (sensitivity) | mdrs_utah | 24.0 | 51.4 (2.8 to 97.4; min 0.0, max 99.9) | 72.0 | 90.7 (67.4 to 99.7; min 37.3, max 100.0) |

### Mars primary median rank percentile (v1 rule, scorable and no-gated-tile sites as v1 reports them)

| Weighting | Median |
|---|---|
| v1 (terrain only) | 61.3 |
| v2 headline H (thermal 0.5) | 52.7 |
| S0 PREREG_A family weights (sensitivity) | 58.8 |
| S1 equal per column (sensitivity) | 58.1 |
| S2 thermal 0.75 (sensitivity) | 51.1 |

PREREG_A sha256 and addendum sha256 are stated at the top of this file and apply to every row above.

## What failed and what is NOT TESTED

- G1: FAIL. Coverage between 55 S and 60 N is 0.7340 against the pre-registered 0.85 (not met). At the five smoke-test points: rub_al_khali th_mean 306.2 K, th_max 324.6 K, th_dn 18.4 K; namib_sand_sea th_mean 303.4 K, th_max 328.0 K, th_dn 28.2 K; amazon_basin has no valid value; lonar th_mean 301.7 K, th_max 320.7 K, th_dn 15.7 K; haughton th_mean 253.5 K, th_max 283.9 K, th_dn 2.6 K. 94 of 2377 land blocks returned no data (south-polar rows; Earth Engine could not transform them).
- G2(a): namib_sand_sea 58.2, rub_al_khali 38.0 on the v1 site statistic (best-of-radius), maximum allowed 25.0.
- G2(b): 0 of 4 scorable Mars positives at or above the 95th percentile (needs 60 percent). Not scorable: lonar, mcmurdo_dry_valleys.
- G3 connecting_ridge_c1__base: 19 regions of at least 100 robust tiles and 100 km from known sites, 0 supported (24,841 robust tiles in v2, 9,693 in v1).
- G3 shackleton_rim__base: 31 regions of at least 100 robust tiles and 100 km from known sites, 2 supported (31,017 robust tiles in v2, 37,713 in v1).
- G3 jezero__base: 36 regions of at least 100 robust tiles and 100 km from known sites, 0 supported (37,015 robust tiles in v2, 49,465 in v1).

### Reading

- Descriptive change from v1 to H (thermal 0.5): Moon Namib best-of-radius 90.2 to 58.2, own tile 41.9 to 5.1; Moon Rub' al Khali best-of-radius 75.6 to 38.0, own tile 11.5 to 3.4; Moon Haughton best-of-radius 85.8 to 71.9, own tile 80.8 to 65.4; Mars Atacama best-of-radius 61.3 to 52.7, own tile 42.3 to 31.2; Mars MDRS best-of-radius 83.3 to 75.0, own tile 37.1 to 24.7; Mars Ladakh best-of-radius 16.2 to 8.3, own tile 16.0 to 8.1.
- Chance level for the best-of-radius statistic is about 97, so every best-of-radius value above sits below it. The own-tile statistic has chance level about 50.
- The thermal columns lower the Moon controls and the Mars positives together. Two causes are untested hypotheses: the thermal pair is a coarse physical match, and the Earth thermal set lacks the tiles with no thermal value (see the coverage finding).
- Coverage finding: under the pre-registered QC rule (QC bits 0-1 equal 0) the composites over central Australia carry bits 0-1 equal to 1 (other quality), so those tiles have no thermal value (checked at one point, 133 E 25 S, where all 229 composites carry bits 0-1 equal to 1; the regional validity shares are in the table above). Indonesia, the Amazon, parts of Siberia and the tropics lose most tiles to cloud and quality flags. Missing tiles are rejected as missing data, so the Earth set that is scored is not a random sample of Earth. This was not corrected; a rerun with bits 0-1 in {0, 1} would be a separate, labelled sensitivity.
- The Moon thermal target ranks come from only the two polar PRP sites inside a south-polar set; the Mars target from Jezero alone. Neither is checked against any positive.

### Not run or not tested

- Moon layer-2 recall: NOT TESTED (two positives, one gated out).
- Arcadia: NOT TESTED (no centre in the v1 target list, no thermal reference).
- Moon ice depth, diurnal range, cold-trap share; Mars surface temperature: not scored (no Earth partner or no source).
- Failed Earth Engine blocks stay NaN and their tiles are rejected as missing data; see STATUS_A.md for the count.

## Deviations

1. Engine commit. PREREG_A named origin/main ca9a816. The v1 results were produced by a7d96d9 (local branch `integrate`, 59 commits ahead, not on origin). The baseline only reproduces v1 with a7d96d9, so its `src`, `config` and `tests` were imported into this branch.
2. Config wording. PREREG_A said the thermal columns replace the family columns. The config keeps the dropped v1 columns in the family lists and adds the thermal columns, so the v1 `drop_columns` lists need no change. The active columns are the same.
3. Weights. The headline weighting is the addendum's H, not the family weights written in PREREG_A. The PREREG_A weighting is reported as S0.
4. Mars radius. PREREG_A wrote 3389.5 km; Role B used 3396.0 km (label). Both give the same 38 pixels at Jezero and the same medians.
5. Earth Engine blocks. 50 x 50 tile blocks, split into halves where a block exceeded the memory limit or could not be transformed near the poles; two worker processes. Not outcome-affecting.
6. Profiles. Only the base profile was run, as PREREG_A states.
7. Two log files were committed by mistake in 978910c and untracked later (no secrets).
