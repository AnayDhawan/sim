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
  4. Roughness at baseline b: split the native DEM into b by b windows, fit and remove a plane, take the RMS residual per window. The tile value is the median window RMS. `rough_a` uses 300 m and `rough_b` 1000 m on every body (target-side E22: Earth terrain comes from a 90 m DEM, so 100 m was finer than the data). TODO: confirm with Vihaan.
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
- `rough_a` and `rough_b` need native cells of at most 100 m and 333 m and are always left out by the fallback.
- A left-out column is absent from the raster, so the missing-data gate (section 6) rejects every tile for a target that needs it and says why; scoring stops loudly (section 7) unless a person lists the column in `run.yaml drop_columns`.
- Only the slope gradient is corrected for the projection's ground scale (section 11). The 500 m slope cell, the roughness windows and the 6 km tile are still projected metres, so they are not square on the ground (see the anisotropy note below).
- Climate layers are only resampled; no temporal aggregation is done.

**Anisotropy note (Earth tiles against Moon and Mars windows).** EPSG:6933 is cylindrical equal-area. A projected distance `d` is `d * kx` ground metres east-west and `d / kx` ground metres north-south, with `kx = cos(lat) / cos(30 deg)`. `operators.slope_deg(kx=...)` uses this to correct the *gradient* (dz/dx and dz/dy), and nothing else. Everything that is a length is still in projected metres, so on Earth:

| Latitude | 500 m slope cell on the ground (E-W x N-S) | 6 km tile on the ground | 300 m roughness window |
|---|---|---|---|
| 30 deg | 500 x 500 m | 6.0 x 6.0 km | 300 x 300 m |
| 60 deg | 289 x 866 m | 3.5 x 10.4 km | 173 x 520 m |
| 80 deg | 100 x 2,494 m | 1.2 x 29.9 km | 60 x 1,496 m |

With the SRTM90 route (target-side E22) Earth terrain exists only from 56 S to 60 N (catalog STAC bbox of `CGIAR/SRTM90_V4`, -56 to 60), so the 80 deg row does not occur in practice; see section 3d.

Moon targets use square ground cells (polar-stereographic rasters, scale factor about 1 near the pole, so windows of 6 km and 500 m on the ground). Mars windows are square in the DEM's own projected metres; on a simple-cylindrical MOLA raster with true scale at the equator, east-west is cos(lat) shorter on the ground (about 5 percent at Jezero, 18.4 deg), far less than the Earth figures above. So a Moon slope at a 500 m baseline and an Earth slope at "500 m" away from 30 deg latitude are measured over different ground footprints, and Earth roughness at 300 m and 1000 m is taken over elongated windows. The gradient is right; the footprint is not the same. This is open (see `docs/UNVERIFIED.md`); it is not a bug in the arithmetic.

## 3d. Earth terrain latitude limit (SRTM90 route, target-side E22)

- Earth terrain comes from SRTM90 (`CGIAR/SRTM90_V4`, 90 m) on a 100 m working grid. Its catalog STAC bbox is longitude -180 to 180, latitude -56 to 60 (read 2026-11-13). Tiles outside 56 S to 60 N get no `slope_med`, `slope_p90`, `relief`, `rough_a`, `rough_b`, so the missing-data gate (section 6) rejects them for every Moon and Mars target. They are unscorable, not low-scoring. Nothing is filled from another DEM unless a person adds one.
- Known sites outside the band (`config/known_sites.yaml`):
  - `haughton` (75.37 N), primary for Moon and Mars. There is no gated tile within 20 km, so it has no site score and cannot count towards the validation criterion.
  - `mcmurdo_dry_valleys` (77.5 S), primary for Mars, same consequence.
  - `samoylov` (72.37 N), gate test. It will be rejected, but as `missing_data`, not by the water gate it is meant to test.
  - `askja` (65.03 N), secondary. It is still excluded from discovery by distance, but it has no score of its own.
- Every other known site lies inside the band: lonar, ladakh_puga, atacama_salars, mdrs_utah, sf_volcanic_field, gosses_bluff, mauna_kea, manicouagan_centre, manicouagan, tatacoa, amazon_basin, congo_basin.

