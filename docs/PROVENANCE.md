# Data provenance

Every dataset used must have a verified row here: id or product, version, date range, resolution, licence, how it was checked and on what date. The Earth Engine rows below were checked live against the Earth Engine catalog on 2026-11-13 (project gsop-earthengine); date ranges were read with reduceColumns minMax on system:time_start. No PDS source has been verified yet (see `UNVERIFIED.md`).

The API returned empty properties for the collections, so version and licence are "not returned by the API, check the catalog page" except where the catalog gave a licence string.

**How "verified" is used here.** All rows below were checked on 2026-11-13 by opening the catalog or archive page (and, for Earth Engine, the official STAC JSON) and reading the id, bands, extent and licence text. Rows were read from catalog pages; the DEM id was then corrected from a real Earth Engine run by Anay (2026-11-13), and no other row has been queried through an authenticated session by this branch. Run `uv run gsop s2 earth --source gee --verify` before the first export and correct any row it contradicts. Licences are quoted as the pages state them; where a page names none, that is said.

## Earth Engine (issue #1) - `config/earth_layers.yaml`

| Layer | Source id | Bands used | Version | Date range | Resolution | Licence (as stated) |
|---|---|---|---|---|---|---|
| Elevation | `NASA/NASADEM_HGT/001` | `elevation` | V001 | 2000-02-11 to 2000-02-22 | 30 m, catalog bbox -56..60 lat | NASA data, "may be used for any purpose" |
| Elevation (fallback above 60N, below 56S) | `COPERNICUS/DEM/GLO30_2024_1` (the unversioned `COPERNICUS/DEM/GLO30` is deprecated; confirmed on a real run by Anay, 2026-11-13) | `DEM` (surface model) | 2024_1 | 2010-12-01 to 2020-11-13 | 30 m | free licence worldwide except Armenia and Azerbaijan; DLR/Airbus attribution |
| Land surface temperature | `MODIS/061/MOD11A2` | `LST_Day_1km`, `LST_Night_1km` (scale 0.02 K) | V6.1 | 2000-02-18 to present | 1 km, 8-day | LP DAAC: no restrictions on use, sale or redistribution |
| NDVI | `MODIS/061/MOD13A2` | `NDVI` (scale 0.0001), `SummaryQA` | V6.1 | 2000-02-18 to present | 1 km, 16-day | LP DAAC terms |
| Land cover | `MODIS/061/MCD12Q1` | `LC_Type1` (12 cropland, 13 built-up, 15 snow and ice, 17 water) | 6.1 | 2001 to 2025, year 2024 used | 500 m | LP DAAC terms |
| Precipitation (driest three months only) | `IDAHO_EPSCOR/TERRACLIMATE` | `pr` | no version; `status` provisional or permanent | 1958-01 to 2024-12 | 4.6 km, monthly | CC0 |

SRTM90 route (target-side E22): `CGIAR/SRTM90_V4`, STAC JSON https://storage.googleapis.com/earthengine-stac/catalog/CGIAR/CGIAR_SRTM90_V4.json read 2026-11-13, bbox longitude -180 to 180, latitude -56 to 60. Earth terrain therefore stops at 56 S and 60 N (SPEC section 3d). This branch did not run the export.

Checked and NOT used yet: `ESA/WorldCover/v200` (10 m, CC-BY-4.0, 60S to 84N only), `JRC/GSW1_4/GlobalSurfaceWater`, `NASA/ASTER_GED/AG100_003` (emissivity bands 10 to 14, lat -59..80; no band-ratio formula in our documents), `NASA/GPM_L3/IMERG_V07`, `NASA/GSFC/MERRA/aer/2` (`DUEXTTAU`), `MODIS/061/MCD19A2_GRANULES`. A community aridity asset (`projects/sat-io/open-datasets/global_ai/global_ai_yearly`) is documented on gee-community-catalog.org but its asset was not opened. **No global permafrost-probability raster exists in the official catalog**: a text search of all 1,182 STAC entries found only the basin polygons `WWF/HydroATLAS/v1/Basins/level08` (`prm_pc_sse`, CC-BY-4.0). The Obu et al. 2019 map (PANGAEA 10.1594/PANGAEA.888600, 1 km, EPSG:3995, CC-BY 3.0) covers only the northern hemisphere. So `water_index`, `silica_index` and `dust_index` are not built (see `not_built` in `config/earth_layers.yaml`).

