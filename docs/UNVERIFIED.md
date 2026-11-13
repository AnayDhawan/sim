# Unverified items and open decisions

Last updated 2026-11-13. "Verified" means an opened page or paper agrees; see `PROVENANCE.md` and `UNCERTAINTY_SOURCES.md` for the evidence. Items that need a person are marked **DECISION** or **SIGN-OFF**.

## Known sites (issue #10)

| Item | Status |
|---|---|
| lonar, haughton, gosses_bluff, ladakh_puga, samoylov, manicouagan_centre | confirmed against an opened source (`known_sites.yaml` carries the source on each line) |
| mcmurdo_dry_valleys, atacama_salars | areas, not points; Wikipedia only. `confirmed: false` |
| mdrs_utah, sf_volcanic_field, mauna_kea, askja, tatacoa | Wikipedia or a search snippet only. `confirmed: false`. A person should check a primary page |
| **manicouagan (gate test)** | **DECISION.** The old point (51.1, -68.7) is the annular reservoir, 31.5 km south of the structure centre (51.383, -68.700). The centre is now listed as `manicouagan_centre`. At the reservoir the 6 km tile is 64.9% water, but 2 of 9 positions shifted by 2 km fall under 50%. At the centre it is 5.9% water and 90.9% trees, so only the NDVI gate could reject it (not verified). Decide which one the gate test means |
| **tatacoa (gate test)** | its tile is 0% water and 0.1% built, so the water and built gates do not reject; only NDVI can, and a Sentinel-2 proxy (median 0.197) sits on the 0.2 threshold. "expect: rejected" is not guaranteed. These land-cover figures are the research agent's own computation on ESA WorldCover 2021, not a quoted source |
| **samoylov (gate test)** | 54% water and 40% herbaceous wetland; open water ranges 40-59% within 2 km. Rejection is marginal unless wetland counts as water |
| **amazon_basin (negative control)** | **DECISION before the first real run.** 13.5 km from central Manaus; the 6 km tile may be 35-40% built-up, above the 20% built gate (if gated out, the control is not ranked at all). A cleaner point such as (-2.9, -60.0) was suggested. Not changed, so nobody moves a control after seeing results |
| congo_basin (negative control) | `confirmed: false`. No coordinate source recorded: the comment in `known_sites.yaml` is a land-cover figure (WorldCover 99.8 percent trees), not a check of the point. A person should confirm or accept it |
| lonar tile | the 6 km tile at Lonar is about 69% cropland plus built-up (WorldCover), so it would fail the built/crop gate if gates applied to primary sites. Check how validation handles gated primary sites before reading its result |

`known_sites.yaml` still has `confirmed: false` entries, so every validation run still prints the warning and stamps `provisional: true`. Nothing from validation may be published before a person clears them or accepts the list above.

## Uncertainties (issue #9)

- Barker 2021 slope 1.5-2.5 deg and height 0.30-0.50 m are quoted exactly (opened). They are one range for four south-pole sites at 5 m/pixel. The file uses the **midpoints, which are a choice**, and applies them at a 500 m baseline, which no source supports. **DECISION**: keep, use the upper ends, or drop.
- No other column has a value. Sourced candidates and why each was not applied are in `UNCERTAINTY_SOURCES.md`. Not sourced at all: rough_a, rough_b, sun_*, water_index, dust_index, Earth ti_proxy, Diviner (Moon) temperatures, Mars climate temperatures.
- The sigma rule also needs a decision on statistic: most sources give LE90 or percent accuracy, not a sigma.

## Earth Engine and open-data route (issues #1, #2, #8)

