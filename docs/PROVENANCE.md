# Data provenance

Every dataset used must have a verified row here: id or product, version, date range, resolution, licence, how it was checked and on what date.

**How "verified" is used here.** All rows below were checked on 2026-11-13 by opening the catalog or archive page (and, for Earth Engine, the official STAC JSON) and reading the id, bands, extent and licence text. **No row has been queried through an authenticated Earth Engine session**, because that login belongs to Anay. Run `uv run gsop s2 earth --source gee --verify` before the first export and correct any row it contradicts. Licences are quoted as the pages state them; where a page names none, that is said.

## Earth Engine (issue #1) - `config/earth_layers.yaml`

| Layer | Source id | Bands used | Version | Date range | Resolution | Licence (as stated) |
|---|---|---|---|---|---|---|
| Elevation | `NASA/NASADEM_HGT/001` | `elevation` | V001 | 2000-02-11 to 2000-02-22 | 30 m, catalog bbox -56..60 lat | NASA data, "may be used for any purpose" |
| Elevation (fallback above 60N, below 56S) | `COPERNICUS/DEM/GLO30` | `DEM` (surface model) | page says superseded by `COPERNICUS/DEM/GLO30_2024_1` | 2010-12-01 to 2015-01-31 | 30 m | free licence worldwide except Armenia and Azerbaijan; DLR/Airbus attribution |
| Land surface temperature | `MODIS/061/MOD11A2` | `LST_Day_1km`, `LST_Night_1km` (scale 0.02 K) | V6.1 | 2000-02-18 to present | 1 km, 8-day | LP DAAC: no restrictions on use, sale or redistribution |
| NDVI | `MODIS/061/MOD13A2` | `NDVI` (scale 0.0001), `SummaryQA` | V6.1 | 2000-02-18 to present | 1 km, 16-day | LP DAAC terms |
| Land cover | `MODIS/061/MCD12Q1` | `LC_Type1` (12 cropland, 13 built-up, 15 snow and ice, 17 water) | 6.1 | 2001 to 2025, year 2024 used | 500 m | LP DAAC terms |
| Precipitation (driest three months only) | `IDAHO_EPSCOR/TERRACLIMATE` | `pr` | no version; `status` provisional or permanent | 1958-01 to 2024-12 | 4.6 km, monthly | CC0 |

Checked and NOT used yet: `ESA/WorldCover/v200` (10 m, CC-BY-4.0, 60S to 84N only), `JRC/GSW1_4/GlobalSurfaceWater`, `NASA/ASTER_GED/AG100_003` (emissivity bands 10 to 14, lat -59..80; no band-ratio formula in our documents), `NASA/GPM_L3/IMERG_V07`, `NASA/GSFC/MERRA/aer/2` (`DUEXTTAU`), `MODIS/061/MCD19A2_GRANULES`. A community aridity asset (`projects/sat-io/open-datasets/global_ai/global_ai_yearly`) is documented on gee-community-catalog.org but its asset was not opened. **No global permafrost-probability raster exists in the official catalog**: a text search of all 1,182 STAC entries found only the basin polygons `WWF/HydroATLAS/v1/Basins/level08` (`prm_pc_sse`, CC-BY-4.0). The Obu et al. 2019 map (PANGAEA 10.1594/PANGAEA.888600, 1 km, EPSG:3995, CC-BY 3.0) covers only the northern hemisphere. So `water_index`, `silica_index` and `dust_index` are not built (see `not_built` in `config/earth_layers.yaml`).

## Open-data fallback (issue #8) - `src/gsop/earth/open_data.py`

| Product | Id | Resolution | Access | Notes |
|---|---|---|---|---|
| ETOPO 2022 v1 | DOI 10.25921/fd45-gt74 | 15, 30, 60 arcsec (15 arcsec is about 460 m); GeoTIFF/NetCDF; EPSG:4326, EGM2008 vertical | no login (HTTP 200 to a HEAD request on the 60 arcsec tile) | user guide: "freely available to use for all private, academic, or commercial purposes". Use the surface version. |
| GEBCO_2026 grid | gebco.net data products | 15 arcsec | no login stated | "placed in the public domain" |
| MOD11A2 | short name MOD11A2, version 061, CMR C2269056084-LPCLOUD, DOI 10.5067/MODIS/MOD11A2.061 | 1 km, HDF-EOS2 | Earthdata Login (general statement; no download attempted) | the loader reads GDAL rasters, so export GeoTIFF (for example AppEEARS) |
| ASTER GED AG100 | version 003, DOI 10.5067/COMMUNITY/ASTER_GED/AG100.003 | 100 m, HDF5 | Earthdata Login (general statement; no download attempted) | |

