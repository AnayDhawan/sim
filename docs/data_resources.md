# Data resources (Role C, branch `data/site-evidence`)

Status is for this branch only. "used" means an output file from this role exists now.

| Resource | Status | What for | Evidence file | Reason |
|---|---|---|---|---|
| NASA Earthdata Search | not used | none | none | MODIS MOD11A2 and ASTER GED are LP DAAC products, but they were read through Earth Engine. Their DOIs are in the ledger. |
| NASA Worldview | not used | none | none | Viewer; used for video visuals only. No data or output file comes from it. |
| NASA PDS | not used | none | none | No lunar or Mars archive data in this role. This role measures Earth sites. |
| NASA LRO | not used | none | none | Same: Earth-site evidence only. |
| NASA LRO Diviner | not used | none | none | Same. ASTER emissivity and MODIS temperature are Earth products and are not Diviner substitutes. |
| CSA RCM | not used | none | none | No RCM scenes requested. |
| CSA RADARSAT-1 | not used | none | none | Stretch item gated on G-C2. G-C2 was not met, so no listing or download was attempted. |
| CSA SAR Python tutorial | not used | none | none | Not needed. Sentinel-1 was processed in Earth Engine. |
| ESA Copernicus Data Space Ecosystem | not used | none | none | Sentinel-1, Sentinel-2 and the Copernicus DEM came through Earth Engine, not through the Copernicus Data Space portal. |
| ESA Open Science Catalog | not used | none | none | Stretch item gated on G-C2. Not met, no search made. No candidates recorded. |
| JAXA G-Portal | not used | none | none | ALOS AW3D30 came through Earth Engine (`JAXA/ALOS/AW3D30/V4_1`), not G-Portal. |

## Datasets actually used (all through Earth Engine, pulled 2026-11-15)

| Dataset | Version | Evidence file |
|---|---|---|
| `COPERNICUS/DEM/GLO30_2024_1` | 2024_1 | `data/evidence/site_measurements.csv` (dataset `cop_dem`) |
| `JAXA/ALOS/AW3D30/V4_1` | 4.1 | same file (`alos_dem`, `dem_crosscheck`) |
| `MODIS/061/MOD11A2` | 6.1 | same file (`mod11a2`) |
| `NASA/ASTER_GED/AG100_003` | V003 | same file (`aster_ged`) |
| `COPERNICUS/S2_SR_HARMONIZED` | harmonized | same file (`s2`, `s2_chip`) and `public/img/sites/` |
| `COPERNICUS/S1_GRD` | none stated | same file (`s1`) |
| `ESA/WorldCover/v200` | v200 | same file (`worldcover`) |

Per-dataset product, version, DOI or catalog URL, date range, pull time and output hash: `data/evidence/ledger_c.json`. Limits: `docs/evidence_limits.md`.