- **`gee_export.py`, `gee_operators.py` and `check_operators.py` were written without a login and corrected after Anay's real Lonar run (PR 13 review); they have not been re-run since.** Their offline maths is tested. Run `gsop s2 earth --source gee --verify`, then `gsop check-operators`, then a Lonar test box, in that order.
- Every collection id is read from the live catalog page, not queried through a session (`PROVENANCE.md`). `GLO30_2024_1` is used (the unversioned collection is deprecated, confirmed by Anay).
- **DECISION: three features are not built** (`config/earth_layers.yaml` `not_built`): `water_index` (no global permafrost raster in the catalog), `silica_index` (ASTER GED exists but the band-ratio formula is not specified), `dust_index` (formula not specified). Until decided, any run that needs them stops loudly (SPEC section 7) unless they are put in `run.yaml drop_columns`.
- Judgement calls in the Earth Engine export a person should confirm: built_crop_frac counts MODIS IGBP classes 12 and 13 only (not 14, mosaic); water_ice_frac counts 15 and 17 (ocean included); land_frac is the share of the tile not in class 17; ndvi_median is the per-pixel temporal median of QA-good 2015-2024 MOD13A2 values, then the tile median; ti_proxy falls back to the annual mean swing where TerraClimate precipitation is missing, and the export carries a `ti_is_fallback` 0/1 band (1 where over half of the tile's pixels fell back).
- `sun_max_elev`, `sun_low_share`, `insol_annual` for Earth are computed from latitude and obliquity only (flat horizon, circular orbit; `earth/solar.py`). SPEC section 3 says slope and aspect are also used; they are not. **DECISION** whether that is acceptable.
- **EPSG:6933 tiles are not 6 km squares on the ground away from 30 deg latitude** (decision D1, not reopened here): east-west ground size is 6 km x cos(lat)/cos(30), and north-south is its inverse, so a tile at 60 deg is about 3.5 km by 10.4 km and at 85 deg about 0.6 km by 60 km. Only the slope GRADIENT is corrected for this (`operators.slope_deg(kx=...)`, tested at 20 and 60 deg; the Earth Engine side applies the same correction but was not re-run). The tile shape is a design question for Anay.
- **Anisotropic baselines and windows (same cause, listed separately because it is a different question).** `kx` fixes the gradient only. The 500 m slope cell, the 100 m and 1000 m roughness windows and the 6 km tile are still projected metres: on the ground the slope cell is 289 x 866 m at 60 deg and 100 x 2,494 m at 80 deg, the 100 m roughness window is 58 x 173 m at 60 deg, and the tile is 3.5 x 10.4 km at 60 deg. Moon and Mars use square ground cells, so an Earth tile away from 30 deg latitude is compared with a Moon or Mars window of a different shape. **DECISION** (Anay): accept this, restrict Earth tiles to a latitude band, or compute slope and roughness on square ground windows. Table in SPEC section 3c.
- The terrain operator needs whole-number cell ratios: it cannot use NASADEM at its native 30 m for `rough_a` (100/30 is not whole), and cannot use the 463 m MOLA DEM at all (500/463). The Earth Engine check therefore works on a 25 m resampled grid, and the Mars terrain profile from MOLA will raise until the baselines are decided. The roughness baselines (100 m and 1000 m) are still `TODO confirm with Vihaan`.
- Open-data fallback: Earthdata Login need for MOD11A2 and ASTER GED is inferred from a general statement; no download was attempted. A ~1.8 km grid cannot give the 500 m slope, so terrain is left out for it. Not tested on real downloads, only on synthetic rasters.

## Moon and Mars targets (issues #3, #4)

- Moon `water_index` can be built from a PSR raster with `gsop s2 targets --body moon --psr <file>`. The pixel encoding and declared nodata of the PGDA `LPSR_80S_20MPP_ADJ` raster were NOT checked; the code reads a declared nodata of 0 as 0 (so a mask that declares nodata = 0 still works) and any other declared nodata as missing (so a no-data area is not counted as unshadowed), treats any non-zero finite cell as shadowed, and grades the row B. **Open the file and record the encoding in `PROVENANCE.md` before raising it to A.**
- Moon `t_mean`, `t_coldest`, `ti_proxy`: Diviner polar products exist (PCP 80-90 deg, PRP to 80 deg; "Diviner does not reach the pole" in issue #3 is not quite right) but their data files were not opened and nothing is wired.
- **Moon `silica_index` cannot be built at the poles**: the Diviner Christiansen-feature grid stops at 60 deg. **DECISION**: drop it (`run.yaml drop_columns`) or find another source.
- Mars: elevation (`aux_elevation_m`) and `air_density` are built from the MOLA window when a DEM is given. `aux_thermal_inertia_si`, `silica_index`, `water_index` (SWIM 2.0 downloads are web forms; a depth composite must be chosen), `ti_proxy`, `dust_index` (no numeric TES dust cover product found), `insol_annual`, `sun_max_elev`, `t_mean`, `t_coldest` are not built.
- **Arcadia Planitia has no published centre** in anything opened (SWIM pages, Morgan 2021 abstract, Putzig and Morgan chapter). Only region boxes exist (`PROVENANCE.md`). It stays `unscored: no target data` (D10). **DECISION** if the team wants a point from a box.
- Mars `air_density` constants (now `config/targets.yaml mars_atmosphere`, logged as DECISIONS E7): the plan's "610 Pa, 11.1 km" is in no source found. The code uses NASA Glenn (699 Pa, 11.1 km scale); NASA's fact sheet gives 636 Pa and 11.0 km. **DECISION** which source. Earth air density uses the Glenn standard-atmosphere troposphere formula (ICAO 7488 not opened).

## Ledger (issue #11)

- Cold-traps Earth cell now quotes verified numbers: air record 184.0 K (WMO), satellite snow-surface minimum about 174.6 K (Scambos 2018, MODIS LST). The "about 93 K" figure in circulation is the earlier 2013 reading (about -93 C, roughly 180 K), not a surface minimum.
- The target side "below 110 K, down to 38 K" was not re-checked. A search snippet of Paige et al. 2010 mentions "as low as 29 K" mid-day bolometric temperatures; unverified lead, conflicts with 38 K. Hayne and Paige need a person to read.
- **SIGN-OFF**: the relevance matrix is unchanged and `relevance_provisional` stays `true` until Anay and Vihaan review it. Electrostatic dust and regolith mechanics rows still come from Shiven's report and are unverified.

## Other

| Item | Where used | Status |
|---|---|---|
| `rough_a` 100 m and `rough_b` 1000 m baselines | `config/features.yaml`, operators | TODO confirm with Vihaan |
| Cross-machine tolerances (score 1e-4, MC 1e-3, Jaccard 0.99) | `config/run.yaml` | First guess. Windows and macOS golden outputs agreed to under 8e-6 in the one macOS run done (against the Windows-recorded file); the CI run on both runners is not done yet |
| Validation site-score rule (mean over targets) | `docs/SPEC.md` section 10 | Assumption |
| Lunar thermal-inertia weight 0.019 lies outside its own Monte Carlo range [0.02, 0.04] | `config/weights.yaml` | Noted in SPEC section 5. **DECISION** whether to widen the range |
| Monte Carlo run time at 4M tiles | `docs/SPEC.md` section 8b | Measured once on synthetic data (332 s per target x profile on an 8-core Apple machine); not measured on real data or on the Windows machine |
