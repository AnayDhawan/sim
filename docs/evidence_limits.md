# Evidence limits (Role C)

Measurements of 120 analog-site rows (114 unique coordinates) from open Earth Engine datasets. Method fixed in `runs/v2/PREREG_C.md`. Numbers: `data/evidence/site_measurements.csv`. Ledger: `data/evidence/ledger_c.json`. These are measurements of Earth sites. They are not similarity scores and they say nothing about the Moon or Mars by themselves.

## Gate result

- G-C1 (smoke test, 3 sites, all six groups return a value or an explained null): met. The first Haughton chip attempt failed on an Earth Engine memory limit (1,023 scenes); it was fixed by fetching the same image in tiles. See "Implementation fixes".
- G-C2 (at least 110 of 120 rows with at least 20 of 24 primary variables at 10 km): **not met**. 94 rows pass. 92 rows have all 24, 28 rows have some missing, 0 rows have none.
- The gap is product coverage, not run failures. Rows where a whole group is null: emissivity 22, radar 13, temperature 4, cover 1, chip 1. These are polar, high-latitude and a few island or arid sites (details per dataset below).
- No task failed after retries and the redo pass. Nulls carry a reason in the `note` column.

## Rules for pages

- `page_ok = 0` marks 2 km values of rows whose coordinates are approximate. Pages use `page_ok = 1` only.
- Where two DEMs disagree by more than the stated uncertainty, show both or show the uncertainty.
- A null is shown as "no data" with its reason. It is never filled from another product.

## Per dataset

### Copernicus DEM GLO-30 (`COPERNICUS/DEM/GLO30_2024_1`) and ALOS AW3D30 (`JAXA/ALOS/AW3D30/V4_1`)
- Shows: elevation, relief (p95 minus p5), mean and p90 slope, and slope spread (the roughness number) of the ground around the site, from a 30 m surface model, at 2 km and 10 km radius.
- Breaks down:
  - Both are surface models, so trees, buildings and ice surfaces are in the height. Slope is computed on a 30 m grid, so it cannot show the metre-scale slopes that matter for a rover or a lander.
  - Lunar slope maps come from laser altimetry at a different baseline. A 30 m Earth slope is not the same quantity.
  - The two DEMs use different vertical references and different acquisition years. No correction is applied.
  - Stated uncertainty: the per-site mean absolute difference between the two DEMs has a median of 2.18 m, a 90th percentile of 4.04 m and a maximum of 9.8 m across the 119 rows with both models.
  - ALOS has no tiles at Mount Howe (-87.4 deg), so that row has Copernicus values only.
- Versions: the brief listed `COPERNICUS/DEM/GLO30` and `JAXA/ALOS/AW3D30/V3_2`. The catalog marks both as deprecated and names the two datasets above as successors, so the successors were used.

### MODIS land surface temperature (`MODIS/061/MOD11A2`, 2015-2024)
- Shows: clear-sky land surface temperature at 1 km: mean day and night, the warmest 8-day day value and the coldest 8-day night value, and the day minus night difference.
- Breaks down:
  - Clear-sky only, so cloudy and polar-night periods are missing and means lean warm in the day. The day minus night difference is a proxy, not a true diurnal range.
  - The 1 km pixel averages many surface types. It cannot represent a shadowed crater floor or a metre-scale thermal contrast.
  - Only composites flagged "good quality" are used. In arid Australia and the US south-west very few composites carry that flag: 4 rows have a mean under 30 valid day composites per pixel (Kilbourne Hole 1, Navajo Sandstone 9, Pilbara 10, Painted Desert 10), and 4 rows (Wolfe Creek, Henbury, Gosses Bluff, Arkaroola) have none and are null. Read the `valid_composites_*` rows before using any temperature.
  - Earth has an atmosphere and ocean heat storage. The lunar surface swings far more between day and night. These numbers do not transfer.
  - This is the MOD11A2 product. It is not Role A's MOD11C3 and the two are never mixed.