## 3e. Earth feature assembly from the Drive downloads (`gsop s2 assemble`, E27)

Code: `src/gsop/earth/assemble.py`. Command:

    uv run gsop s2 assemble --gate <gsop_gate folder> --terrain <gsop_terrain90 folder> --terrain-hi <gsop_terrain90_hi folder>

- Inputs, all EPSG:6933 with 6000 m cells, searched recursively, every file placed by its own affine transform on the global grid (origin x = -17,367,530.445 m, y = 7,342,230.136 m, 5,790 columns x 2,448 rows). A file whose origin is not on the grid, or that falls outside it, is an error.
  - gate: `gate_6km_r??_c??[_p?][_s?].tif`, 4 bands `land_frac`, `water_ice_frac`, `ndvi_median`, `built_crop_frac` (`gee_export.landcover_bands`).
  - SRTM90 terrain: `terrain90_r??_c??[_r?].tif`, 6 bands `slope_med`, `slope_p90`, `relief`, `elev_mean`, `rough_a`, `rough_b` (`gee_export.terrain_bands(100.0, "srtm90", (3, 10))`).
  - GLO30 terrain: `terrain90_stage1_<site>_*.tif` and `terrain90_stage2_*.tif`, same 6 bands (`terrain_glo30_image`).
  - Band descriptions, when present, must equal the expected order exactly; a file without descriptions is read in that order. Files whose names match none of the patterns are skipped and listed in the report.
- Missing: NaN, -9999 (`TERRAIN90_NODATA`, written by the export for masked cells) and a declared nodata value.
- Overlaps inside one source: Earth Engine writes one extra edge row or column that the neighbouring chunk also covers (seen in the real downloads: 84 overlapping SRTM pairs, 15 gate pairs, the extra edge all NaN in one of the two files). Split retries (`_r0`, `_r1`, pieces of a failed parent that has no file of its own) and Drive duplicates (`name (1).tif`) can cover the same cells again. Rule: a finite value beats a missing one; two finite values must agree within rtol 1e-5, atol 1e-6, otherwise the build stops and names both files. Each tile is counted once.
- Precedence between terrain sources: SRTM90 for tiles whose centre latitude is at or below 60 N, GLO30 above 60 N. Where the preferred source has no complete value the other one is used (GLO30 stage-1 boxes south of 56 S, SRTM margin rows just north of 60 N). This adds the GLO30 tiles that section 3d lists as missing (haughton, samoylov, askja, mcmurdo_dry_valleys boxes, E23), as far as their tasks finished.
- Land: `land_frac >= 0.5` (finite). One row per land tile, `tile_id = iy * 5790 + ix`, sorted by tile_id. Columns: `tile_id, ix, iy, lon, lat, water_ice_frac, ndvi_median, built_crop_frac, slope_med, slope_p90, relief, elev_mean, rough_a, rough_b`, then (default `--add-solar`) `sun_max_elev, sun_low_share, insol_annual` from latitude (`earth/solar.py`) and `air_density` from `elev_mean` (`astro.py`, E26). Land tiles without terrain keep NaN terrain (and NaN `air_density`), so the missing_data gate rejects them. Tiles whose gate file was not downloaded are not in the table at all.
- Outputs next to the parquet: `grid.json`, `earth_coverage.json` (files per source, land tiles, tiles per terrain source, tiles in both, tiles with complete and NaN terrain, share covered, NaN tiles north of 60 N and south of 56 S) and, for the default output path, `MANIFEST.json` over everything in `data/processed` (so `gsop verify-data` passes on the receiving machine).
- Slope in these downloads is not kx corrected (E25).
- Memory: one global float32 gate mosaic (4 x 14.2M cells, about 230 MB) plus per-tile terrain arrays. Measured on the partial real downloads (48 gate, 219 SRTM, 27 GLO30 files): 13 s.

## 3f. Slope bias of the downloaded Earth terrain (E25, E29)

