# PREREG_C: site-level open-data evidence (Role C)

Written 2026-11-15 (IST) before any site measurement was run. Branch `data/site-evidence`.
Nothing in this file changes after results are seen. Implementation bug fixes that leave every definition below untouched are allowed and are logged in `docs/evidence_limits.md`.

## 0. Scope

- This role produces measurements. It produces no similarity score, rank or weight.
- Input: `GSOP_analog_sites_moon_mars.csv`, copied read-only into `data/raw/` (git-ignored). sha256 of the input: `86439f8537079b7f2e9f9b0325ba9b7ac4bb2ecb4a4522dc92a53694ca21b3e7`.
- Columns read: Body, Category, Site_name, Latitude, Longitude, Coordinate_note. The loader names these six columns explicitly. No other column is used.
- 120 rows, 114 unique (Latitude, Longitude) pairs. A pair that occurs on several rows is measured once and the rows are copied to every matching (Body, Site_name). One Site_name occurs twice (HI-SEAS habitat, Moon and Mars, same coordinates): one chip, two sets of rows.
- Earth Engine project id: `gsop-earthengine` (read from the existing verify scripts in the repo). No credentials are written anywhere.

## 1. Geometry and approx-coordinate handling

- Region = circle of radius 2000 m and 10000 m around (Latitude, Longitude), built with `ee.Geometry.Point(lon, lat).buffer(r)`.
- `coord_flag = approx` when Coordinate_note contains the string "approx" (case-insensitive). Otherwise `coord_flag = ok`. Expected count: 60 rows.
- Both radii are computed for every row. Column `page_ok = 1` unless (`coord_flag = approx` and `radius_km = 2`). Pages may use only rows with `page_ok = 1`.
- Reductions on a 10 m, 20 m or 30 m grid use a local Lambert azimuthal equal-area CRS (WKT, centre = site, metres, WGS84 ellipsoid). Reason: a metre scale with the default EPSG:4326 grid oversamples longitude by 1/cos(lat). Probe on a non-site point showed a 1.45x pixel overcount at 46.5 N without the local CRS and a match to pi r^2 / pixel area with it.
- MODIS and ASTER GED are reduced on their own native grid (no resampling): MODIS sinusoidal 1000 m, ASTER GED native geographic grid at its nominal scale.
- Reducers are Earth Engine's coverage-weighted reducers. `n_pixels` = the weighted count from `Reducer.count()` on the same band and region.

## 2. Datasets and catalog check

Source of record: Earth Engine catalog entries (STAC JSON that backs each catalog page, `storage.googleapis.com/earthengine-stac/catalog/...`, fetched 2026-11-15). Catalog page URL pattern: `https://developers.google.com/earth-engine/datasets/catalog/<ID with / replaced by _>`.

| Use | Dataset ID used | Catalog version | Catalog status | DOI in catalog | Differs from brief list |
|---|---|---|---|---|---|
| Terrain | `COPERNICUS/DEM/GLO30_2024_1` | 2024_1 | ready | none, catalog URL recorded | Yes. `COPERNICUS/DEM/GLO30` (version 2021) is marked deprecated in the catalog with `GLO30_2024_1` as successor. |
| Terrain cross-check | `JAXA/ALOS/AW3D30/V4_1` | 4.1 | ready | none, catalog URL recorded | Yes. `V3_2` is marked deprecated with `V4_1` as successor. |
| Temperature | `MODIS/061/MOD11A2` | 6.1 | ready | 10.5067/MODIS/MOD11A2.061 | No |
| Emissivity | `NASA/ASTER_GED/AG100_003` | V003 | ready | 10.5067/COMMUNITY/ASTER_GED/AG100.003 | No |
| Optical | `COPERNICUS/S2_SR_HARMONIZED` | harmonized | ready | none, catalog URL recorded | No |
| Radar | `COPERNICUS/S1_GRD` | none stated | ready | none, catalog URL recorded | No |
| Land cover | `ESA/WorldCover/v200` | v200 (reference year 2021) | ready | none, catalog URL recorded | No |

If an ID fails to load at run time, the run stops for that dataset and the failure is written to the output, not substituted.

## 3. Variable definitions

All statistics are over the region pixels. Units in brackets.

