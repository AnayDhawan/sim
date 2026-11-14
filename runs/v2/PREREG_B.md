# PREREG_B: reference-side thermal features (ROLE B)

Registered: 2026-11-15, before any download beyond HEAD tests. Nothing in this file changes after results are seen. Deviations go in a separate dated section at the bottom, never as edits above.

Seed: 20261114 (no stochastic step is planned; the seed is reserved in case one is added, and any addition is logged as a deviation).

## Scope and hard exclusions

- Role: Moon and Mars thermal features at reference sites. Earth side and scoring belong to ROLE A.
- The LLM-estimated numbers in `data/raw/*.csv` (`Similarity_pct`, `P_*`, `MonteCarlo_*`, `MC_rank_range_of_60`) are never used as features, labels or thresholds. In this clone the files sit in `data/raw/`, not `data/reference/raw/`.
- Tag `v1-final` does not exist in this clone (`git tag` is empty, `git ls-remote --tags` is empty). Nothing is tagged, so nothing can be moved. New work goes to `runs/v2/`, `data/reference/` and `docs/refs_limits.md` only.
- Wording: the words "validated", "discovered", "undiscovered" and "new sites" are not used.

## Sites

Source: `config/targets.yaml` at origin/main ca9a816 (the v1 reference targets). `lon_e` is degrees east, 0 to 360.

| site_slug | body | lat | lon_e | source in config | thermal product |
|---|---|---|---|---|---|
| connecting_ridge_c1 | moon | -89.45 | 222.84 | Glaser 2018 | PRP south |
| shackleton_rim | moon | -89.78 | 203.97 | Glaser 2018 | PRP south |
| jezero | mars | 18.4386 | 77.5031 | Grant 2018 | TES TIMAP |
| arcadia | mars | none | none | no published centre (docs/DECISIONS.md D10) | not covered |

- Arcadia stays "not covered": no coordinates are guessed.
- No non-polar Moon site exists in the v1 target list, so RCP (Lacus Mortis tile) is "not covered" for every site. It is not downloaded.
- "Shackleton ridge" means Connecting Ridge C1. The name C2 is not used.
- C1 and Shackleton rim centres are about 10.6 km apart (great-circle, 1737.4 km sphere). Radius R below keeps the primary windows disjoint.

## Site radius R

- Polar Moon (PRP): primary R = 5 km. Sensitivity R = 2.5 km and R = 10 km, computed in the same pass, reported as separate rows. The 10 km windows overlap; that is stated wherever they are shown.
- Mars (TES): R = 10 km (a 20 pix/deg pixel is about 3 km at the equator, so this takes roughly 3 to 5 pixels). Pixels are selected by centre distance.
- Distance: great-circle on a sphere of radius 1737.4 km (Moon) and 3389.5 km (Mars), computed from 3D unit vectors, so longitude wrap and the pole cause no special cases. PRP triangles are selected by centroid (`tri_clat`, `tri_clon`).

## Features and the pairs ROLE A will use

ROLE A compares each pair by percentile rank within each body's own set, never by absolute value.

| Moon / Mars feature | Source layer | Earth partner (ROLE A) |
|---|---|---|
| Moon temp_avg | PRP `temp_avg` (K, annual average at 2 cm depth) | annual mean of (day+night)/2 |
| Moon temp_max | PRP `temp_max` (K, annual maximum surface temperature) | annual maximum of monthly day LST |
| Moon diurnal range | RCP or PCP, only where they exist | day-night range |
| Mars thermal inertia | TES TIMAP day and night maps, 2007 | day-night range, inverted (proxy) |
| Moon ice_depth | PRP `ice_depth` (m) | reference context only, not scored |

Per feature and site, these statistics are written: n, median, mean, p5, p95, min, max (PRP and TES), plus the layer-specific items below.

