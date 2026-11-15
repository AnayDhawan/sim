# PREREG_A addendum 1: weights, site-statistic checks and illumination sensitivity (ROLE A)

Registered: 2026-11-15 09:08 IST. This file was added after PREREG_A (sha256 `1758b132701ea831dea51c82ee9ebc3bd5c2c3a9e1544fdfe3eb7cd7a1e7992e`, git blob `38d81060d2bea823f753b0537f1fd99aa9d203ef`) and before any v2 score was computed or read. Nothing below is edited after its hash is recorded.

## What had been computed before this addendum (disclosure)

- The terrain-only baseline with the v1 config and v1 Earth file (the v1 numbers, reproduced: Namib 90.19, Rub' al Khali 75.56, Mars median 61.29). These are v1 results, not v2 results.
- One smoke test of the thermal scoring path on a partial Earth thermal file (Mars, 50 Monte Carlo runs, most tiles gated out for missing data). Its outputs were deleted without being read.
- A read-only audit of the v1 engine (`C:\Users\lenovo\ENGINE_AUDIT.md`) that shuffled v1 terrain features. It contains no thermal score. Items 2 and 3 below follow from it.
- No v2 control score, positive score or Mars median had been seen when this file was written.

## 1. Weights

Supersedes the weighting sentence in PREREG_A, section Re-scoring. Everything else in PREREG_A stays (sets, ranks, QC rule, gates, seed).

Headline (H): the thermal group carries 0.5 of the total score and the terrain group 0.5. Inside a group every active column has the same weight. Family similarity stays the mean of its columns, so a family with n columns gets `group_share * n / n_group_columns`.

- Moon, 7 terrain columns, 2 thermal columns: slope 0.142857, illumination 0.142857, roughness 0.142857, relief 0.071429, temperature (th_mean, th_max) 0.5.
- Mars, 6 terrain columns, 1 thermal column: slope 0.166667, sunlight 0.166667, relief 0.083333, elevation_density 0.083333, thermal_inertia (th_ti) 0.5.
- Active columns are the v1 active columns (the v1 `drop_columns` lists stay) plus the thermal columns.

Sensitivity weightings, same data and engine, base scores only (no Monte Carlo), labelled as sensitivity wherever shown:

- S0: the PREREG_A weighting (v1 derived family weights with the thermal columns added to their families).
- S1: every active column equal (thermal share 2 of 9 on the Moon, 1 of 7 on Mars).
- S2: thermal group 0.75, terrain group 0.25, equal per column inside each group.

Monte Carlo (headline H only, 2000 runs, seed 20261114): each family weight is drawn uniformly in [0.7 w, 1.3 w] around its H weight, then renormalised, the same draw rule as v1. The 30 percent half-width is chosen here and is not from a source. It is applied to every family so no family is favoured.

G3 uses the H run. The thermal-family similarity in G3 (ii) is the mean of the similarities of the thermal columns.

## 2. Secondary site statistic and chance level

Added next to, never instead of, the v1 site statistic. Reported for every labelled site, for the v1 baseline and for H, S0, S1, S2 (and S3 below):

- Moon sites: lonar, haughton (positives); rub_al_khali, namib_sand_sea, amazon_basin, congo_basin (controls). Mars sites: the six primary sites and amazon_basin, congo_basin. Per target and as the mean over the body's targets, as v1 does.
- Best-of-radius percentile: the v1 statistic (best score over the gated tiles within the match radius, percentile among the gated tiles of the view).
- Own-tile percentile: the tile whose centre is nearest to the site point, percentile among the gated tiles of the view with the same rule `100 * mean(scores < value)`. If that tile is not gated, the entry is `gated_out` and has no number.
- Chance level beside every percentile: shuffle seed 20261114, 1000 draws. Rows of the gated feature table are permuted jointly; because a tile's score depends only on its own row, the shuffled null for a site equals drawing `n` random scores without replacement from the view's score vector, with `n` the number of gated tiles in the radius (best-of-radius) or 1 (own tile). The code draws from the score vector. One generator per view, seeded 20261114, sites taken in alphabetical order. Reported: mean, the 2.5th to 97.5th percentile range over the draws, and min to max.
- These numbers are descriptive. They are not gates and no gate rule changes because of them.

## 3. Illumination

The Moon illumination family has near-zero similarity for every Earth tile (ENGINE_AUDIT.md, check 5). The headline keeps it, as PREREG_A defines. Post-PREREG sensitivity, labelled so wherever shown (S3): Moon scores with the illumination family removed, once for the v1 terrain-only baseline (v1 weights) and once for H (terrain share 0.5 spread equally over the remaining 5 terrain columns).

## 4. Gates

G1, G2 (a), (b), (c) and G3 stay as written in PREREG_A, evaluated on H. `results_a.md` carries this line: "G2(a) cannot be met by construction under a best-of-35-tiles score; G2(b) passes by chance about 83% of the time. See ENGINE_AUDIT.md."

## 5. Reporting

`results_a.md` and `metrics.json` report, as a descriptive result whatever the gate status: control scores and the Mars primary median for v1, for H, and for S0, S1, S2, each with the PREREG_A sha256, this addendum's sha256, and the chance level. `results_a.md` states that this addendum was added after PREREG_A and before any result.

## 6. Housekeeping

`pull_stdout.log` and `ref_stdout.log` were committed by mistake in 978910c. They hold only block counts and file names (checked for tokens, keys and credentials: none). They are untracked and ignored from this commit on.