### ASTER Global Emissivity Dataset (`NASA/ASTER_GED/AG100_003`)
- Shows: mean thermal-infrared emissivity in ASTER bands 10 to 14 at 100 m, and `qi_silica_proxy`, a ratio of those means (eps11 squared over eps10 times eps12) that moves with quartz-rich surfaces.
- Breaks down:
  - The product is a 2000-2008 average, not a recent measurement.
  - The ratio is a proxy for silica-rich surface, not a composition. Moist soil, vegetation and mixed pixels change it. The index form is the commonly cited quartz index and its attribution was not re-checked.
  - 22 rows have no values: polar sites, Hawaii and Iceland. The product has no valid pixels there (masked or not covered; the run does not tell which).
  - Lunar thermal emissivity is measured with different bands (for example Diviner). The two band sets are not interchangeable.

### Sentinel-2 NDVI (`COPERNICUS/S2_SR_HARMONIZED`, 2024-2025)
- Shows: how much green vegetation signal the site area has, from the median of all cloud-masked scenes. A value near zero means bare ground, rock, sand or snow.
- Breaks down:
  - The Moon and Mars have no vegetation. A high value marks a site where biology changes the surface, which is a reason the analogy is weaker there, not stronger.
  - Snow and ice stay in the median (they are not masked as cloud), so polar values describe snow, not ground.
  - 12 of 120 rows at 10 km were computed at 20 m instead of 10 m after Earth Engine timed out twice. The `scale_m` column records this. All 2 km values are at 10 m.
  - Mount Howe has no Sentinel-2 scenes (polar), so that row is null.

### ESA WorldCover (`ESA/WorldCover/v200`, reference year 2021)
- Shows: the share of the circle in each land-cover class. `bare_fraction` is the "bare / sparse vegetation" class.
- Breaks down:
  - The bare class includes sparse vegetation, so a high value does not mean no life.
  - One year (2021), classified from imagery, with its own errors.
  - No coverage over Antarctica: those sites are null.

### Sentinel-1 backscatter (`COPERNICUS/S1_GRD`, IW mode, VV and VH, 2024-2025)
- Shows: C-band radar return in dB (median over time, then mean over the circle). Higher VV and VH mean a rougher or wetter surface at the centimetre to decimetre scale.
- Breaks down:
  - A roughness and moisture proxy only. It is not comparable to lunar radar, which uses other wavelengths, other incidence angles and a dry, airless surface.
  - Orbit passes are pooled. Mean of dB values is a geometric mean in linear terms.
  - 13 rows are null: the IW filter finds no scenes at those high-latitude and Antarctic sites (Sentinel-1 uses other modes over much of the polar regions; this was not checked per site).

### Sentinel-2 true-colour chip (`public/img/sites/<slug>.jpg`)
- Shows: a 20 km by 20 km view of the site area, 512 px, median of cloud-masked scenes 2024-2025, same stretch for every site. It shows land form and surface colour at a glance.
- Breaks down:
  - A 2-year median mixes seasons. Where snow covers the ground for part of the year the median saturates: 20 of 119 site rows have at least half of the chip pixels at near-white, and 12 have at least 90 percent (polar and high-latitude sites). `chip_saturated_fraction` records this. It is a post-hoc addition, not in PREREG_C. Do not show a chip with a high value as a picture of the ground.
  - Mount Howe has no clear imagery. Its entry says so and no other image is used.
  - 5 site names share coordinates with another row. Their chips are byte-identical copies, marked `alias_of` in `credits.json`.
  - Credit: "Contains modified Copernicus Sentinel data (2024-2025)". Chips total 6.06 MB, each under 300 KB.

## Post-hoc additions and implementation fixes

- Added after results were seen, labelled in the data: `chip_saturated_fraction` rows. No PREREG definition changed.
- Chip fetch: single-request render hit Earth Engine "User memory limit exceeded" on a 1,023-scene site. The chip is now fetched as 2x2, 4x4 or 8x8 tiles and stitched. Same pixels, less memory per request.
- Rate limits: thumbnail requests returned HTTP 429 under 6 parallel workers. The code now retries the same request, caps chips at 2 at once, and a redo pass re-ran the 29 failed tasks.
- ALOS gap: Mount Howe terrain crashed on the empty ALOS mosaic. The code now writes null ALOS and cross-check rows and keeps the Copernicus values.
- Null notes: "outside coverage" was reworded to "no valid pixels (product masked or no coverage at site)" because the run cannot tell the two apart.
- Words in PREREG line 111 list the terms not used in outputs, so a text search for them hits that line.

## Not done

- No similarity score, rank or weight is produced here.
- Stretch items (RADARSAT-1 scene, Open Science Catalog search) were gated on G-C2 and were not run.