- PRP `temp_avg`, `temp_max`: statistics over triangles inside R. No invalid-value handling is expected; any value outside 0 to 500 K is counted, excluded, and reported.
- PRP `ice_depth`: count of `-999` triangles (invalid, deeper than 2.8738 m) reported separately as `n_invalid_999` and `frac_invalid_999`. Median, p5 and p95 are taken over valid triangles only. `-999` is never averaged.
- Cold-trap fraction: share of triangles inside R with `temp_max` below the threshold. Unweighted by triangle area (triangle edges are about 500 m, near uniform); the area-weighted version is also written and labelled.
- Moon diurnal range: PCP polar diurnal files are about 250 MB per local-time file and 96 per season. They are not downloaded. Diurnal range is "not covered" for both polar sites. It stays "not covered" even if step 2 shows byte-range support, because a range-read plan would be a new design made after this registration.
- Mars thermal inertia: `global_ti_day_2007` and `global_ti_night_2007`. Scale factor and fill value are read from each `.lbl` file, not from `datainfo.txt`. Mask files: value 0 marks an interpolated pixel (read from each mask's own `.lbl`, because `datainfo.txt` has a copy error in the night-mask text). Reported: median day TI, median night TI, `frac_interpolated` for each map, and the same statistics restricted to non-interpolated pixels.
- Mars surface temperature: "not covered".
- LOLA terrain: skipped (v1 has Moon terrain).

## Cold-trap temperature threshold

- Threshold: 110 K applied to PRP `temp_max`.
- Sources:
  - Hayne et al., "Micro cold traps on the Moon", Nature Astronomy (2020 online): regions below 110 K are termed cold traps, thermal lifetime of water ice comparable to or longer than the age of the solar system.
  - Williams et al. 2019, JGR Planets 124:2505, doi 10.1029/2019JE006028: 110 K contour map of cold-trapping surfaces from Diviner.
  - Diviner team summary: https://www.diviner.ucla.edu/single-post/2020/07/20/new-diviner-seasonal-polar-data-products
- Verification status: the 110 K figure was confirmed in search-result text on 2026-11-15 for the Hayne paper and the Diviner team summary. The full papers were not opened. If the full text disagrees, the number stays 110 K for this run and the disagreement is logged as a deviation.
- Caveat to carry into `docs/refs_limits.md`: PRP `temp_max` is a modelled maximum surface temperature on a roughly 500 m mesh. Sub-mesh cold traps (Hayne et al.) are invisible to it, so the cold-trap fraction is a lower bound for the resolved scale.

## Data products (cited in code comments; the label wins if it disagrees, and the difference is logged)

- Diviner Derived Bundle 1, v5.0, DOI 10.17189/wj0s-w188: https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/
  - Only `data_derived_prp/dlre_prp_south.tab` (604,800,210 bytes, 2,880,000 records x 210 bytes) and its label `dlre_prp_south.xml`. The north file is not downloaded: no v1 site is north of 80 N.
- MGS TES TIMAP, DOI 10.17189/1519489: https://pds-geosciences.wustl.edu/mgs/mgs-m-tes-5-timap-v1/mgst_9001/data/
  - `global_ti_day_2007.img`, `global_ti_night_2007.img` (3600 x 7200 int16 MSB, 51,840,000 bytes each), their masks and all four `.lbl` files.
- Not downloaded: PCP, GDR L3, RCP, the 128 pix/deg global files, GHRM.
- Download estimate: PRP south 605 MB, TES maps and masks about 210 MB, labels under 1 MB. Total about 0.82 GB.

## Outputs

- `data/reference/thermal_refs.csv`, columns: `site_slug, body, layer, stat, value, units, product, version, source_url, sha256`. One row per site, layer and stat. A layer with no data gets one row per site with `stat = not_covered`, an empty `value` and the reason in the `layer` note column of `docs/refs_limits.md`.
- The `sha256` column holds the sha256 of the source file the number came from.
- Sensitivity rows carry the suffix `_R2p5km` or `_R10km` on `stat`. Primary rows have no suffix.
- `docs/refs_limits.md`: per layer, where it cannot match Earth (for example Earth has no surfaces near 40 K, so Diviner absolute temperatures cannot be matched and only relative features are used).
- `runs/v2/STATUS_B.md`, `runs/v2/logs/`, and the download cache are never committed.

## Failure-first checks written before running

- Record count of the PRP file must equal file size / 210 (2,880,000). A mismatch stops the run.
- PRP triangle count inside R for each site is printed. Fewer than 20 triangles for the primary R is reported as a failure of that site, not patched with a bigger R.
- Sanity check on the pipeline, not on the science: the number of `temp_max` values below 110 K across the whole south file must be nonzero (cold traps exist poleward of 80 S). Zero means a parsing fault.
- Jezero: `frac_interpolated` above 0.5 within R is flagged, and the interpolated-excluded statistics are the ones reported as primary in that case. The rule is fixed now; the 0.5 is not tuned later.