### 3.1 Terrain (dataset `cop_dem`, product `COPERNICUS/DEM/GLO30_2024_1`, band `DEM`)
- Mosaic the collection, set default projection from the first tile, `resample('bilinear')`, reproject to local LAEA at 30 m.
- Slope = `ee.Terrain.slope` of that grid [degrees].
- Reported: elevation mean, min, max, p5, p95 [m, EGM2008 datum]; `relief` = p95 minus p5 of elevation [m]; slope mean, p90, std [deg]. `roughness` = slope std.
- Reduction: scale 30 m, local LAEA, `tileScale` 4.
- Dataset `alos_dem` (`JAXA/ALOS/AW3D30/V4_1`, band `DSM`): identical procedure, same statistics.
- Dataset `dem_crosscheck` (stated uncertainty, not a correction): per-pixel `ALOS DSM minus COP DEM` on the shared 30 m grid. Reported: mean difference, mean absolute difference, RMS difference [m]. Derived rows from the two datasets: elevation-mean difference, relief difference, slope-mean difference (ALOS minus COP). No datum correction is applied. Both are surface models.

### 3.2 Temperature (dataset `mod11a2`, product `MODIS/061/MOD11A2`)
- Window: 2015-01-01 to 2024-12-31 inclusive (`filterDate('2015-01-01','2025-01-01')`). Not mixed with Role A's MOD11C3.
- Quality: keep a pixel-composite only where `QC_Day` (for day) or `QC_Night` (for night) bits 0-1 equal 0 ("LST produced, good quality"). LST = DN x 0.02 [K].
- Per-pixel over all valid composites in the window: `lst_day_mean` = mean of day LST; `lst_night_mean` = mean of night LST; `lst_day_max8d` = max of day LST; `lst_night_min8d` = min of night LST; `valid_composites_day` and `valid_composites_night` = count.
- Spatial reduction: coverage-weighted mean over the region of each per-pixel image [K; count for the two count variables], native sinusoidal grid, scale 1000 m.
- `lst_day_night_diff` = `lst_day_mean` minus `lst_night_mean` (difference of the two spatial means) [K]. A proxy, not a true diurnal range, because the clear-sky composites differ between day and night.
- Clear-sky sampling bias applies to every number here. It is stated in `docs/evidence_limits.md`.

### 3.3 Emissivity (dataset `aster_ged`, product `NASA/ASTER_GED/AG100_003`)
- Bands `emissivity_band10` to `emissivity_band14`, scale factor 0.001. Spatial mean over the region, native grid.
- Silica proxy `qi_silica_proxy` = (eps11 x eps11) / (eps10 x eps12), computed from the five spatial means. Dimensionless, a thermal-infrared quartz-index style ratio, a proxy only. The index form follows the commonly cited Ninomiya-type quartz index; the attribution was not re-checked in this run.
- The product is a 2000-2008 mean. It is not a 2015-2024 measurement.

### 3.4 Cover
- Dataset `s2` (`COPERNICUS/S2_SR_HARMONIZED`): window 2024-01-01 to 2025-12-31 inclusive (`filterDate('2024-01-01','2026-01-01')`). Cloud mask from band `SCL`: remove classes 0, 1, 3, 8, 9, 10. Classes 2, 4, 5, 6, 7, 11 are kept, so snow and ice (11) stay in. NDVI = (B8 - B4) / (B8 + B4) per image, then per-pixel temporal median. Reported: `ndvi` spatial mean and std of that median image [unitless]. Reduction scale 10 m, local LAEA, `tileScale` 16.
- Dataset `worldcover` (`ESA/WorldCover/v200`, band `Map`, 2021): fraction of region pixels in each class 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100 [fraction 0-1]. `bare_fraction` = class 60 ("Bare / sparse vegetation" in the product legend, so it includes sparse vegetation). Reduction scale 10 m, local LAEA.

### 3.5 Radar (dataset `s1`, product `COPERNICUS/S1_GRD`)
- Window 2024-01-01 to 2025-12-31 inclusive. Filters: `instrumentMode = IW`; `transmitterReceiverPolarisation` contains both VV and VH. All orbit passes pooled. Bands VV, VH in dB as stored in the collection.
- Values at or below -50 dB are masked as non-physical. No other masking beyond the collection's own mask.
- Per-pixel temporal median per band, then spatial mean and std over the region [dB]. The mean of dB values is the geometric mean in linear power. A roughness and moisture proxy only. Not comparable to lunar radar.
- `scene_count` = number of images that passed the filters over the region [count]. Reduction scale 10 m, local LAEA, `tileScale` 16.

