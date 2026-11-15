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
- **Anisotropic baselines and windows (same cause, listed separately because it is a different question).** `kx` fixes the gradient only. The 500 m slope cell, the 300 m and 1000 m roughness windows and the 6 km tile are still projected metres: on the ground the slope cell is 289 x 866 m at 60 deg and 100 x 2,494 m at 80 deg, the 300 m roughness window is 173 x 520 m at 60 deg, and the tile is 3.5 x 10.4 km at 60 deg. Moon and Mars use square ground cells, so an Earth tile away from 30 deg latitude is compared with a Moon or Mars window of a different shape. **DECISION** (Anay): accept this, restrict Earth tiles to a latitude band, or compute slope and roughness on square ground windows. Table in SPEC section 3c.
- The terrain operator needs whole-number cell ratios: it cannot use NASADEM at its native 30 m for slope (500/30 is not whole), and cannot use the 463 m MOLA DEM at native cells (500/463). The Earth Engine check therefore works on a 25 m resampled grid, and the Mars window is resampled bilinearly to 500 m cells for slope and relief (2026-11-13; roughness is never taken on a resampled surface). The roughness baselines are 300 m (target-side E22, because Earth terrain comes from SRTM90 on a 100 m grid) and 1000 m, still `TODO confirm with Vihaan`. SRTM90 covers 56 S to 60 N only: haughton, mcmurdo_dry_valleys, samoylov and askja lie outside and get no terrain (SPEC section 3d). **DECISION** (Anay): accept that haughton and mcmurdo_dry_valleys drop out of validation and samoylov is rejected as missing data, or add a DEM for high latitudes.
- Open-data fallback: Earthdata Login need for MOD11A2 and ASTER GED is inferred from a general statement; no download was attempted. A ~1.8 km grid cannot give the 500 m slope, so terrain is left out for it. Not tested on real downloads, only on synthetic rasters.

## Moon and Mars targets (issues #3, #4)