## Open-data fallback (issue #8) - `src/gsop/earth/open_data.py`

| Product | Id | Resolution | Access | Notes |
|---|---|---|---|---|
| ETOPO 2022 v1 | DOI 10.25921/fd45-gt74 | 15, 30, 60 arcsec (15 arcsec is about 460 m); GeoTIFF/NetCDF; EPSG:4326, EGM2008 vertical | no login (HTTP 200 to a HEAD request on the 60 arcsec tile) | user guide: "freely available to use for all private, academic, or commercial purposes". Use the surface version. |
| GEBCO_2026 grid | gebco.net data products | 15 arcsec | no login stated | "placed in the public domain" |
| MOD11A2 | short name MOD11A2, version 061, CMR C2269056084-LPCLOUD, DOI 10.5067/MODIS/MOD11A2.061 | 1 km, HDF-EOS2 | Earthdata Login (general statement; no download attempted) | the loader reads GDAL rasters, so export GeoTIFF (for example AppEEARS) |
| ASTER GED AG100 | version 003, DOI 10.5067/COMMUNITY/ASTER_GED/AG100.003 | 100 m, HDF5 | Earthdata Login (general statement; no download attempted) | |

A ~1.8 km grid (for example ETOPO 60 arcsec) cannot give slope at the 500 m baseline, so the fallback leaves slope and relief out for it; the 15 arcsec grids can. Roughness (300 m and 1000 m baselines) is never built by the fallback.

## Moon (issue #3)