### 3.6 Imagery chip (dataset `s2_chip`, 10 km radius only)
- Square of 20 km x 20 km centred on the site (half-width 10 km, so the whole 10 km analysis circle is inside), in the local LAEA CRS, rendered at 512 x 512 px (about 39 m per pixel).
- Same S2 window and the same SCL mask as 3.4. Per-pixel median of B4, B3, B2. Fixed stretch for every site: min 0, max 3000 (surface reflectance DN), gamma 1.4.
- Clear-scene rule: the chip is made only if at least 50% of the box pixels (sampled at 100 m) have at least 3 valid observations. Otherwise status is `no clear imagery`, no chip file is written, and no other image is substituted.
- Saved as JPEG at `public/img/sites/<slug>.jpg`. Quality ladder 85, 75, 65, 55, 45, 35, stop at the first file of 300 KB or less. If 35 still exceeds 300 KB the chip is dropped with status `chip over budget`. Total budget 40 MB.
- `slug` = Site_name, NFKD-normalised, ASCII only, lower case, every run of non-alphanumeric characters replaced by one hyphen, leading and trailing hyphens stripped. (No slug function exists in the repo, so this rule is the one applied.)
- `public/img/sites/credits.json` holds the credit string `Contains modified Copernicus Sentinel data (2024-2025)`, plus per site: status, clear fraction, scene count, date window.
- Row in the CSV: `s2_chip / chip_clear_fraction` [fraction].

## 4. Output schema and null handling

- `data/evidence/site_measurements.csv`, long format. Required columns: site_name, body, list (= Category), radius_km, coord_flag, dataset, variable, stat, value, units, n_pixels, product_id, version, doi_or_url, date_range. Extra columns: lat, lon, scale_m, page_ok, note, pulled_utc.
- A null is written as an empty `value` with a `note`: `no_valid_pixels`, `no_images`, `outside_product_coverage`, or `FAILED: <reason>` after retries. Nulls are shown, never dropped (O7).
- Derived rows (relief, qi_silica_proxy, lst_day_night_diff, dem_crosscheck differences) carry `note = derived`.

## 5. Execution rules

- One background Python script under Git Bash `nohup`, not inside the Claude Code session.
- Unit of work: unique coordinate. Rows for a coordinate are appended to the CSV only when all of its tasks are finished or have failed after retries. A completed-coordinate list in `runs/v2/cache/` makes the run resumable.
- 4 parallel workers. Per task up to 5 attempts, backoff 20 s x 2^attempt.
- Scale ladder for the 10 m tasks (S2 NDVI, S1, WorldCover): attempts 1-2 at 10 m, attempt 3 at 20 m, attempt 4 at 30 m, attempt 5 at 60 m. The scale used is written to `scale_m`. A coarser scale is a recorded deviation, not a silent one.
- `runs/v2/STATUS_C.md` is rewritten every 10 minutes. It, logs and caches are git-ignored.
- A task stuck for more than 30 minutes is logged as failed and the run moves on.
- No new work starts after 17:00 IST on 2026-11-15.
- The script exits non-zero if any task failed, and prints the failed list.

## 6. Gates

- Smoke test sites (fixed now): Antarctic = "McMurdo Dry Valleys (Taylor/Wright valleys)"; desert = "Atacama Desert - Yungay core" (also exercises `approx`); high latitude = "Haughton crater (Devon Island)".
- G-C1: for each smoke site, all six measurement groups (terrain, temperature, emissivity, cover, radar, chip) return values or an explained null.
- Primary variables per row at 10 km (24 in total): cop_dem elevation mean, min, max, relief, slope mean, slope p90, slope std (7); dem_crosscheck mean elevation difference (1); mod11a2 lst_day_mean, lst_night_mean, lst_day_max8d, lst_night_min8d, lst_day_night_diff (5); aster_ged band10 to band14 means and qi_silica_proxy (6); s2 ndvi mean (1); worldcover bare_fraction (1); s1 VV and VH medians (2); chip available (1).
- A row passes when at least 20 of the 24 are non-null. G-C2 = at least 110 of the 120 rows pass.

## 7. Claims and wording

- `runs/v2/claims_c.csv` (claim, number, source file, sha256) gets one row for every non-null measurement row in `site_measurements.csv`, plus one row for every number quoted in `docs/evidence_limits.md` and `docs/data_resources.md`. Source file for site numbers is `data/evidence/site_measurements.csv` with its sha256.
- `data/evidence/ledger_c.json` has one entry per dataset: product, version, DOI or URL, date range, date pulled, sha256 of the output rows for that dataset. The sha256 is taken over that dataset's rows serialised as CSV in file order with LF line endings.
- Words not used in any output: validated, discovered, undiscovered, new sites.
- Every dataset gets two lines in `docs/evidence_limits.md`: what it shows about the site, and where the measurement or the analogy breaks down.