- **Built 2026-11-13** (`data/processed/targets_moon.parquet`, `targets_mars.parquet`; sources in `PROVENANCE.md`). Moon, both targets: slope_med, slope_p90, relief, rough_a, rough_b from the LOLA 20 m DEM (grade A); water_index as PSR share from `LPSR_80S_20MPP_ADJ` (grade A, encoding checked on the file); sun_max_elev, sun_low_share from the pole rule (grade C). Jezero: slope_med, slope_p90, relief from MOLA resampled to 500 m (grade A), aux_elevation_m (A), air_density (Glenn model, C), insol_annual and sun_max_elev computed (C).
- The LOLA DEM and PSR map were taken as a [-32, 32] km clip of the remote cloud-optimised files (source pixels unchanged), because the server gave about 100 KB/s for the 2.7 GB file. A full PSR download stopped at 121.8 of 154.2 MB (curl exit 56) and was deleted; nothing depends on it.
- Moon `t_mean`, `t_coldest`, `ti_proxy`: Diviner polar products exist (PCP 80-90 deg, PRP to 80 deg) but their data files were not opened and nothing is wired. Dropped for the Moon (Anay, 2026-11-13, `run.yaml drop_columns.moon`).
- Moon `silica_index` cannot be built at the poles (the Diviner Christiansen-feature map stops at 70 deg, Zenodo record 4558235; earlier docs said 60 deg, which was wrong). Dropped (Anay, 2026-11-13).
- Moon `water_index` is dropped for v1 (Anay, 2026-11-13, DECISIONS E19): the Earth column is aridity only (high = dry) while the Moon target is a PSR share near 0 (0.026, 0.096), so the match would favour the wettest barren Earth tiles. The PSR share stays in the target file. With cold_dry gone, the Moon score uses slope, illumination, roughness and relief only, and Moon `ice_resources` is not run (`run.yaml skip_profiles`). A future Earth ice or cold-trap proxy would need a new decision.
- Mars `rough_a`, `rough_b` cannot come from MOLA: 300 m is 0.65 cells and 1000 m is 2.16 cells of 463 m, and the plane fit needs a whole number of at least 3 cells; a resampled surface has no real sub-cell relief. Dropped for Mars (Anay, 2026-11-13, E20). A HiRISE or CTX DEM of Jezero could give them; none was opened.
- Mars `silica_index`, `water_index` (SWIM 2.0 downloads are web forms; a depth composite must be chosen), `dust_index` (a floating-point TES Dust Cover Index exists, 16 ppd, 5760 x 2880, about 66 MB, per the ASU page; not comparable to the atmospheric Earth column, so not built), `ti_proxy`: not built, no published source comparable with the Earth column. Left unscored for Mars (E20, E31). An agent-assisted evidence table (sim/data/raw/gsop_mars_silica_swim_dci.csv, 2026-11-14, not re-verified, not copied here) agrees: silica NONE EXISTS, water_index and dust_index NOT FOUND.
- Mars sunlight (`insol_annual`, `sun_max_elev`) is computed with the Earth code (latitude and obliquity, circular orbit) and NASA fact sheet constants (E21, accepted).
- After the Mars drops only sunlight, slope, relief and elevation_density remain (0.376 of the derived weight before renormalisation), and `ice_resources` equals `base` for Mars because every family it boosts is dropped. Mars `geology_life` is not run (Anay, 2026-11-13). **SIGN-OFF**: Mars runs only after Anay confirms the Jezero target values (the 2026-11-14 values are in the section below).
- **Arcadia Planitia has no published centre** in anything opened (SWIM pages, Morgan 2021 abstract, Putzig and Morgan chapter). Only region boxes exist (`PROVENANCE.md`). It stays `unscored: no target data` (D10). **DECISION** if the team wants a point from a box.
- Mars `air_density` constants (now `config/targets.yaml mars_atmosphere`, logged as DECISIONS E7): the plan's "610 Pa, 11.1 km" is in no source found. The code uses NASA Glenn (699 Pa, 11.1 km scale); NASA's fact sheet gives 636 Pa and 11.0 km. **DECISION** which source. Earth air density uses the Glenn standard-atmosphere troposphere formula (ICAO 7488 not opened).

## Ledger (issue #11)

- Cold-traps Earth cell now quotes verified numbers: air record 184.0 K (WMO), satellite snow-surface minimum about 174.6 K (Scambos 2018, MODIS LST). The "about 93 K" figure in circulation is the earlier 2013 reading (about -93 C, roughly 180 K), not a surface minimum.
- RESOLVED 2026-11-14 (Moon checks PDF, see the section at the end): the ledger target side now says below 110 K and Diviner measured as low as 29 K (Paige et al. 2010); the earlier 38 K figure was a modelled subsurface value and was removed.
- **SIGN-OFF**: the relevance matrix is unchanged and `relevance_provisional` stays `true` until Anay and Vihaan review it. Electrostatic dust and regolith mechanics rows still come from Shiven's report and are unverified.

## Other