The terrain90 and GLO30 downloads were computed without the kx ground-scale correction, so the Earth slope is read on projected EPSG:6933 metres. Accepted and labelled (E29): every results output carries `slope_ground_scale_corrected: false` and a one-line limitation (`provenance.SLOPE_LABEL`). Uncorrected Horn slope of a plane with a known true slope, by latitude and slope direction (`tests/test_kx_slope.py::test_bias_table_in_spec`, the numpy mirror of the Earth Engine expression; value read, then error in degrees):

| Latitude | kx | 10 deg east-west | 10 deg north-south | 20 deg east-west | 20 deg north-south |
|---|---|---|---|---|---|
| 0 | 1.155 | 11.51 (+1.51) | 8.68 (-1.32) | 22.80 (+2.80) | 17.50 (-2.50) |
| 20 | 1.085 | 10.83 (+0.83) | 9.23 (-0.77) | 21.55 (+1.55) | 18.54 (-1.46) |
| 30 | 1.000 | 10.00 (+0.00) | 10.00 (+0.00) | 20.00 (+0.00) | 20.00 (+0.00) |
| 40 | 0.885 | 8.87 (-1.13) | 11.27 (+1.27) | 17.85 (-2.15) | 22.37 (+2.37) |
| 50 | 0.742 | 7.46 (-2.54) | 13.36 (+3.36) | 15.12 (-4.88) | 26.12 (+6.12) |
| 60 | 0.577 | 5.81 (-4.19) | 16.98 (+6.98) | 11.87 (-8.13) | 32.23 (+12.23) |

- The bias is smallest near 30 deg latitude (zero at 30 deg, where kx = 1) and grows toward the equator and, faster, toward the poles. East-west slopes read too steep equatorward of 30 deg and too gentle poleward; north-south slopes the reverse. Real terrain has slopes in all directions, so a tile median is biased less than the single-direction planes above, but not by a known amount.
- Robustness run: `gsop run --body moon --lat-band 20 40` scores only Earth tiles with absolute latitude 20 to 40 deg inclusive (within about 1.5 deg of the true value for a 10 deg slope). It restricts which tiles are scored; it is not a gate and never appears as a rejection reason. Results go to `results/moon_lat20-40/`, and run_meta.json and export/index.json carry `lat_band_abs_deg`. `scripts/compare_runs.py results/moon results/moon_lat20-40` reports per target and profile the Jaccard overlap of the top 1 percent (base score) and of the robust sets, both raw and with the full run restricted to the band, and lists the full run's top-20 robust tiles that lie outside the band (the band run cannot check them).

## 3g. DEM seam at 60 N (E22, E23, E27)

Measured 2026-11-14 with `scripts/seam_test.py`: the same two boxes, both below 60 N where SRTM90 and Copernicus GLO30 both have data, run through `terrain_bands(100.0, "srtm90", (3, 10))` and `terrain_bands(100.0, "glo30", (3, 10))` (the graphs of the production exports) and downloaded with `getDownloadURL` (interactive, no export). Difference is GLO30 minus SRTM90 per tile; relative difference is that over the SRTM90 value; p05/p95 are the 5th and 95th percentile of the relative difference over tiles. Units: slope deg, relief m, elev_mean m, rough_a and rough_b m.

Box A: lon 7.36 to 8.67 E, lat 58.11 to 59.92 N (EPSG:6933 cells ix 3013, iy 166, 20 x 20 tiles), southern Norway, relief about 414 m per tile. 385 tiles valid in both DEMs (386 SRTM90, 400 GLO30; the rest is sea or fjord masked in SRTM90).

| Feature | Median SRTM90 | Median GLO30 | Median diff | Median rel diff | p05 / p95 rel diff | Pearson | Spearman |
|---|---|---|---|---|---|---|---|
| slope_med | 4.44 | 4.48 | +0.035 | +0.9% | -3.9% / +5.2% | 0.998 | 0.998 |
| slope_p90 | 10.05 | 10.11 | +0.031 | +0.4% | -2.6% / +3.9% | 0.999 | 0.999 |
| relief | 414.0 | 413.3 | +2.16 | +0.6% | -1.2% / +2.6% | 0.9995 | 0.9995 |
| elev_mean | 617.5 | 617.1 | -0.35 | -0.07% | -0.6% / +0.3% | 1.000 | 1.000 |
| rough_a (300 m) | 3.57 | 4.32 | +0.68 | +18.9% | +9.3% / +31.7% | 0.978 | 0.966 |
| rough_b (1000 m) | 19.51 | 21.07 | +1.11 | +5.7% | 0.0% / +11.8% | 0.996 | 0.995 |