A ~1.8 km grid (for example ETOPO 60 arcsec) cannot give slope at the 500 m baseline, so the fallback leaves slope and relief out for it; the 15 arcsec grids can. Roughness (100 m and 1000 m baselines) is never built by the fallback.

## Moon (issue #3)

| Product | Where | Notes |
|---|---|---|
| LOLA south-polar DEM, PDS (IMG) | https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/img/ , for example `ldem_80s_20m.img` (labels: polar stereographic, 20 m/pixel, radius 1737.4 km) | IMG only on PDS; labels carry no PRODUCT_ID field |
| LOLA GeoTIFFs, PGDA | https://pgda.gsfc.nasa.gov/products/90 , for example `LDEM_80S_20MPP_ADJ.TIF` (HTTP 200, no login); 5 m: https://pgda.gsfc.nasa.gov/products/81 `ldem_87s_5mpp`, 3.3 GB (download URL not checked) | Barker et al. 2023, PSJ 4, 183, DOI 10.3847/PSJ/acf3e1; no licence text and no vertical datum on the page |
| Permanently shadowed regions | same PGDA page: `LPSR_80S_20MPP_ADJ` (TIF, SHP, CSV; N=506,349) and `..._1km2` (N=1,531) | pixel encoding NOT checked; `targets/moon.py` treats non-zero as shadowed and says to confirm |
| Diviner global grids (GDR L3) | https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/ : rock abundance and soil temperature to +-80 deg, **Christiansen feature to +-60 deg only** | so `silica_index` cannot be built at the lunar poles |
| Diviner polar products | PCP (80 to 90 deg, 240 m/pixel, ASCII tables) and PRP (`LRO-L-DLRE-5-PRP-V2.0`, to 80 deg, annual mean and maximum surface temperature) | data files not opened; not wired. Diviner does reach the pole through these |

## Mars (issue #4)

| Product | Where | Notes |
|---|---|---|
| MOLA DEM 463 m | https://astrogeology.usgs.gov/search/map/mars_mgs_mola_dem_463m , file `Mars_MGS_MOLA_DEM_mosaic_global_463m.tif` (2.1 GB, HTTP 200, no login) | CC0; metres above the areoid; simple cylindrical. **The terrain operator cannot use this DEM as is**: 500 m is not a whole multiple of 463 m, and the 100 m roughness baseline is finer than the cells |
| THEMIS thermal inertia | USGS Astrogeology, quantitative 32-bit tiles at about 100 m/pixel (only tile 30S060E checked, ISIS cube) | global tiling not verified |
| TES thermal inertia, Putzig and Mellon 2007 | PDS `mgs-m-tes-5-timap-v1/mgst_9001`, 20 pixels per degree | |
| TES albedo | https://planetarymaps.usgs.gov/mosaic/Mars_MGS_TES_Albedo_mosaic_global_7410m.tif | no numeric TES dust cover index found (only a colorised ASU map) |
| SWIM ice consistency | https://swim.psi.edu : SWIM 2.0 composites "Combined Ice Consistency" for 0-1 m, 1-5 m and >5 m; downloads are web forms, no file was retrieved | the composite needs a depth choice. 2019 northern-hemisphere GeoTIFFs: simple cylindrical, 3000 m, no-data -30 |
| Mars atmosphere | NASA Glenn model https://www.grc.nasa.gov/www/k-12/airplane/atmosmrm.html : p = 0.699 exp(-0.00009 h) kPa, T = -31 - 0.000998 h C (h up to 7,000 m); NASA fact sheet https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html : 6.36 mb, scale height 11.0 km | the plan's "610 Pa, 11.1 km" pair is in no single source we read |

**Arcadia Planitia centre: no published centre point was found.** The SWIM pages and the Morgan et al. 2021 abstract print none. The Putzig and Morgan et al. chapter (Handbook of Space Resources, accepted manuscript https://nathaniel.putzig.com/publications/Putzig_and_Morgan_et_al_2023_accepted.pdf) gives region definitions only: pilot study region "0 N to 60 N, 190 E to 210 E"; "Arcadia Planitia (170-220 E)" for the high-consistency area at 40 to 45 deg latitude. Arcadia therefore stays `unscored: no target data` (D10). Do not turn a region box into a point without a decision from the team.

## Earth standard atmosphere (Earth `air_density`)

NASA Glenn metric model, troposphere (to 11 km): T = 15.04 - 0.00649 h (C), p = 101.29 ((T + 273.1) / 288.08)^5.256 (kPa), rho = p / (0.2869 (T + 273.1)). https://www.grc.nasa.gov/www/k-12/airplane/atmosmet.html . ICAO Doc 7488 and USSA-1976 were not opened.