| Product | Where | Notes |
|---|---|---|
| LOLA south-polar DEM, PDS (IMG) | https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/img/ , for example `ldem_80s_20m.img` (labels: polar stereographic, 20 m/pixel, radius 1737.4 km) | IMG only on PDS; labels carry no PRODUCT_ID field |
| LOLA GeoTIFFs, PGDA | https://pgda.gsfc.nasa.gov/products/90 , for example `LDEM_80S_20MPP_ADJ.TIF` (HTTP 200, no login); 5 m: https://pgda.gsfc.nasa.gov/products/81 `ldem_87s_5mpp`, 3.3 GB (download URL not checked) | Barker et al. 2023, PSJ 4, 183, DOI 10.3847/PSJ/acf3e1; data DOI 10.60903/gsfcpgda-lola-spole; the page asks users to cite the paper and states no other licence; no vertical datum on the page |
| **LOLA DEM used for the Moon targets** | https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LDEM_80S_20MPP_ADJ.TIF , opened 2026-11-13 | HEAD: HTTP 200, Content-Length 2,696,082,051 bytes, Last-Modified 2023-07-07, no checksum published. Page: "LOLA Digital Elevation Model (LDEM) giving surface height (in meters)", cloud-optimised GeoTIFF. File header (read over HTTP): 30,400 x 30,400 float32, 20 m cells, `+proj=stere +lat_0=-90 +lat_ts=-90 +R=1737400`, x and y -304 to 304 km, nodata NaN, z range -7,296.8 to 7,027.2 m, history `gmt grdmath ... 1000.0 MUL` (km to m). The full file came at about 100 KB/s, so only the part that is used was taken: `data/raw/moon/LDEM_80S_20MPP_ADJ_clip32km.tif` = x and y in [-32, 32] km (3,200 x 3,200 cells, source pixels unchanged, same CRS and origin grid; both targets' 17 km reads lie inside it), read by HTTP range requests with `scripts/clip_pgda_cog.py` (re-running it gave the same sha256 for the PSR clip), sha256 b3dd66fed1c8c197c493c8a02b782332dce3b9e9374f3cf80fcfe262000b34e8, no NaN in the clip, -3,871.2 to 1,959.4 m. Grade A. Roughness windows: rough_a 300 m (15 cells, target-side E22), rough_b 1000 m (50 cells); profiles rebuilt from this clip on 2026-11-13 |
| **PSR raster used for Moon `water_index`** | https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LPSR_80S_20MPP_ADJ.TIF , opened 2026-11-13 | HEAD: HTTP 200, Content-Length 154,221,202 bytes, Last-Modified 2023-06-03, no checksum published. Page: "All PSRs (N=506349): LPSR_80S_20MPP_ADJ.TIF - 148M - PSR map"; the page does not state the pixel values. **Encoding read from the file**: float32, same grid as the LDEM (30,400 x 30,400, 20 m), declared nodata NaN, band metadata `actual_range {0,1}`; values present in the clip: 0 and 1 only, no NaN. Meaning of 1 checked against the DEM: 1 over a 1 km box on the Shackleton crater floor (-89.67, 129.78 E, elevation -2,789 m; that coordinate is from memory, used only as a sanity point), 0 at Connecting Ridge C1 and at the Shackleton rim target (both sunlit 76 to 81 percent of the time in `config/targets.yaml`). So 1 = permanently shadowed, 0 = not. Clip `data/raw/moon/LPSR_80S_20MPP_ADJ_clip32km.tif` (same [-32, 32] km box, sha256 8b7f4556f50f29dfcda587c3874de1399fc7dd1ddc1b6db0d0fd4bb58bbf79a6). `targets/moon.py` grades the row A only for this product with a strictly 0/1 window; any other PSR raster stays B with the CONFIRM note. The value is kept in the target file but `water_index` is dropped from the v1 Moon score (DECISIONS E19) |
| Diviner global grids (GDR L3) | https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/ : rock abundance and soil temperature to +-80 deg, **Christiansen feature map to +-70 deg only** (Lucey et al. 2021, Zenodo record 4558235: "+/- 70 degrees of latitude"; an earlier version of this row said 60 deg) | so `silica_index` cannot be built at the lunar poles |
| Diviner polar products | PCP (80 to 90 deg, 240 m/pixel, ASCII tables) and PRP (`LRO-L-DLRE-5-PRP-V2.0`, to 80 deg, annual mean and maximum surface temperature) | data files not opened; not wired. Diviner does reach the pole through these |

## Mars (issue #4)

| Product | Where | Notes |
|---|---|---|
| MOLA DEM 463 m | https://astrogeology.usgs.gov/search/map/mars_mgs_mola_dem_463m , file `Mars_MGS_MOLA_DEM_mosaic_global_463m.tif` (2.1 GB, HTTP 200, no login) | CC0; metres above the areoid; simple cylindrical. **The terrain operator cannot use this DEM as is**: 500 m is not a whole multiple of 463 m, and the 300 m roughness baseline is under one cell |
| **MOLA DEM used for Jezero** | https://planetarymaps.usgs.gov/mosaic/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif (302 to https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif), downloaded in full 2026-11-13 to `data/raw/mars/` | HEAD on the S3 object: HTTP 200, Content-Length 2,125,771,142 bytes (the downloaded file has exactly this size), Last-Modified 2022-11-10, ETag `cccf7001294ee9f503b13318eab83086-254` (a multipart ETag, not an MD5 of the file; no checksum published). sha256 of the download 38a4eb0b4452855b8dabfac40a367b458555ab4c01b31235807ad0a53c031f4c. Label opened (`mars_mgs_mola_dem_mosaic_global_463m.lbl` from the search page): 46,080 x 23,040 SignedWord (int16), Equirectangular, sphere radius 3,396,190 m, PixelResolution 463.093541550370901 m, 128 pixels per degree, DataSetId `mola128_mola64_merge_90Nto90S_clon0`. Slope and relief: the 17 km window is resampled bilinearly to 500 m cells (`targets/common.py resample_bilinear`), grade A with the resampling named in the row. Roughness: not built (see `docs/UNVERIFIED.md`) |
| **Mars solar constants** (Jezero `insol_annual`, `sun_max_elev`) | NASA Mars fact sheet https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html , opened 2026-11-13 ("Last Updated: 19 May 2025") | "Obliquity to orbit (deg) 25.19", "Solar irradiance (W/m2) 586.2" (eccentricity 0.0935 listed and not used, as Earth's is not). Put in `config/targets.yaml mars_solar` and run through the Earth code (`earth/solar.py`: latitude and obliquity, flat horizon, circular orbit). Grade C (computed) |
| THEMIS thermal inertia | USGS Astrogeology, quantitative 32-bit tiles at about 100 m/pixel (only tile 30S060E checked, ISIS cube) | global tiling not verified |
| **THEMIS thermal inertia, Jezero (used)** | Zenodo record 4931348, https://zenodo.org/records/4931348 , doi 10.5281/zenodo.4931348, "THEMIS-derived Thermal Inertia of Jezero Crater, Mars", Edwards and Buz, Northern Arizona University, version 1, published 2021-06-11, CC BY 4.0, one file `Jezero_Thermal_Inertia_v1.tiff` 1,721,889 bytes, md5 53fec7c990a90629e98c871a7a0da474 (the download matches size and md5 of the record) | Record text: "The image is in GeoTIFF format, has a null (black space) value of 0, and units of J/m2/K1/s1/2". File read on 2026-11-14: 890 x 890 float32 pixels, 100 m, one band, nodata 0, no band description, CRS "SimpleCylindrical Mars" (equirectangular, sphere radius 3,396,190 m, central meridian 0), extent x 4,564,100 to 4,653,100 m and y 1,052,100 to 1,141,100 m (89 km square), 298,150 of 792,100 pixels are 0 and no NaN. The description matches the file (GeoTIFF, nodata 0, thermal inertia range 42.4 to 1,655.3). The 15 km window around Jezero (18.4386 N, 77.5031 E, x 4,593,973 m, y 1,092,942 m, pixel row 481 col 298) lies fully inside the raster and every one of its 22,500 pixels is valid (covered fraction 1.0000, no 0 and no NaN). Rule (`targets/common.py tile_median_profile`): median of each 6 km tile at stride 3 km (4 x 4 = 16 tiles, all 100 percent valid), then median over tiles and IQR/1.349: **204.08 J/m2/K/s^1/2, spread 13.69**. Stored as `aux_thermal_inertia_si` (the D6 check: 204.08 is at least 100), grade A, status DERIVED. `ti_proxy` stays unavailable: the Earth column is a day-night temperature swing in K, THEMIS is thermal inertia in SI units, no conversion is defined. The record says the TES albedo is used and tile offsets up to about 20 are within the derivation uncertainty; Fergason et al. 2006 give about 20 percent accuracy for THEMIS thermal inertia (UNCERTAINTY_SOURCES.md) |
| **Mars Climate Database v6.2, surface temperature at Jezero (used)** | LMD web interface, https://www-mars.lmd.jussieu.fr/mcd_python/ (form opened 2026-11-14, page title "Mars Climate Database v6.2: The Web Interface"), request CGI `./cgi-bin/mcdcgi.py` (GET, field names read from the form; example URL in `docs/evidence/mcd_v6_2_jezero_tsurf_2026-11-14.meta.json`) | The PyPI package named `mcd` is a speech-processing tool (mel cepstral distortion), not this database, and the full MCD is a Fortran distribution from LMD (info page: "the MCD access software, as a Fortran subroutine"), so no package or database was installed and the web interface was used. Settings: `var1=tsurf` (Surface temperature, K), `dust=1` (climatology average solar), `zkey=3` altitude 0 m above surface, `hrkey=1` (form default; three test points gave the same tsurf with hrkey 0 and 1), latitude 18.4386, longitude 77.5031 E. Every response says `MCD_v6.2 with climatology average solar scenario`. Sampling: Ls 0, 15, ..., 345 (24 values) x local true solar time 0, 1, ..., 23 martian hours = 576 requests, table `docs/evidence/mcd_v6_2_jezero_tsurf_2026-11-14.csv`, script `scripts/mcd_jezero.py`. Range of the table 185.79 to 286.79 K. The service gives one point per request: the MCD GCM grid is coarse (a few degrees), so nothing varies inside the 15 km window and spread is 0 by construction. A `diumean=on` request returns the local-time-0 value for a single point (24 such requests were identical to the LT 0 rows and were dropped). Month lengths for the time weights: the LMD page http://www-mars.lmd.jussieu.fr/mars/time/solar_longitude.html (opened 2026-11-14), twelve 30-degree Ls months of 61.2, 65.4, 66.7, 64.5, 59.7, 54.4, 49.7, 46.9, 46.1, 47.4, 50.9, 55.7 sols, total 668.6 sols. Exact calculation (`targets/mars.py mcd_stats`): daily mean(Ls) = mean over the 24 local times, daily minimum(Ls) = minimum over the 24 local times. **t_mean = 224.098 K**: the daily means at the 12 month-centre Ls (15, 45, ..., 345) weighted by month length in sols (the unweighted mean over all 24 Ls is 223.722 K, 0.38 K lower). **t_coldest = 185.788 K**: the lowest daily minimum over all Ls, reached at Ls 285, local time 5 h (neighbours 186.39 K at 6 h and 186.90 K at 4 h; hourly sampling can miss a true minimum between hours by a fraction of a kelvin). For comparison, the coldest-season daily mean is 214.213 K (Ls 285). Grade C, status DERIVED. MCD is a model; the Earth columns are MODIS LST observations, so comparability is PARTIAL: the lowest daily minimum is colder than a coldest-month mean LST, and the repo's own definition in `config/features.yaml` is "coldest-month surface temperature" (about 214 K here) |
| TES thermal inertia, Putzig and Mellon 2007 | PDS `mgs-m-tes-5-timap-v1/mgst_9001`, 20 pixels per degree | |
| TES albedo | https://planetarymaps.usgs.gov/mosaic/Mars_MGS_TES_Albedo_mosaic_global_7410m.tif | no numeric TES dust cover index found (only a colorised ASU map) |
| SWIM ice consistency | https://swim.psi.edu : SWIM 2.0 composites "Combined Ice Consistency" for 0-1 m, 1-5 m and >5 m; downloads are web forms, no file was retrieved | the composite needs a depth choice. 2019 northern-hemisphere GeoTIFFs: simple cylindrical, 3000 m, no-data -30 |
| Mars atmosphere | NASA Glenn model https://www.grc.nasa.gov/www/k-12/airplane/atmosmrm.html : p = 0.699 exp(-0.00009 h) kPa, T = -31 - 0.000998 h C (h up to 7,000 m); NASA fact sheet https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html : 6.36 mb, scale height 11.0 km | the plan's "610 Pa, 11.1 km" pair is in no single source we read |

**Arcadia Planitia centre: no published centre point was found.** The SWIM pages and the Morgan et al. 2021 abstract print none. The Putzig and Morgan et al. chapter (Handbook of Space Resources, accepted manuscript https://nathaniel.putzig.com/publications/Putzig_and_Morgan_et_al_2023_accepted.pdf) gives region definitions only: pilot study region "0 N to 60 N, 190 E to 210 E"; "Arcadia Planitia (170-220 E)" for the high-consistency area at 40 to 45 deg latitude. Arcadia therefore stays `unscored: no target data` (D10). Do not turn a region box into a point without a decision from the team.

## Earth standard atmosphere (Earth `air_density`)

NASA Glenn metric model, troposphere (to 11 km): T = 15.04 - 0.00649 h (C), p = 101.29 ((T + 273.1) / 288.08)^5.256 (kPa), rho = p / (0.2869 (T + 273.1)). https://www.grc.nasa.gov/www/k-12/airplane/atmosmet.html . ICAO Doc 7488 and USSA-1976 were not opened.

### Rows checked live by the phase2-gee route (Earth Engine API, 2026-11-13)

These ids are the ones `earth/gee_export.py` (the route that ran) uses; the table above is the one `earth/gee_export_layers.py` and `config/earth_layers.yaml` use.

| Layer | Source id | Version | Date range | Resolution | Licence | Verified on |
|---|---|---|---|---|---|---|
| DEM, 56S to 60N | NASA/NASADEM_HGT/001 | not returned by the API, check the catalog page | 2000-02-11 to 2000-02-22 | 1 arc-second (about 30 m) | NASA / USGS / JPL-Caltech (string in catalog) | 2026-11-13 |
| DEM elsewhere | COPERNICUS/DEM/GLO30_2024_1 | not returned by the API, check the catalog page | 2010-12-12 to 2020-11-12 | 30.9 m nominal | not returned by the API, check the catalog page | 2026-11-13 |
| Surface temperature | MODIS/061/MOD11A2 | not returned by the API, check the catalog page | 2000-02-18 to 2026-11-01 | 926.6 m | not returned by the API, check the catalog page | 2026-11-13 |
| NDVI | MODIS/061/MOD13A2 | not returned by the API, check the catalog page | 2000-02-18 to 2026-10-16 | 926.6 m | not returned by the API, check the catalog page | 2026-11-13 |
| Land cover | MODIS/061/MCD12Q1 | not returned by the API, check the catalog page | 2001-01-01 to 2025-01-01 | 463 m | not returned by the API, check the catalog page | 2026-11-13 |
| PET | MODIS/061/MOD16A2GF | not returned by the API, check the catalog page | 2000-01-01 to 2025-12-27 | 463 m | not returned by the API, check the catalog page | 2026-11-13 |
| Precipitation | NASA/GPM_L3/IMERG_MONTHLY_V07 | not returned by the API, check the catalog page | 1998-01-01 to 2025-09-01 | 11.1 km | not returned by the API, check the catalog page | 2026-11-13 |
| Emissivity | NASA/ASTER_GED/AG100_003 | not returned by the API, check the catalog page | catalog start values 946684800000 and 1230681600000 ms | 100 m | not returned by the API, check the catalog page | 2026-11-13 |
| Dust | NASA/GSFC/MERRA/aer/2 | not returned by the API, check the catalog page | 1980-01-01 to 2026-10-01 | 62 km | not returned by the API, check the catalog page | 2026-11-13 |

### Layer notes (phase2-gee)

- NASADEM: bands elevation, num, swb.
- COPERNICUS/DEM/GLO30 is deprecated and superseded by GLO30_2024_1, which is the id used.
- MOD11A2: bands LST_Day_1km and LST_Night_1km. Years 2015-2024 are used. Scale 0.01 for the mean and 0.02 for the day-night swing, as in the code.
- MOD13A2: band NDVI, scale 0.0001.
- MCD12Q1: band LC_Type1 (IGBP), year 2023 used. Classes: 17 water, 15 snow and ice, 13 built-up, 12 cropland.
- MOD16A2GF: band PET.
- IMERG monthly: band precipitation.
- ASTER GED: bands emissivity_band10 to emissivity_band14.
- MERRA-2 aerosol: band DUEXTTAU.

### Derived choices (phase2-gee)

- `water_index` (Earth): 1 - min(P/PET, 1). P is IMERG monthly precipitation times hours per year. PET is MOD16A2GF PET scaled by 0.1 and by 365.25/8. This is an aridity-only proxy; 1 is arid. It deviates from the plan (see `UNVERIFIED.md`).
- `dust_index`: the mean MERRA-2 DUEXTTAU, dust extinction optical depth at 550 nm. Dimensionless, not a 0-1 index.
- `silica_index`: e11^2 / (e10 * e12) from ASTER GED emissivity bands scaled by 0.001 (quartz index; the formula is from memory).
- `land_frac`: the share of MCD12Q1 cells that are not class 17.
- `water_ice_frac`: MCD12Q1 classes 17 plus 15.
- `built_crop_frac`: MCD12Q1 classes 13 plus 12.

## Moon target evidence from Vihaan (2026-11-14)

Copy: `docs/evidence/moon_evidence_vihaan_2026-11-14.csv` (from `data/raw/gsop_moon_evidence_table.csv`). Every row: agent-assisted, source pages opened by Vihaan's chat, not re-verified by us.

| Column | Targets | Result | Products and URLs named in the table |
|---|---|---|---|
| t_mean | connecting_ridge_c1, shackleton_rim | NOT FOUND at the targets | Diviner Polar Resource Product (PRP, modelled annual average surface temperature) and Diviner Polar Cumulative Products (PCP, binned bolometric brightness temperature, 240 m), https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/ (data_derived_prp, data_derived_pcp) |
| t_coldest | both | NOT FOUND; a coldest SEASON is the best possible: PCP has 6 Ls bins of about 58 days, so a coldest month cannot be resolved | https://www.diviner.ucla.edu/single-post/2020/07/20/new-diviner-seasonal-polar-data-products (maps poleward of 80 deg); Williams et al. 2019, JGR Planets 124:2505, doi 10.1029/2019JE006028 |
| ti_proxy | both | NOT COMPARABLE: the Sun stays within about 1.5 deg of the horizon, so there is no 24 h day-night swing; the subsolar-longitude cycle is a 29.5 day shadowing cycle | PDS Diviner derived products (as above) |
| silica_index | both | NONE EXISTS above 70 deg | Diviner Christiansen Feature map, Lucey et al. 2021, https://zenodo.org/record/4558235 ("+/- 70 degrees of latitude", 32 pixels per degree) |

- WARNING: Williams et al. 2019 prints temperatures for "Connecting Ridge C2". Repo rule: never C2. Those numbers must not be used for connecting_ridge_c1.

## Mars target evidence from Shiven (2026-11-14)

Copy: `docs/evidence/mars_evidence_shiven_2026-11-14.csv` (from `data/raw/gsop_mars_silica_swim_dci.csv`). Every row: agent-assisted, source pages opened by Shiven's chat, not re-verified by us.

| Column | Target | Result | Products and URLs named in the table |
|---|---|---|---|
| silica_index | jezero | NONE EXISTS comparable to the Earth quartz index: Tarnas et al. 2019 (GRL 46:12771) has CRISM detections of hydrated silica at two outcrops only, no abundance or index; Salvatore et al. 2018 (Icarus 301:76) TIR bulk mineralogy is basaltic, no silica value for Jezero | https://authors.library.caltech.edu/99688/ ; https://arxiv.org/pdf/1107.3499 |
| water_index | jezero | NOT FOUND: SWIM 2.0 Combined Ice Consistency (Morgan et al. 2021, Nature Astronomy 5:230), pixel 3000 m, ice mapping 0 to 60 N; no value read at Jezero. NOT COMPARABLE: SWIM is a subsurface ice likelihood, the Earth column is an aridity index | https://swim.psi.edu/SWIM2Products.php |
| dust_index | jezero | NOT FOUND: MGS TES Dust Cover Index (Ruff and Christensen 2002, JGR 107, doi 10.1029/2001JE001580), 16 pixels per degree, about 3.5 km; no Jezero value. NOT COMPARABLE: DCI is surface dust cover, the Earth column is atmospheric dust | http://www.mars.asu.edu/~ruff/DCI/dci.html ; https://www.mars.asu.edu/data/tes_ruffdust |

### Shiven's second Mars message (2026-11-14)

Every row: agent-assisted, source pages opened by Shiven's chat, not re-verified by us.

| Item | Source | Notes |
|---|---|---|
| Earth quartz index QI = D11 x D11 / (D10 x D12) | Ninomiya and Fu 2016, Geosciences 6(3):39, Eq. 2, https://doi.org/10.3390/geosciences6030039 | computed there on normalised at-sensor radiance, not GED emissivity; not exported in v1 (E31) |
| ASTER TIR bands B10 8.125-8.475, B11 8.475-8.825, B12 8.925-9.275 um, 90 m | Corrie et al., arXiv 1107.3499, Table 1 | |
| ASTER GED | NASA/ASTER_GED/AG100_003 | scale 0.001, pixel 111.32 m, latitude -59 to 80, clear-sky 2000 to 2008, 0 means no data |
| Jezero thermal inertia 330 SI (traverse mean, 295 to 350, about 20 percent accuracy) | Martinez et al. 2023, JGR Planets, doi 10.1029/2022JE007537 | our window median 204.08 SI from Zenodo 4931348; different samples, both pass D6, unscored |
| Landing-site model inputs TI 260 to 321 SI, albedo 0.1342 to 0.1935 | Newman et al. 2021, Table 1, PMC7868679 | grid-smoothed model inputs, not measurements |
| TES Dust Cover Index, floating point, 16 ppd, 5760 x 2880, about 66 MB | ASU (https://www.mars.asu.edu/data/tes_ruffdust) | not comparable, unscored |
| SWIM4MIM ice consistency, 3000 m, no data -30, -60 to 60 | https://swim.psi.edu/SWIM2Products.php | value at Jezero not read, unscored |

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