Box B: lon 13.27 to 14.58 E, lat 58.11 to 59.92 N (ix 3109, iy 166, 20 x 20 tiles), central Sweden, relief about 67 m per tile. 400 tiles valid in both.

| Feature | Median SRTM90 | Median GLO30 | Median diff | Median rel diff | p05 / p95 rel diff | Pearson | Spearman |
|---|---|---|---|---|---|---|---|
| slope_med | 0.66 | 0.67 | +0.000 | +1.3% | -7.9% / +10.3% | 0.999 | 0.999 |
| slope_p90 | 1.63 | 1.66 | +0.006 | +1.0% | -6.6% / +9.0% | 0.999 | 0.998 |
| relief | 67.1 | 66.5 | +0.20 | +0.7% | -5.5% / +7.8% | 0.999 | 0.999 |
| elev_mean | 114.8 | 113.3 | -1.53 | -2.0% | -3.8% / +0.1% | 1.000 | 1.000 |
| rough_a (300 m) | 0.95 | 1.39 | +0.36 | +37.1% | +15.7% / +68.2% | 0.983 | 0.973 |
| rough_b (1000 m) | 3.49 | 4.20 | +0.50 | +14.0% | -2.0% / +33.5% | 0.991 | 0.990 |

- Slope, relief and elevation agree to about 1 to 2 percent in the median with correlation of at least 0.998. `rough_a` reads higher in GLO30 by 19 percent (box A) and 37 percent (box B) in the median, `rough_b` by 6 and 14 percent. The two DEMs rank tiles almost identically (Spearman at least 0.966), so the step is a level shift, not a reordering.
- Two boxes, one latitude band (58 to 60 N), both forested. Nothing was measured above 60 N (SRTM90 has no data there), at other latitudes, or on bare ground. The cause of the roughness step (resolution, noise or DEM type) was not isolated.
- Effect on the table: tiles above 60 N use GLO30 (section 3e), so their `rough_a` and `rough_b` sit above what SRTM90 would give for the same ground by the amounts above. 30,654 of the 2,210,031 tiles with terrain lie above 60 N (1.4 percent). In the finished 2,000-run results (commit `170c76d`) the robust tiles above 60 N number, per job: Moon connecting_ridge_c1 base 111 of 10,197, landing_mobility 449 of 12,861; Moon shackleton_rim base 692 of 30,982, landing_mobility 535 of 16,502; Mars jezero base 83 of 41,091, landing_mobility 241 of 36,315, power_night 1 of 42,761. Raw seam script output is written by `scripts/seam_test.py --out`; the files are not committed.

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
- A human can drop a column on purpose with `run.yaml: drop_columns`. The column leaves its family (an empty family leaves the weights), weights are renormalised, and the dropped list is written into every output. `drop_columns` is either a list (every body) or a mapping `{all, moon, mars}` (per body; a listed column must belong to that body's families).
- A human can also decide not to run a purpose profile with `run.yaml: skip_profiles` (`{body: {profile: [missing columns]}}`). It is never scored, and every output lists it as not run with those columns named. `base` cannot be skipped.
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

**Run-to-run variation is large on this machine.** The first measurement of the same configuration (the earlier, uncommitted script) took 331 s: pass 1 137 s, pass 2 162 s. With only 1.4 GB free on an 8 GB machine that was also running other things, the two runs differed by 20 percent; with only two runs that spread is not characterised, so treat the figures as "about 4.5 to 5.5 minutes", not as a precise number. The first run's 33 s outside the two passes was not split at the time. On the second run the two parts that were not timed before (merge/select and finalise) took 4.4 + 26.6 = 31 s, which accounts for it; that is an inference from the second run, not a measurement of the first. `MCResult.timings_s` now reports all four parts, and `summary.json` carries them.

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
- Amendment E28 (2026-11-14, decided before any real run; the criteria block and its sha256 changed, Moon 9ea263ae... to 5474d029..., Mars 6af0d520... to df12845a...):
  - A site is `gated_out` when at least one land tile lies within its radius, none passes the gates, and every one fails at least one land-cover gate (open water or ice, vegetated, built or cropland) on its own gate layers. It is reported on its own line with `gate_reasons` (count of tiles per first failing land-cover gate) and `first_gate_reason`, and gets no rank.
  - The primary median is over scorable primary sites (every primary site that is not gated_out). A primary site with no gated tile for another reason (missing data, no land tile) still counts with rank 0. With fewer than `primary_min_scorable_sites` (2) scorable primary sites for a body the criterion is `not_testable`, neither pass nor fail.
  - Negative controls: only controls with a gated tile within the radius count toward the maximum. A gated-out control is reported `gated_out` (not rank 0) and is not counted as below the 25th percentile; with no such control the criterion is `not_testable`. Gate tests are unchanged.
  - `results.criteria_status` gives pass, fail or not_testable with a reason per criterion; `results.pass` holds true, false or null (not testable); `pass.all` is true only if all three pass, false if any fails, null otherwise.
  - E30 (2026-11-14, before any real run): negative controls have an optional `bodies` list (all bodies when absent). Two sand-sea controls are Moon only: `rub_al_khali` (21.0 N, 51.0 E) and `namib_sand_sea` (24.8853 S, 15.4078 E). Flat dune fields pass the NDVI and cropland gates, so they are scorable, and their terrain is unlike a 9 to 17 deg polar slope, so a working score ranks them low. Mars keeps amazon_basin and congo_basin only (Jezero is nearly flat). The criteria block carries `control_rule`; Moon criteria sha256 `6bdaaf3a...`.
  - Informational, outside the pre-registered test: every gated-out site gets `ungated_terrain_only`, the base-profile score of its best tile within the radius computed WITHOUT the vegetation (NDVI) and built or cropland gates (the open water or ice gate and the missing-data rule still apply), scored with the target's own sigma from the gated tiles, and its rank percentile among that target's gated scores. `no_terrain_yet` when no such tile has all used columns.
- Site score: for each scored target, the base-profile rank percentile (among that target's gated tiles) of the best tile within 20 km of the site; the site value is the mean over the body's scored targets. ASSUMPTION: Anay to confirm. For Moon this averages Connecting Ridge C1 and Shackleton rim.
- Gate tests use the tile nearest the point. A point with no land tile within 6 km counts as rejected with that reason.
- Some site coordinates are still unconfirmed (see `docs/UNVERIFIED.md`). While any is, results are stamped `provisional: true` and the run prints the list of unconfirmed sites.

## 11. Deviations and assumptions

- Grid extends to the poles (section 2).
- Barker 2021 uncertainty midpoints (section 4): the source was opened and the range is quoted exactly; the midpoint is a choice, and the 5 m-pixel figures are applied at a 500 m baseline without a source for that.
- Roughness baselines 300 m (target-side E22) and 1000 m, TODO confirm with Vihaan.
- Earth terrain from SRTM90 covers 56 S to 60 N only (section 3d): tiles outside get no terrain and are rejected as `missing_data`.
- Per-tile noise not applied (section 8).
- Site score for validation averages over targets (section 10).
- Ledger relevance matrix is a draft (`ledger.yaml`, `provisional: true`).
- Cross-machine tolerances (`run.yaml: compare`) are a first guess.
- Earth `water_index` is aridity-only because no permafrost-probability dataset was verified (section 12, `UNVERIFIED.md`).
- Two Earth Engine modules exist. `earth/gee_export.py` is the route that ran (gate layers and terrain90/GLO30 chunk tasks, section 12); `earth/gee_export_layers.py` with `gee_operators.py` and `check_operators.py` is the config-driven route from PR 13/14, kept for `gsop check-operators` and not used for the v1 export. Three Earth columns (`water_index`, `silica_index`, `dust_index`) are not built in v1 (E21).
- Earth `sun_max_elev`, `sun_low_share`, `insol_annual` use latitude and obliquity only, not slope and aspect (`earth/solar.py`).
- Only the slope GRADIENT on the EPSG:6933 grid is corrected for the projection's ground scale (open-data fallback and Earth Engine operator, `operators.slope_deg(kx=...)`). The 500 m slope cell, the 300 m and 1000 m roughness windows and the 6 km tile stay projected metres, so away from 30 deg latitude they are not square on the ground (anisotropy note, section 3c). The default call is unchanged, so Moon, Mars and the golden slice are unaffected. The terrain90 and GLO30 Earth Engine exports run WITHOUT kx (`ground_scale=False`, E25).
- Moon and Mars target profiles are only partly built; the columns that are not are dropped per body (see `docs/UNVERIFIED.md`, DECISIONS target-side E19 to E21). Moon `water_index` is built but dropped (E19).
- Mars slope and relief: the 463 m MOLA window is resampled bilinearly to 500 m cells, because the operator needs the slope baseline to be a whole number of cells. Mars roughness is not built.
- The Earth Engine gate export and the terrain90/GLO30 terrain exports ran in Earth Engine (see `docs/EE_COST.md`); the Earth table is assembled from the Drive downloads (section 3e).

## 12. Earth Engine route

- Working grids: 33.333 m (DEM), 500 m (slope baseline) and 6000 m (tile), all aligned to the EPSG:6933 grid origin. A 6 km tile is 12 x 12 cells of 500 m.
- The terrain operator runs server-side and follows `src/gsop/operators.py` step by step:
  - block mean of the DEM to 500 m;
  - Horn 3x3 slope from explicit kernels, not `ee.Terrain.slope`;
  - slope percentiles 50 and 90 per tile;
  - relief is max minus min of the 500 m elevation cells in the tile;
  - roughness by window-centred moments (plane removed per window), with the median over windows per tile;
  - a tile value is NaN when fewer than 90 percent of its cells are valid.
- Dataset ids, date ranges and derived bands are recorded in `PROVENANCE.md`. Items not confirmed are in `UNVERIFIED.md`.
- The open-data fallback gives coarser terrain, and a 500 m slope baseline cannot be computed from a grid of about 1.8 km.

### Lonar operator check (2026-11-13)

- Window: 10 x 10 tiles (100 tiles, 60 km box) centred near lon 76.51, lat 19.98 (grid cells ix 4119-4128, iy 802-811), with a 1 km DEM margin. Script: `scripts/check_operators_lonar.py`; raw output `results/operator_check.json` (not committed).
- Earth Engine side: `gee_export.terrain_bands` tile features. numpy side: `gsop.operators.tile_features` on the Earth Engine 33.333 m mean DEM (`z33`) downloaded for the same region.
- Relative difference is |EE - numpy| / |numpy| per tile; a feature passes when the median is under 10 percent (issue 2 threshold).

| Feature | Tiles compared | Median rel. diff | 95th pct rel. diff | Max abs. diff | Result |
|---|---|---|---|---|---|
| slope_med | 100 | 0.09% | 0.56% | 0.01185 deg | pass |
| slope_p90 | 100 | 0.34% | 1.48% | 0.05418 deg | pass |
| relief | 100 | 0.00% | 0.00% | 5.6e-05 m | pass |
| rough_a | 99 | 0.54% | 1.67% | 0.008014 m | pass |
| rough_b | 100 | 0.00% | 0.00% | 2.3e-07 m | pass |

- rough_a has 99 tiles because one tile has numpy roughness exactly 0 (EE gives 2.6e-05 m), so a relative difference is undefined there.
- Both sides use the same Earth Engine 33.333 m mean DEM (`z33`), so this tests the operators only, not the DEM aggregation or reprojection. That is why relief and rough_b agree to float32 noise.
- The window box contains lon 76.51, lat 19.98 (its centre is about 6 km away).
- One window only. This does not replace running `gsop check-operators` over several terrain types (flat, mountain, polar).
