# Results schema (`gsop s8 export`, `gsop merge`)

`results/<body>/export/` is written by `gsop s8 export --body <body>`. `gsop merge` copies the two bodies into `results/all/<body>/` and writes `results/all/index.json` and `results/all/MANIFEST.json`. Every file is under 3 MB. `MANIFEST.json` holds the sha256 and size of each file; the site should verify it. `schema_version` is 1.

## `index.json` (per body and merged)

Per body: `{schema_version, body, views: [{name, target, profile, confidence, fails_own_gate, fidelity, n_robust, dropped_columns}], unscored: {name: reason}}`.
Merged: `{schema_version, views: [... plus body], run_meta: {moon|mars: {git_commit, config_hash, earth_hash}}, warnings: []}`.

- `name` is `<target>__<profile>`.
- `confidence` is `standard` or `low`.
- `unscored` lists targets that were not scored and why (for example Arcadia: no target data).

## `candidates__<target>__<profile>.json`

`{schema_version, body, target, profile, confidence, fails_own_gate, runs, n_robust, n_gated_tiles, candidates: [...], truncated_to_fit_3mb?}`

Each candidate (top 500, robust first, then by `mc_median`):

| Field | Type | Meaning |
|---|---|---|
| tile_id | int | `iy * 5790 + ix` on the EPSG:6933 6 km grid |
| lat, lon | float | tile centre, degrees |
| score_base | float | base similarity, 0 to 100 |
| mc_median, mc_p05, mc_p95 | float | Monte Carlo score band |
| rank_pct_p05, rank_pct_p50, rank_pct_p95 | float | rank percentile among gated tiles, 100 is best |
| freq_top1, freq_top5, freq_top10 | float | share of runs in the top 1, 5, 10 percent |
| robust | bool | top 5 percent in at least 90 percent of runs |
| illum_match | float | illumination (or sunlight) family similarity alone, 0 to 1 |

## `convergence__<target>__<profile>.json`

`{metric, n_tiles_top1pct, overlap_membership: {"500": j, ...}, overlap_mean_score: {...}, candidates, candidates_truncated}`

## `fidelity.json`

`{body, relevance_provisional, per_purpose: {profile: {fidelity, n_rows, rows: [{id, status, provisional}], reason}}, ledger: [{id, property, target, earth, status, source, provisional}], note}`. Fidelity is 0 to 100 and is never part of the score. The relevance matrix is a draft.

## `validation.json`

`{preregistered: {criteria, radius_km_source, body, site_score_rule, gated_out_rule, amendment, control_rule, unconfirmed_sites}, preregistered_sha256, registered_at, status, provisional, slope_ground_scale_corrected, slope_limitation, results: {primary, negative_controls, secondary, gate_tests, primary_median_rank_pct, negative_control_max_rank_pct, criteria_status: {<criterion>: {status: pass|fail|not_testable, reason}}, pass: {<criterion>: true|false|null, all}, n_primary_sites, n_scorable_primary_sites, gated_out_primary_sites}}`. Always `provisional: true` until site coordinates are confirmed.

Each primary, negative-control and secondary site has `status`: `scored` (`rank_pct`, `per_target`), `no_gated_tile` (`rank_pct` 0, `per_target` notes) or `gated_out` (`rank_pct` null, `n_tiles_within_radius`, `gate_reasons`, `first_gate_reason`, `ungated_terrain_only: {label: "outside the pre-registered test, informational", rule, status: computed|no_terrain_yet|..., per_target: {<target>: {best_tile, best_score, rank_pct_among_gated}}, rank_pct}`). E28, SPEC section 10. `negative_controls` lists only the controls whose `bodies` include the run's body (E30: rub_al_khali and namib_sand_sea are Moon only).

Slope label (E29): `run_meta.json`, `validation.json`, every `summary.json`, and `export/index.json`, `export/fidelity.json`, `export/candidates__*.json` carry `slope_ground_scale_corrected: false` and `slope_limitation`. A `--lat-band` run adds `lat_band_abs_deg` and `lat_band_note` to `run_meta.json` and `export/index.json`.