| Item | Where used | Status |
|---|---|---|
| Known-site coordinates (all of `known_sites.yaml`): Lonar, Haughton, McMurdo Dry Valleys, Atacama salars, Ladakh Puga, MDRS, SF volcanic field, Gosses Bluff, Mauna Kea, Askja, Manicouagan, Tatacoa, Samoylov, Amazon, Congo | `config/known_sites.yaml`, validation | From memory, `confirmed: false`. Shaurya must confirm before any result is published. Manicouagan and Tatacoa are "as given in our files". |
| Barker 2021 Moon slope uncertainty 2.0 deg and relief 0.4 m | `config/features.yaml`, sigma rule | Ranges (1.5 to 2.5 deg, 0.3 to 0.5 m) given in the setup prompt; the midpoints are the assistant's choice. |
| Earth Engine collection IDs for every Earth layer | `config/features.yaml` (leads), Phase 2 | Checked in the live catalog on 2026-11-13 and recorded in `PROVENANCE.md`. Version and licence fields were not returned by the API for the collections. |
| Satellite surface minimum for the cold-traps ledger row | `config/ledger.yaml` | The row quotes about 184 K air-temperature record; the setup prompt says the satellite minimum is lower and must be checked before quoting. |
| Ledger relevance matrix (which rows matter for which purpose) | `config/ledger.yaml`, fidelity | Draft, `provisional: true`. Anay and Vihaan review. |
| Electrostatic dust and regolith mechanics rows | `config/ledger.yaml` | From Shiven's report, unverified. |
| Validation site-score rule (mean over targets) | `docs/SPEC.md` section 10 | Confirmed by Anay 2026-11-13. |
| Arcadia Planitia centre | `config/targets.yaml` | Not in our files. Take from SWIM ice map (issue #4). |
| PSR share, Diviner and other Moon target sources | Phase 3 | Not wired. No URL or product ID has been checked. |
| No permafrost-probability dataset could be found or verified in the Earth Engine catalog, so Earth `water_index` is aridity-only | Earth `water_index`, Phase 2 | DEVIATES from the plan (mean of permafrost probability and aridity). Anay accepted aridity-only on 2026-11-13 (DECISIONS.md). |
| Silica index formula e11^2/(e10*e12) on ASTER GED emissivity bands scaled by 0.001 | Earth `silica_index`, Phase 2 | QI = D11 x D11 / (D10 x D12) is printed as Eq. 2 in Ninomiya and Fu 2016, Geosciences 6(3):39, https://doi.org/10.3390/geosciences6030039 ("expected to be high for crystallized quartz"). That paper uses normalised at-sensor radiance, not GED emissivity, so its QI > 1.05 threshold does not transfer. Earth silica_index is not exported in v1 (E31), so no run is affected. Details in the Mars section below (agent-assisted, source pages opened by Shiven's chat, not re-verified by us). |
| Dust measure: mean MERRA-2 DUEXTTAU (dust extinction optical depth at 550 nm) | Earth `dust_index`, Phase 2 | Dimensionless, not a 0-1 index. Choice of measure not confirmed. |
| `built_crop_frac` = MCD12Q1 classes 13 plus 12 | Earth `built_crop_frac`, Phase 2 | Class 14 (cropland and natural vegetation mosaic) is not counted. Choice not confirmed. |
| NASADEM (EGM96) and Copernicus (EGM2008) vertical datums differ | Earth DEM, Phase 2 | Not harmonised. |
| DEM seam at 60 N: SRTM90 up to 60 N, Copernicus GLO30 above (E22, E23, E27) | Earth terrain, `assemble.py` | Measured 2026-11-14 on two boxes at 58.1 to 59.9 N where both DEMs have data (`docs/SPEC.md` section 3g, `scripts/seam_test.py`). Slope, relief and elev_mean agree to 1 to 2 percent in the median (correlation at least 0.998). `rough_a` is higher in GLO30 by 19 and 37 percent in the median, `rough_b` by 6 and 14 percent. Two forested boxes, one latitude band; nothing measured above 60 N, on bare ground, or at other latitudes. A person decides whether to accept the roughness step or restrict the roughness match above 60 N. |
| `rough_a` 300 m (target-side E22) and `rough_b` 1000 m baselines | `config/features.yaml`, operators | TODO confirm with Vihaan |
| Cross-machine tolerances (score 1e-4, MC 1e-3, Jaccard 0.99) | `config/run.yaml` | First guess. Windows and macOS golden outputs agreed to under 8e-6 in the one macOS run done (against the Windows-recorded file); the CI run on both runners is not done yet |
| Lunar thermal-inertia weight 0.019 lies outside its own Monte Carlo range [0.02, 0.04] | `config/weights.yaml` | Noted in SPEC section 5. **DECISION** whether to widen the range |
| Monte Carlo run time at 4M tiles | `docs/SPEC.md` section 8b | Measured once on synthetic data (332 s per target x profile on an 8-core Apple machine); not measured on real data or on the Windows machine |
| Obliquity 23.44 deg and S0 1361 W/m2 (`config/features.yaml solar`), Earth standard atmosphere constants (`earth_atmosphere`) | Earth sun columns and `air_density` (`astro.py`, E26) | From the targets-moon-mars config; not re-checked on integrate. |
| `sun_*` and `insol_annual` ignore slope, aspect, eccentricity and atmosphere | `src/gsop/earth/solar.py`, Earth and Mars sun columns | Simplification, not validated. |
| Earth slope from the terrain90 and GLO30 exports is not kx corrected (E25) | Earth `slope_med`, `slope_p90` | Ground-scale error: east-west gradient over-read by 1/kx, north-south under-read by kx, kx = cos(lat)/cos(30 deg). Not corrected in the running export. |

## Moon target columns, Vihaan's evidence table (2026-11-14)

All rows agent-assisted, source pages opened by Vihaan's chat, not re-verified by us. Table copy: `docs/evidence/moon_evidence_vihaan_2026-11-14.csv`.

- `t_mean` and `t_coldest`: NOT FOUND at connecting_ridge_c1 or shackleton_rim. Candidate products: Diviner PRP (modelled annual average surface temperature) and PCP (bolometric brightness temperature, 240 m bins, 24 subsolar-longitude bins x 6 Ls bins), https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/ and https://www.diviner.ucla.edu/single-post/2020/07/20/new-diviner-seasonal-polar-data-products. `t_coldest` could only be a coldest-season value: 6 Ls bins of about 58 days. PCP is a brightness temperature, not a skin temperature. The 15 km window around shackleton_rim reaches into the interior PSR.
- `ti_proxy`: NOT COMPARABLE. There is no 24 h day-night swing at the pole (Sun within about 1.5 deg of the horizon); the Earth column is a dry-season day-night LST difference.
- `silica_index`: NONE EXISTS above 70 deg. The Diviner Christiansen Feature map (Lucey et al. 2021, Zenodo record 4558235) covers +/- 70 deg; our docs said 60 deg before 2026-11-14, now corrected.
- WARNING: Williams et al. 2019 (JGR Planets 124:2505) prints temperatures for "Connecting Ridge C2". Repo rule: never C2; do not use those numbers for connecting_ridge_c1.
- These four columns stay dropped for the Moon (E19, E16); nothing here changes a run.

## Mars target columns, Shiven's evidence table (2026-11-14)

All rows agent-assisted, source pages opened by Shiven's chat, not re-verified by us. Table copy: `docs/evidence/mars_evidence_shiven_2026-11-14.csv`.

- `silica_index`: NONE EXISTS comparable to the Earth quartz index. Only CRISM hydrated-silica detections (Tarnas 2019) and basaltic TIR bulk mineralogy (Salvatore 2018), no abundance value.
- `water_index`: NOT FOUND at Jezero (SWIM 2.0, 3000 m pixels, 0 to 60 N; no value read). NOT COMPARABLE to the Earth aridity index.
- `dust_index`: NOT FOUND at Jezero (MGS TES Dust Cover Index, 16 ppd, about 3.5 km). Surface dust cover against an atmospheric Earth column: NOT COMPARABLE.
- These stay dropped for Mars (E20, E31).

## Mars Jezero columns derived on 2026-11-14 (E31)

- `aux_thermal_inertia_si` = 204.08 J m-2 K-1 s-1/2, spread 13.69, from the Zenodo THEMIS Jezero mosaic (record 4931348, CC BY 4.0); 16 tiles, 22,500 of 22,500 window pixels valid. Grade A, DERIVED. The D6 thermal-inertia check now reads true (it was `unknown`). Only the Jezero mosaic was used, one file, not a global product.
- `ti_proxy` stays unavailable for Mars. **DECISION**: the instructions asked for THEMIS in `ti_proxy`, but the Earth `ti_proxy` is a dry-season day-night temperature swing in K (`config/features.yaml`) and THEMIS is thermal inertia in J m-2 K-1 s-1/2. Putting 204 next to a swing of a few tens of kelvin would score nothing real once the Earth column exists. A conversion, or an Earth thermal-inertia column, is needed first.
- `t_mean` = 224.098 K and `t_coldest` = 185.788 K from MCD v6.2 (climatology average solar, `tsurf`, 24 Ls x 24 local times, web interface). Grade C, DERIVED, spread 0 by construction. A model against Earth MODIS LST: comparability PARTIAL. The definition of `t_coldest` (lowest daily minimum, 185.788 K) differs from the repo's "coldest-month surface temperature" (coldest-season daily mean, 214.213 K): **DECISION** which one the Earth column should be compared with. The Earth file has neither column, so both stay in `run.yaml drop_columns.mars`; a run that lists them as used stops with `cannot score, unavailable columns ['t_coldest', 't_mean']` (SPEC section 7).
- Equal Ls steps are not equal time steps, so t_mean is weighted by month length (LMD table). Not verified: the month centre stands in for the whole month (one Ls per month), and the 1 h local-time grid.
- Candidate-stage re-scoring that would compute the three Earth bands for a few thousand tiles only: `docs/PROPOSAL_candidate_climate_rescoring.md` (proposal, not implemented, exploratory).

## Shiven's second Mars message (2026-11-14)

All items agent-assisted, source pages opened by Shiven's chat, not re-verified by us.

- Earth silica formula: QI = D11 x D11 / (D10 x D12), Eq. 2 of Ninomiya and Fu 2016, Geosciences 6(3):39, https://doi.org/10.3390/geosciences6030039 ("expected to be high for crystallized quartz"). Caveats:
  - the paper computes QI on normalised at-sensor radiance, not on GED emissivity, so its QI > 1.05 threshold does not transfer;
  - ASTER bands B10 8.125-8.475, B11 8.475-8.825, B12 8.925-9.275 um at 90 m (Corrie et al., arXiv 1107.3499, Table 1);
  - ASTER GED (NASA/ASTER_GED/AG100_003): scale 0.001, pixel 111.32 m, latitude -59 to 80, clear-sky data 2000 to 2008; pixels with value 0 divide by zero;
  - a low QI does not mean low silica (sulfates, feldspar);
  - "TES" in ASTER GED (Temperature Emissivity Separation) is unrelated to Mars TES.
  - Earth silica_index is NOT exported in v1 (E31), so no run is affected.
- Jezero thermal inertia (D6 check only, never scored):
  - Martinez et al. 2023 (JGR Planets, doi 10.1029/2022JE007537): 330 SI, a traverse mean (range 295 to 350, absolute accuracy about 20 percent), not a window median.
  - Our value from the THEMIS raster (Zenodo record 4931348): 204.08 SI, median over the repo's 15 km window (16 tiles).
  - Anay's raster check (2026-11-14, same file, window median of 22,500 pixels): whole raster median 243.6 (p5 150.3, p95 387.1); at the repo target 209.5; 0.2 deg south 219.8; 0.2 deg north 248.4; at the Perseverance landing point (18.4447, 77.4508) 210.1.
  - Conclusion: the two values are different spatial samples of the same quantity and do not conflict; both pass the D6 check (at least 100) and neither is scored.
  - Newman et al. 2021, Table 1 (PMC7868679): nine models use TES-derived thermal inertia of 260 to 321 SI and albedo 0.1342 to 0.1935 at the landing site. These are grid-smoothed model inputs, not Jezero measurements.
- OPEN: Mars coordinate convention unresolved. The THEMIS file is on a sphere (radius 3,396,190 m, planetocentric) and Grant 2018 may be planetographic; the two latitude conventions differ by about 0.2 deg (about 12 km) at 18.4 N, nearly the 15 km window. All Jezero target values are affected a little; the crater floor is flat, so scores are insensitive. Not re-run.
- `dust_index`: the ASU page says a floating-point numeric TES Dust Cover Index exists (16 ppd, 5760 x 2880, about 66 MB). A JMARS screenshot reading of 0.97126 at ONE pixel 9.9 km from the target is not a window median and is not used. NOT COMPARABLE to the Earth atmospheric dust column; unscored.
- `water_index`: SWIM4MIM, 3000 m pixels, no data -30, latitude -60 to 60; value at Jezero not read (about 25 pixels in a 15 km window); unscored.
- `t_mean`, `t_coldest`: Shiven could not run the MCD; ours are derived from MCD v6.2 (224.098 K and 185.788 K), partial comparability, unscored (no Earth columns).

## Moon checks (PDF, 2026-11-14)

Copy: `docs/evidence/moon_checks_diviner_roughness_ledger_2026-11-14.pdf`. All items agent-assisted, source pages opened by the author's chat, not re-verified by us.

- Diviner temperatures: 29 K is MEASURED (surface bolometric brightness temperature at mid-day in southern summer; Paige et al. 2010, Science 330:479, doi 10.1126/science.1187726, checked against a text copy, to confirm in the Science PDF). The old 38 K was a MODELLED SUBSURFACE value at the LCROSS region (USGS abstract) and is removed from the ledger. The coldest Diviner reading anywhere is 25 K in Hermite crater near the north pole in winter night, not usable for a south pole target. A south pole winter or annual minimum is not sourced.
- Roughness baselines, literature verdict:
  - Barker et al. 2023 (PSJ 4:183, LOLA 80 to 90 S) uses baselines of 100, 200, 400, 800 and 1600 m with a plane fit and 1.48 x MAD of the residuals. Our statistic is the RMS of plane residuals; the two are equal for normally distributed residuals, and MAD resists outliers.
  - 100 m and 1000 m lie inside the published range. No opened paper uses 300 m. Our 300 m for rough_a is forced by the 90 m Earth DEM (a 100 m window holds fewer than 3 cells of a 90 m DEM, E22) and sits between the published 200 m and 400 m.
  - Optional cross-check: Moon target roughness can be read from PGDA product 90.
  - Rosenburg et al. 2011 find a break near 1 km, so the 1000 m rough_b may be less stable.
  - The PDF's "brief says 300 m but features.yaml says 100 m" mismatch comes from reading origin/main (ca9a816), which predates E22. The integrate branch uses 300 m everywhere.
- Ledger corrections applied (config/ledger.yaml, rows marked `provisional: true` with a `check_note`; relevance matrix unchanged pending Vihaan and Anay): cold_traps (29 K measured, 38 K removed, 174.6 K detail unverified), radiation_uv ("Earth UV-A 10x sea level in Ladakh" NOT SUPPORTED, replaced by about 10 percent more UV per 1000 m (WHO) and a lunar particle dose of about 60 microsieverts per hour, more than 200 times the ground on Earth, not zero), los_earth_gps ("no GPS anywhere" NOT SUPPORTED, replaced by the NASA LuGRE tracking on 3 March 2025), regolith ("dry except in cold traps"), gravity (Mars mean 3.73 m/s2, 3.71 m/s2 is equatorial, NASA fact sheets), air_pressure and polar_lighting (sources added: NASA Moon and Mars fact sheets, NASA Glenn atmosphere, NASA SVS 4893, PGDA product 69).
- Open: Williams et al. 2019 south pole winter minimum not opened; Lunar Sourcebook regolith mechanics not opened; optional Hurst exponent and MAD roughness statistics not computed.
