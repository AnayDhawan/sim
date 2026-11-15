# Earth Engine export cost: measured on one box, with cheaper variants

Measured 2026-11-13, project `gsop-earthengine`, by `scripts/ee_cost_probe.py` (raw results in `results/ee_cost_probe.json`, gitignored).

The only quota number used here is the monthly limit of 540,000 EECU-seconds (the value read from the console). Every extrapolation below is a rough linear scaling from ONE box that is almost entirely cropland. It is not a forecast for the globe.

## What was run

- Box: lon 76.51, lat 19.98 (Lonar), 60 km half-width, grid cells ix0 4114, iy0 797, 20 x 20 = 400 tiles of 6 km.
- Region and transform from `gee_export.chunk_region`, CRS `gee_export.CRS_WKT`, `ee.batch.Export.image.toDrive(fileFormat="GeoTIFF", maxPixels=1e10)` into Drive folder `gsop_probe`. Three tasks started together, polled every 30 s.
- Probe A: `full_stack()`, 17 bands, as it is today.
- Probe B: `landcover_bands()`, 4 gate bands (land_frac, water_ice_frac, ndvi_median, built_crop_frac).
- Probe C: `terrain_bands(100.0, "srtm90", (3, 10))`, 6 bands (slope_med, slope_p90, relief, elev_mean, rough_a, rough_b) from a 90 m DEM on a 100 m working grid. Slope baseline stays 500 m (5 cells), tile is 60 cells, roughness windows are 3 and 10 cells (300 m and 1000 m).
- No global export was started and no task was cancelled.

## 90 m DEM ids, checked live with `ee.data.getAsset`

| Id | Resolves | Bands | Nominal scale |
|---|---|---|---|
| `COPERNICUS/DEM/GLO90` | No ("not found") | n/a | n/a |
| `CGIAR/SRTM90_V4` | Yes (IMAGE) | `elevation` | 92.77 m |

Probe C used `CGIAR/SRTM90_V4`. Its latitude coverage was not checked here. Copernicus GLO30 (30 m) is the only Copernicus DEM id that resolved in this project, so a 90 m variant for high latitudes would need GLO30 block-averaged to 90 m or 100 m, which is a different (and more expensive) computation that was not measured.

## Measured batch cost

Times are UTC from the task status timestamps (`creation`, `start`, `update`).

| Probe | Task id | State | Created | Started | Last update | Run time (start to update) | `batch_eecu_usage_seconds` | Polls |
|---|---|---|---|---|---|---|---|---|
| A full stack | WYOD7RVJUPWJJJ3S3TIT5CTU | COMPLETED | 11:11:35 | 11:11:38 | 11:26:03 | 865 s | 707.78 | 29 |
| B gate layers | 6MCOM3WFTUDOFUR45PTAEYJG | COMPLETED | 11:11:38 | 11:11:42 | 11:12:01 | 18.6 s | 4.44 | 2 |
| C terrain 90 m | IQ6K2FI6CEWA73KLDNLHU7C4 | COMPLETED | 11:11:41 | 11:12:07 | 11:12:23 | 16.1 s | 11.52 | 3 |

All three finished inside the 20 minute polling cap.

| Probe | EECU-s per tile (400 tiles) |
|---|---|
| A full stack | 1.769 |
| B gate layers | 0.0111 |
| C terrain at 90 m / 100 m | 0.0288 |

For comparison, the earlier interactive downloads were roughly 10 EECU-s per tile, so the batch route measured here is about 5.7 times cheaper per tile for the full stack.

Caveats on the per-tile numbers:
- B and C are tiny tasks (4 and 12 EECU-s in total). A fixed per-task overhead would be a large part of those totals, so their true per-tile cost at global chunk size could be lower than shown. A is large enough that overhead matters little.
- The 17 bands of A were not split by cost. How much of the 707.78 is terrain at 33.333 m versus the climate bands was not measured. Probe C is a 90 m terrain cost, not a 33 m one.
- The Lonar box is flat-to-rolling cropland. Rugged terrain, other land cover, or different data densities could change the cost per tile in either direction.

## Gate share on this box

Gate rule from the task: ndvi_median <= 0.2, water_ice_frac <= 0.5, built_crop_frac <= 0.2. Read from a direct download of the four gate bands (400 of 400 tiles had finite values).

| Gate | Tiles passing | Median value in the box |
|---|---|---|
| ndvi_median <= 0.2 | 0 of 400 | 0.40 |
| water_ice_frac <= 0.5 | 400 of 400 | 0.0 |
| built_crop_frac <= 0.2 | 1 of 400 | 1.0 |
| All three | 0 of 400 (0%) | n/a |

The box is almost entirely cropland (median built_crop_frac 1.0) with moderate NDVI, so it passes none of the gates. This is a rate from one agricultural box and says nothing about the surviving share worldwide. It does mean this box cannot calibrate the gate-first option: the real pass share `p` is unknown and the gate-first rows below are parametric in `p`.

## Linear extrapolation to about 4 million land tiles

Rough linear scaling from one agricultural box. Quota is 540,000 EECU-s per month.

| Variant | EECU-s per tile | Total for about 4,000,000 tiles | Multiple of 540,000 |
|---|---|---|---|
| A full stack, all tiles | 1.769 | 7,077,783 | 13.1 |
| B gate layers, all tiles | 0.0111 | 44,439 | 0.082 (8.2%) |
| C terrain 90 m, all tiles | 0.0288 | 115,216 | 0.213 (21.3%) |
| B + C, all tiles | 0.0399 | 159,655 | 0.296 (29.6%) |

Gate-first, treating A per tile as an upper bound for the work done on each surviving tile (B for all tiles, then A only for survivors), with `p` the share of tiles that pass the gates:

| Pass share p (illustrative, not a prediction) | Cost B + p x A | Multiple of 540,000 |
|---|---|---|
| 0.05 | 398,328 | 0.74 |
| 0.10 | 752,217 | 1.39 |
| 0.25 | 1,813,884 | 3.36 |
| 0.50 | 3,583,330 | 6.64 |
| Break-even for one month | p = 0.070 | 1.00 |
| Break-even for two months (1,080,000) | p = 0.146 | 1.00 |

Gate-first with Probe C terrain for survivors (B for all tiles, then C only for survivors; climate bands not included because they were not measured separately):

| p | Cost B + p x C | Multiple of 540,000 |
|---|---|---|
| 0.05 | 50,199 | 0.093 |
| 0.10 | 55,960 | 0.104 |
| 0.25 | 73,243 | 0.136 |
| 0.50 | 102,047 | 0.189 |

## Options for Anay (no recommendation)

| Option | Estimated cost | Share of one month's 540,000 | What it gives up or needs |
|---|---|---|---|
| 1. Full stack as is, one project, one month | 7,077,783 | 1310% | Not possible: 13.1 times over the limit. |
| 2. Full stack spread over two months | 7,077,783 total, 3,538,892 per month | 655% per month | Still not possible. Needs about 14 months at the monthly limit. |
| 3. Split the full stack across other Earth Engine projects (each has its own 540,000) | 7,077,783 total, about 505,600 each across 14 projects | about 94% each | 14 projects, each at the limit with no margin; chunks assigned per project and Drive outputs merged. Whether 14 team members can each run a project, and whether Earth Engine terms allow this split, is not verified. |
| 4. Gate-first export (cheap gates globally, then the full stack for survivors only) | 44,439 + p x 7,077,783 | 8.2% + p x 1310% | Needs the real p. Fits one month only if p <= 7.0% and two months only if p <= 14.6%. Tiles failing the gates get no terrain or climate features at all. A second pass (list of surviving tiles) must be built and fed back as export regions. |
| 5. Coarser terrain for all tiles (Probe C) | 115,216 (terrain only), 159,655 with the gates | 21.3% (29.6% with gates) | No 33.333 m DEM, no 100 m roughness window (smallest window is 300 m), 100 m working grid resampled from a 92.8 m DEM, so terrain features differ from the 33 m route and from `gsop.operators` checks. Climate bands still need their own cost on top. High-latitude coverage of the 90 m source is not checked. |
| 6. Gate-first plus coarser terrain for survivors | 44,439 + p x 115,216 | 8.2% + p x 21.3% (13.6% at p = 0.25) | Combines the gaps of options 4 and 5. |
| 7. Gate-first over two months | Same as option 4 | Break-even p is 14.6% | Doubles the allowed survivor share at the price of a two-month schedule. |

## Open items before any choice

- The climate bands (t_mean, t_coldest, ti_proxy, ti_is_fallback, dust_index, water_index, silica_index) and the 33.333 m terrain were never costed separately. A fourth probe (terrain at 33.333 m only, and climate only) on the same box would give the split. It was not run because it was outside the three requested probes.
- The real gate pass share needs a global or multi-biome gate map, which Probe B scaled up would produce for about 44,000 EECU-s.
- Per-tile cost at global chunk size (about 100,000 tiles per task at 40 chunks) was not measured. Scaling a 400-tile task by 10,000 is the weakest step in every number above.

## Probe D and global gate export

Measured 2026-11-13 by `scripts/ee_probe_d.py` (raw results in `results/ee_probe_d.json`, gitignored). Nothing above this section is replaced.

### Probe D: Atacama box, three separate batch tasks

- Box: lon -68.2, lat -23.5, 60 km half-width, grid cells ix0 1787, iy0 1699, 20 x 20 = 400 tiles. Same `chunk_region`, `CRS_WKT`, `Export.image.toDrive` (GeoTIFF, maxPixels 1e10) route as Probes A to C, Drive folder `gsop_probe`, polled every 30 s.
- D1 `terrain_bands()` at the default 33.333 m (6 bands). D2 `climate_bands()` (7 bands). D3 `landcover_bands()` (4 gate bands).
- All three COMPLETED well inside the 25 minute cap.

| Probe | Task id | Created (UTC) | Started | Last update | Run time | `batch_eecu_usage_seconds` | EECU-s per tile | Share of D1+D2+D3 |
|---|---|---|---|---|---|---|---|---|
| D1 terrain 33.333 m | XQJIIGK747M3ODO4OSSOKLGR | 11:38:53 | 11:39:00 | 11:41:13 | 133 s | 111.76 | 0.2794 | 20.7% |
| D2 climate | UNZY3HINZJ45PAVL6EJLIFK4 | 11:38:55 | 11:39:22 | 11:47:49 | 507 s | 421.08 | 1.0527 | 78.0% |
| D3 gate layers | E7L7IODECROQZ3NKU3BAUK6F | 11:38:58 | 11:41:17 | 11:41:44 | 26 s | 6.92 | 0.0173 | 1.3% |
| D1 + D2 + D3 | | | | | | 539.77 | 1.3494 | 100% |

- Versus Probe A (full stack, Lonar, 1.769 EECU-s per tile): D1+D2+D3 is 1.349, which is 23.7% lower. That is a moderate difference, not a large one, and it mixes two effects: a different box (barren desert versus cropland) and three separate tasks versus one 17-band task. Overhead shared inside one task would push the sum of separate tasks up, so the box difference is at least as large as the 23.7%. This probe cannot separate the two.
- D3 per tile (0.0173) is 56% higher than Probe B on Lonar (0.0111). Both are tiny tasks (7 and 4 EECU-s in total), so a fixed per-task overhead is probably most of the gap.

### Climate versus terrain split (this box)

- Climate (D2) is 78.0% of the three-part sum, terrain at 33.333 m (D1) is 20.7%, gate layers (D3) are 1.3%.
- Climate costs 3.77 times what 33.333 m terrain costs per tile on this box.
- Terrain at 90 m / 100 m (Probe C, Lonar, 0.0288 per tile) is about 10 times cheaper than 33.333 m terrain (D1, Atacama, 0.2794). The two probes are on different boxes, so the ratio is indicative only.
- Removing terrain entirely (gate plus climate) would save only 20.7% of the full cost on this box. Climate is the larger lever.

### Gate share on the Atacama box

Same gate rule as before, read from a direct download of the four D3 bands (400 of 400 tiles finite; the downloaded array had 420 cells, 20 were nodata edge cells and are excluded).

| Gate | Tiles passing (of 400) | Median in the box |
|---|---|---|
| ndvi_median <= 0.2 | 400 | 0.075 |
| water_ice_frac <= 0.5 | 400 | 0.0 |
| built_crop_frac <= 0.2 | 400 | 0.0 |
| All three | 400 of 400 (100%) | n/a |

This is one desert box. It passes everything, as Lonar passed nothing. The two boxes bracket the range and say nothing about the global share p.

### Global gate export: not run

`scripts/ee_gate_export.py` and `gee_export.start_gate_export` were written (landcover_bands only, 4 bands, same 10 x 4 chunking, region and CRS as `start_global_export`, `Export.image.toAsset` into `projects/gsop-earthengine/assets/gsop_gate/`). No task was started. Creating the asset folder failed: `Asset 'projects/gsop-earthengine/assets' does not exist or doesn't allow this operation`, and `getAssetRoots()` / `listAssets` on `projects/gsop-earthengine/assets` return nothing for this project. The Cloud project has no Earth Engine asset root. Creating one is a Cloud project setup step (the Assets tab of the Code Editor, or an equivalent console action) that was not part of the approved spends. 0 EECU-s were spent on this step, so the global pass share p, the land tile count, the passing tile count and the actual total against the 44,439 prediction are all unmeasured.

Two facts about the planned export that matter for the 44,439 prediction:
- The 10 x 4 chunking covers the whole 5790 x 2448 grid, 14,173,920 cells (354,348 per chunk), not about 4,000,000 land cells. 44,439 was 0.0111 x 4,000,000. Ocean and polar cells were not costed by any probe; if they cost like land, a whole-grid gate export would scale to about 157,000 (Lonar rate) or 245,000 (Atacama D3 rate), not 44,000.
- Per-chunk size is about 3.5 times the 100,000 tiles per task assumed earlier.

### Updated cost table (p still unmeasured, so parametric)

Per-tile rates now available, scaled to 4,000,000 land tiles (linear, same weakness as before):

| Piece | EECU-s per tile | Total for 4,000,000 | Multiple of 540,000 |
|---|---|---|---|
| Gate layers, D3 rate (Atacama) | 0.01731 | 69,235 | 0.128 |
| Gate layers, Probe B rate (Lonar) | 0.0111 | 44,439 | 0.082 |
| Terrain 33.333 m, D1 | 0.2794 | 1,117,645 | 2.07 |
| Climate, D2 | 1.0527 | 4,210,811 | 7.80 |
| Terrain 90 m, Probe C | 0.0288 | 115,216 | 0.213 |
| Full stack as D1+D2+D3 (barren box) | 1.3494 | 5,397,691 | 10.0 |
| Full stack, Probe A (cropland box) | 1.769 | 7,077,783 | 13.1 |

Gate-first, gate layers at the D3 rate (69,235) for all tiles, then the survivor work for a share p of tiles. The survivor full-stack rate used is the D1+D2+D3 barren-box rate, since surviving tiles are barren by construction; the Probe A rate would be 31% higher.

| p | Gate + p x full stack (1.3494) | x 540,000 | Gate + p x terrain 33 m (0.2794, no climate) | x 540,000 | Gate + p x terrain 90 m (0.0288, no climate) | x 540,000 |
|---|---|---|---|---|---|---|
| 0.05 | 339,119 | 0.63 | 125,117 | 0.23 | 74,995 | 0.14 |
| 0.10 | 609,004 | 1.13 | 180,999 | 0.34 | 80,756 | 0.15 |
| 0.25 | 1,418,657 | 2.63 | 348,646 | 0.65 | 98,039 | 0.18 |
| 0.50 | 2,768,080 | 5.13 | 628,057 | 1.16 | 126,843 | 0.23 |
| Break-even, one month (540,000) | p = 0.087 | 1.00 | p = 0.42 | 1.00 | p = 4.1 (above 1, so every p fits) | n/a |
| Break-even, two months (1,080,000) | p = 0.187 | 1.00 | p = 0.90 | 1.00 | above 1, every p fits | n/a |

Notes on the table:
- With the Probe A survivor rate (1.769) and the Lonar gate rate the earlier break-evens stand: p = 0.070 for one month, 0.146 for two. The measured barren-box full-stack rate moves them to 0.087 and 0.187.
- The terrain-only columns leave climate out. Adding climate for the same survivors costs p x 4,210,811 on top (for example 1,052,703 at p = 0.25).
- The terrain 90 m column uses the Probe C rate from a cropland box; a barren-box 90 m rate was not measured.
- No pass share p was measured for the globe, so no row above is a forecast. The two boxes measured so far give p = 0% (Lonar) and p = 100% (Atacama).

### Still open

- A global or multi-biome gate map (needs the Earth Engine asset root, or a Drive route) to get a real p.
- Per-tile cost at global chunk size and for ocean and polar cells.
- A 90 m terrain rate and a climate rate on more than one box.

## Gate export via Drive: calibration (2026-11-13)

The asset route was blocked (no asset root, see above), so the gate export was switched to `ee.batch.Export.image.toDrive` (GeoTIFF, Drive folder `gsop_gate`, same grid, `CRS_WKT`, 10 x 4 chunking, 4 gate bands). Only calibration chunks were started. The other chunks were NOT started, because the extrapolated total is above the 60,000 EECU-s decision limit (see below). Raw results: `results/ee_gate_export.json` (gitignored), script `scripts/ee_gate_export.py`.

### Measured chunk costs

Each chunk is 579 x 612 = 354,348 cells of 6 km. All tasks ran as batch tasks and were polled every 60 s.

| Chunk | What it covers | Result | `batch_eecu_usage_seconds` | EECU-s per exported cell | Land share (12 km sample of the MCD12Q1 water class) |
|---|---|---|---|---|---|
| r01_c00 | 0-30N, 180W-144W, central Pacific | COMPLETED | 979.15 | 0.00276 | 0.002 |
| r01_c05 | 0-30N, 0-36E, Sahara, Sahel, northern Congo | COMPLETED | 1,305.15 | 0.00368 | 0.941 |
| r03_c05 | 30S-90S, 0-36E, Antarctica, Southern Ocean, South Africa tip (610 of 612 rows) | COMPLETED on the second attempt | 888.49 | 0.00252 | about 0.20 (estimate) |
| r00_c03 | 30N-90N, 72W-36W, Greenland, Canadian Arctic, Labrador Sea (610 of 612 rows, 3 pieces) | COMPLETED as 3 pieces on the third attempt | 3,242.83 (p0 2,432.13, p1 476.25, p2 334.45) | 0.00918 | 0.318 |
| r03_c05, first attempt (full 612 rows) | | FAILED | 91.91 | n/a | n/a |
| r00_c03, second attempt (full chunk, 610 rows) | | FAILED | not reported by Earth Engine | n/a | n/a |

- Total batch usage of the six completed tasks: 6,415.62 EECU-s. Failed attempts add 91.91 plus an unreported amount for the north failure, so the total spend so far is about 6,507 plus the unreported amount of the north failure.
- Per cell, the 354k-cell chunks cost 0.0025 to 0.0037 (ocean, Antarctic and Sahara chunks), against 0.0111 (Probe B, Lonar) and 0.0173 (D3, Atacama) for 400-tile tasks. Fixed per-task overhead dominated the small probes, as suspected. This also means the 44,439 prediction (0.0111 x 4,000,000 land tiles) overestimated the per-cell rate by about 3 to 4 times but left out ocean: the grid has 14.17M cells and the ocean chunk costs 75% of the Sahara chunk (0.00276 vs 0.00368 per cell), so ocean is not free.
- The cost is driven by latitude, not land share. The top piece of the north chunk (rows 2 to 204, from 89.8N down to about 56N) cost 2,432 EECU-s for 203 rows, which is 75% of the chunk; the two lower pieces cost 476 and 334. Equal-area cells near a pole are long N-S slivers that cover a large ground area, so each 6 km cell aggregates many 500 m source pixels.

### Two failures that change the export plan

1. South pole: the grid has 2448 rows of 6000 m, which is 3.5 km beyond the pole-to-pole extent (`2 x Y_MAX`). Row 2447 reaches past the pole, and the task failed with `(3474.0,2448.0) transformed to NaN` (91.91 EECU-s spent). Trimming 2 rows at each pole (`gee_export.POLE_TRIM_ROWS`, the last 12 km at each pole) fixed it. These 2 x 5790 cells per pole are polar ice or Arctic Ocean and are not exported. `start_global_export` (the full stack, not started) uses the same untrimmed regions, so its row 3 chunks will almost certainly fail the same way.
2. North: the whole chunk r00_c03 failed with `Reprojection output too large (9818x8284 pixels)`, although every third of it ran fine as an interactive reduction. Exporting the top row of chunks in 3 pieces each (`gee_export.ROW0_SPLIT`, pieces `<chunk>_p0` to `_p2`) worked for this chunk. It is not known whether the other 9 chunks of row 0 behave the same; only r00_c03 was tested. The same split may be needed for other chunks reaching high latitudes in the south (r03 chunks other than c05 were not tested).

### Extrapolation to the full grid (40 chunks, 60 tasks)

Three simple models over the four measured chunks (land share from the sampled water mask, used only to describe the mix):

| Model | Assumption | Total for 40 chunks | Multiple of 540,000 |
|---|---|---|---|
| Land-share fit | per-chunk cost = 1,534 + 191 x land share (fitted, 4 points, weak) | 63,916 | 0.118 |
| Mean x 40 | every chunk costs the mean of the four measured (1,604) | 64,156 | 0.119 |
| Max x 40 (upper bound) | every chunk costs like the north chunk (3,243) | 129,713 | 0.240 |
| Lower reading | rows 1 to 3 like the three cheap chunks (about 1,057 each, 30 chunks) plus 10 north chunks like r00_c03 (3,243) | 64,100 | 0.119 |

The two plausible readings agree at about 64,000 EECU-s. Above 60,000 means the decision rule stopped the run. Row 0 (30N to 90N) alone is about half of it (about 32,000 if every top chunk costs like the Greenland one, which is probably high for chunks over open ocean or Siberia, and unmeasured).

### What was not started and a land-only variant

- 34 of the 40 chunks were never started (all except the four measured; r00_c03 counts as one chunk in 3 pieces). Nothing was cancelled.
- Land-only variant, using the sampled land share: the chunks under 2% land are r01_c00 (measured), r01_c09, r02_c00, r02_c01 and r02_c04 (central and eastern Pacific, South Atlantic). Skipping those five chunks removes about 4,900 to 7,100 EECU-s (979 each if they cost like the measured ocean chunk, the fitted 1,534 for the four unmeasured ones), giving an estimated 56,800 to 59,000 EECU-s in total. That is below 60,000 but with little margin, and the polar row 0 is the main uncertainty. The tiles in the skipped chunks are ocean, so they have no land tiles to pass or fail.
- Trimming further at the poles would cut the dominant cost (the top 200 rows of row 0 cost 2,432 of the 3,243). Cells poleward of 85.04 degrees (the standard EASE-Grid 2.0 limit, 5 rows at each pole) are polar ice and are gated out anyway per `gsop.grid`, but the cost per row in the top 203 rows was not resolved, so the saving is unknown.

### Drive files completed (folder `gsop_gate`)

- `gate_6km_r01_c00.tif`, `gate_6km_r01_c05.tif`, `gate_6km_r03_c05.tif` (rows 1836 to 2445 only)
- `gate_6km_r00_c03_p0.tif`, `gate_6km_r00_c03_p1.tif`, `gate_6km_r00_c03_p2.tif` (rows 2 to 611 in three pieces)
- All four-band float32 GeoTIFFs of about 5 MB each at 6 km. They were not read back because no route to the Drive files exists in this session. The pass share p was therefore not computed. After downloading the folder, run `uv run python scripts/ee_gate_stats.py PATH_TO_FOLDER`. It prints land tiles (land_frac >= 0.5), passing tiles and p. It was tested on the Atacama D3 box (420 cells in the download, 400 finite, 400 land, 400 passing, p = 1.0, as measured before). Four chunks are not a global p.

## Global gate export run (snapshot 2026-11-13, about 23:50 IST)

The user approved running the remaining chunks. The run is NOT finished at this snapshot. Settings: Drive folder `gsop_gate`, 2 pole rows trimmed, top chunk row split in 3 pieces for every top-row chunk (`ROW0_SPLIT`), one retry per failed chunk with the failed pieces split in two, safety stop at 62,000 EECU-s for this run (not fired), polling every 60 s, at most 6 unfinished tasks submitted at a time. Raw results: `results/ee_gate_export.json` (gitignored).

### Why it is not finished

- Earth Engine ran only 2 of this project's tasks at a time. Over about 4.5 hours the run completed 22 tasks, roughly 5,000 to 6,000 EECU-s per hour.
- Since about 23:08 none of the gate tasks has run: the project queue holds about 250 `terrain90_*` tasks queued by another job, and they are served ahead of the 6 queued gate tasks. The gate run is waiting, not failing.
- The first polling process reached its 180 minute cap at 22:03 and was restarted once (second 180 minute window, to about 01:03). Queued gate tasks remain queued and nothing was cancelled. To resume: `uv run python scripts/ee_gate_export.py --rest` (continues from the saved queue, retries only once per chunk).

### Measured so far (completed tasks)

Piece rows are rows of the 6 km grid (row 0 is the north pole, each chunk row has 612 rows, 2 trimmed at each pole).

| Chunk | Completed pieces | EECU-s | Notes |
|---|---|---|---|
| r00_c00 | 3 (rows 104 to 612) | 2,629 | rows 2 to 103 (89.8N to about 66N) GAVE UP: too large twice (21623x7267, then 15125x4908 pixels) |
| r00_c01 | 4 | 6,743 | first piece split in two: rows 2 to 103 alone cost 3,213 |
| r00_c02 | 4 | 5,333 | first piece split in two: rows 2 to 103 alone cost 1,902 |
| r00_c03 | 3 | 3,243 | from the calibration |
| r00_c04 | 3 | 1,510 | |
| r00_c05 | 3 | 2,544 | |
| r00_c06 | 3 | 5,455 | |
| r00_c07 | 2 of 4 (rows 205 to 612) | 2,902 | first piece failed once, its two halves are queued |
| r01_c00 | 1 | 979 | from the calibration |
| r01_c05 | 1 | 1,305 | from the calibration |
| r03_c05 | 1 (610 rows) | 888 | from the calibration |

- Completed tasks: 33,532 EECU-s over 28 tasks (11 chunks complete or partly complete). Failed attempts add 91.9 for the first r03_c05 try; the other failures (all "Reprojection output too large") report no EECU. All failed attempts, 7 in total: r00_c00 p0, r00_c00 p0_s0, r00_c01 p0, r00_c02 p0, r00_c03 (whole), r00_c07 p0, and r03_c05 (pole overreach).
- For this run alone (everything except the 6,415.6 of the calibration tasks): 27,116.3 EECU-s.
- Top-row chunks are 4 to 10 times more expensive than mid-latitude ones: 1,510 to 6,743 EECU-s each, against 979 to 1,305 measured for rows 1 to 3. The first 100 rows from the pole (89.8N to about 66N) fail, or cost about 1,900 to 3,200 EECU-s per 100 rows in chunks c01 and c02. The "too large" error always hit the first (polar) piece; splitting it into two halves worked for c01, c02 and the lower half of c00, not for the polar half of c00; the retry of c07 is still queued.

### Forecast for the 40 chunks (not measured)

- Seven top-row chunks (c00 to c06) are complete apart from the given-up piece and average 3,920 EECU-s each; c07 is half done, c08 and c09 are queued. Ten top-row chunks at that average are about 39,000.
- Rows 1 to 3 (30 chunks, 3 measured at 888 to 1,305, about 1,060 on average): about 32,000 for 30.
- All 40 chunks: about 70,000 EECU-s, against the earlier 44,439 prediction and the 64,000 estimate. The 62,000 EECU-s limit for this run (about 70,000 minus 6,416 of calibration tasks = 63,600) would stop the last chunks.

### Drive files completed in `gsop_gate` at this snapshot

28 GeoTIFFs:
`gate_6km_r01_c00`, `gate_6km_r01_c05`, `gate_6km_r03_c05`, `gate_6km_r00_c00_p0_s1`, `_p1`, `_p2`, `gate_6km_r00_c01_p0_s0`, `_p0_s1`, `_p1`, `_p2`, `gate_6km_r00_c02_p0_s0`, `_p0_s1`, `_p1`, `_p2`, `gate_6km_r00_c03_p0`, `_p1`, `_p2`, `gate_6km_r00_c04_p0`, `_p1`, `_p2`, `gate_6km_r00_c05_p0`, `_p1`, `_p2`, `gate_6km_r00_c06_p0`, `_p1`, `_p2`, `gate_6km_r00_c07_p1`, `_p2`. The current list is the `tasks` entries with state COMPLETED in `results/ee_gate_export.json`.

Missing at this snapshot: r00_c00 rows 2 to 103 (given up), r00_c07 rows 2 to 204 (retry queued), r00_c08 (3 pieces queued), r00_c09 (3 pieces, 1 submitted), and the 26 chunks of rows 1 to 3 that were never submitted (only r01_c00, r01_c05 and r03_c05 done).

The pass share p was not computed (no read route to Drive). Download the folder and run `uv run python scripts/ee_gate_stats.py PATH` for the files present.

## Terrain on survivors and cheap climate bands (2026-11-13)

Measured by `scripts/ee_terrain_probe.py` (raw results in `results/ee_terrain_probe.json`, gitignored), branch `ee-terrain-probe`. Same route as Probes A to D: 400-tile boxes (60 km half-width), `chunk_region`, `CRS_WKT`, `Export.image.toDrive` (GeoTIFF, maxPixels 1e10), Drive folder `gsop_probe`. All probes ran as batch tasks. They sat READY in the project's FIFO queue behind the gate-export tasks for 69 to 75 minutes before starting, which is not counted in the run times below. Total spend of these 9 probes: 903.9 EECU-s. The monthly quota (540,000 EECU-s) is the only quota number used.

### Does masking terrain to gate-passing tiles lower the batch cost? Not enough.

`terrain_bands(tile_mask=gate_pass_mask())`: the DEM is masked with the 6 km gate-pass image (ndvi_median <= 0.2, water_ice_frac <= 0.5, built_crop_frac <= 0.2, from `landcover_bands()`) with `updateMask` right after the first aggregation, before every reduction. Terrain at the default 33.333 m, 6 bands.

| Probe | Box (tiles passing) | Task id | Run time | `batch_eecu_usage_seconds` | EECU-s per tile (400) |
|---|---|---|---|---|---|
| 1a terrain unmasked | Lonar (0 of 400) | PAGQLVRRKVGDLVEZ72JN6ABO | 105 s | 167.33 | 0.4183 |
| 1b terrain masked | Lonar (0 of 400) | T33NH6FFLGEK6G6MOHGJ275Y | 95 s | 83.97 | 0.2099 |
| 2 terrain masked | Atacama (400 of 400) | 6AK2SCJYQAA5TAY6DVHAFE63 | 153 s | 226.71 | 0.5668 |
| D1 (earlier) terrain unmasked | Atacama | XQJIIGK747M3ODO4OSSOKLGR | 133 s | 111.76 | 0.2794 |

- Masking removes only about half of the Lonar cost (83.97 of 167.33) although 0 of 400 tiles pass. A floor of 0.21 EECU-s per tile remains for tiles that are masked out.
- Where everything passes (Atacama) the masked task costs 2.03 times the unmasked one (226.71 vs 111.76). The mask itself is expensive: a 6 km image evaluated on a 33 m grid recomputes the gate layers per 33 m output tile. Earth Engine does not skip the DEM work for masked tiles.
- Two boxes, so only an indicative line: masked cost per tile is about 0.2099 + 0.3569 x p, with p the share of tiles passing. Over 4,000,000 land tiles that is 839,700 at p = 0, 911,100 at p = 0.05, 982,500 at p = 0.10, 1,196,600 at p = 0.25, 2,267,000 at p = 1. Even at p = 0 it is 1.55 times the whole monthly quota. Masking is not a way to afford 33 m terrain globally. p is still unmeasured for the globe.
- The unmasked 33 m rate differs by box: 0.2794 (barren Atacama) and 0.4183 (Lonar). Terrain cost depends on the box, so every extrapolation here carries that spread.

### Fallback: terrain only for regions that contain survivors

Masking does not work, so `src/gsop/earth/terrain_plan.py` and `scripts/ee_terrain_plan.py` plan the export region by region (offline, no Earth Engine call, nothing exported):

1. Read the gate GeoTIFFs (the `ee_gate_stats.py` rule: four finite bands, land_frac >= 0.5, the three gates) and convert every surviving tile to its global (ix, iy).
2. Group survivors into 10 x 10 cell blocks (60 km) and keep the occupied blocks.
3. Merge: first zero-waste (joining blocks with equal spans), then repeatedly merge the pairs of rectangles that add the least empty area (8 nearest neighbours per round), up to 60 cells per side while possible, until at most 150 regions remain. If 150 cannot be reached under the side limit, the limit is dropped (region count wins over size).
4. Shrink each region to the bounding box of the survivors inside it.
5. `gee_export.start_terrain_export(regions)` builds one terrain task per region (`start=False` by default). It was not started.

Tests (`tests/test_terrain_plan.py`): Atacama gate output (400 survivors) gives 1 region of 20 x 20 cells, waste factor 1.0; Lonar gate output (0 survivors) gives 0 regions; a clustered random set of 400 clusters is merged to at most 150 regions covering every survivor. The gate output for the four finished global chunks was not available locally.

The waste factor w (exported cells per surviving tile) depends on how clustered the survivors are, which is unknown. A synthetic check (random Gaussian fields of 1200 x 1200 cells, not real data): fields with a correlation length of 15 cells gave w of 1.3 to 1.8 at p = 0.05 to 0.25; correlation length 4 gave w of 4.8 to 13.6; uncorrelated survivors gave w of 4 to 20, meaning the whole area gets exported. Real deserts are large patches, so the low end is plausible, but that is an assumption.

Cost with this fallback at the unmasked Atacama rate (0.2794, barren like the survivors), 4,000,000 land tiles, gate cost not included:

| p | w = 1.0 | w = 1.5 | w = 3.0 |
|---|---|---|---|
| 0.05 | 55,880 | 83,820 | 167,640 |
| 0.10 | 111,760 | 167,640 | 335,280 |
| 0.25 | 279,400 | 419,100 | 838,200 |
| 0.50 | 558,800 | 838,200 | 1,676,400 |

About 464,000 EECU-s remain in the month after the gate export (about 64,000) and the 12,000 already used, so 33 m terrain on survivors alone fits when p x w is at most about 0.415. p is not known yet.

### Climate bands one at a time (Atacama box)

Each probe is `climate_bands().select(...)` (water_index through the new `water_index_band()`), one batch task per band.

| Band | Task id | Run time | `batch_eecu_usage_seconds` | EECU-s per tile | Share of the sum |
|---|---|---|---|---|---|
| t_mean | 2GJ3LLUVR46D6SPEK3QKXT6Q | 60 s | 19.21 | 0.0480 | 4.5% |
| t_coldest | 4LLW5B4ZGK2VSOKJN7UYMYA2 | 49 s | 17.41 | 0.0435 | 4.1% |
| ti_proxy (with ti_is_fallback) | YWFGQEFZRGXWHC2MTCWJVXIS | 71 s | 40.73 | 0.1018 | 9.6% |
| dust_index | CA2HAX3HDNJKIEJ65KGIE4FQ | 351 s | 336.04 | 0.8401 | 78.9% |
| water_index (`water_index_band()`) | YBAFZLVFUFWLRZUJXBLVSUX2 | 18 s | 10.54 | 0.0263 | 2.5% |
| silica_index | 3SEW4K4ZQPGRSC2EIQFMD2AL | 9 s | 1.94 | 0.0048 | 0.5% |
| Sum of the six probes | | | 425.87 | 1.0647 | 100% |
| D2 `climate_bands()` all in one (earlier) | UNZY3HINZJ45PAVL6EJLIFK4 | 507 s | 421.08 | 1.0527 | |

- The bands are almost additive (425.87 against 421.08), so single-band selection is pruned by Earth Engine and the singles are a fair split.
- `dust_index` (MERRA-2 `DUEXTTAU`, ten years of 3-hourly images) is 79% of the climate cost. The other five bands together cost 89.83 per 400 tiles (0.2246 per tile), 4.7 times less than the full climate set.
- Climate without dust_index over 4,000,000 land tiles: 898,300. With dust_index: 4,258,700. On survivors only (p x w = 0.1): 89,800 and 425,900. A cheaper dust_index (a few years instead of ten, since cost follows the image count) was not tested.
- water_index alone: 0.0263 per tile, 105,300 EECU-s for 4,000,000 tiles, 10.5 on this box. It is cheap enough to run for all tiles, not only survivors.

### Recommendation for the cheapest plan

- Do not mask terrain. Masking halves the cost at best and doubles it at worst.
- Keep 33 m terrain only if survivors are few and clustered: export terrain per survivor region (`terrain_plan.py`). Fits when p x w <= 0.415 at the barren rate with nothing else spent. Needs the gate output for all chunks first.
- Drop dust_index from the survivor run, or cost a shorter MERRA window first. The other five climate bands plus water_index are cheap.
- If p x w is large or unknown by the cutoff, the 90 m terrain route (next section) is the only measured-affordable global terrain.

## Global 90 m terrain export (2026-11-13, queued, not yet measured)

User decision: queue terrain at 90 m globally because 33 m terrain on survivors cannot finish in time. No chunk cost is measured yet: all tasks sit in the project FIFO queue behind the gate-export tasks (gate finish about 03:30 IST on 2026-11-14). Calibration costs will be in `results/ee_terrain90_state.json` (`eecu`, `start_ms`, `update_ms` per task) once the first two tasks run.

- Configuration: `terrain_bands(100.0, "srtm90", (3, 10))` (the Probe C configuration): `CGIAR/SRTM90_V4` (92.8 m nominal) averaged to a 100 m working grid, slope baseline 500 m, tile 6 km, roughness windows 3 and 10 cells = 300 m and 1000 m. Bands: slope_med, slope_p90, relief, elev_mean, rough_a, rough_b. Masked cells are written as -9999 (the image is unmasked before export). Same CRS_WKT, 6 km grid and alignment as the gate export. Drive folder `gsop_terrain90`, files `terrain90_r<row>_c<col>.tif`.
- Latitude limit: SRTM90 has no data above 60N or below 56S. The export covers grid rows 164 to 2237 (60.06N to 56.06S, one margin row each side). Tiles outside this band have no terrain from this export.
- Chunks: 200 x 200 cells (at most 40,000 tiles; the largest is 37,800), 11 x 29 = 319 planned, 91 skipped because the coarse SRTM mask (5 km sampling, interactive, no batch cost) found no data (open ocean), 228 submitted. Islands smaller than about 5 km inside an all-ocean chunk would be lost. Calibration chunks submitted first: `terrain90_r02_c15` (Sahara, flat, all land) and `terrain90_r02_c21` (Himalaya, mountainous).
- Planned tiles in the 228 chunks: 8,589,440, including the ocean parts of coastal chunks.
- Monitor: `scripts/ee_terrain90_export.py poll` (detached, every 90 s, 4 h cap). It stops the stage and cancels its queued tasks when the finished tasks of the stage pass 130,000 EECU-s, or when more than 20% of chunks fail after one retry (an error with "too large" or "memory" splits the chunk in two). Running tasks are never cancelled.
- Extrapolation (unmeasured): the per-tile rate is only known from Probe C (0.0288 on a 400-tile box, inflated by task overhead, as the gate chunks showed: 0.0111 and 0.0173 for 400 tiles against 0.0025 to 0.0037 per cell at chunk size). A plausible range is 0.008 to 0.0288 per tile, so 69,000 to 247,000 EECU-s for 8,589,440 tiles. The upper end passes the 130,000 stop. At about 7,000 EECU-s per hour after the gate tasks finish, 69,000 takes about 10 hours (finish near 13:30 IST Saturday), 130,000 about 18.6 hours (finish near 22:00 Saturday). The empty ocean parts of coastal chunks probably cost less than land, so the true figure is likely toward the lower end; this is a guess, not a measurement.
- Compared with Probe C: 90 m terrain differs from the 33 m route (no 100 m roughness window: rough_a is 300 m everywhere), and the 100 m grid is resampled from a 92.8 m DEM. The Moon and Mars target rough_a must be recomputed at 300 m to be comparable.
- Tools: `scripts/ee_terrain90_stats.py FOLDER [--ref PROBE_C.tif]` lists chunks, bands and the invalid share per band (NaN, nodata tag or -9999), and compares slope_med to a Probe C GeoTIFF cell by cell. Offline tests: `tests/test_terrain90_plan.py`.

## High-latitude terrain on Copernicus GLO30 (2026-11-13, queued, not yet measured)

User decision: add a DEM for the latitudes SRTM90 does not cover, so that Haughton, Samoylov, the McMurdo Dry Valleys and Askja can be scored.

- `terrain_bands(100.0, "glo30", (3, 10))`: `COPERNICUS/DEM/GLO30_2024_1` band DEM, mosaic, block-averaged (mean) to the 100 m grid after `setDefaultProjection`, then the same downstream operator and the same six bands (500 m slope baseline, windows of 3 and 10 cells = 300 m and 1000 m, 6 km tile). reduceResolution `maxPixels` is 1024 because GLO30 pixels shrink in longitude with latitude, so a 100 m cell holds 40 to 90 source pixels at 75 to 83 degrees. Drive folder `gsop_terrain90_hi`.
- Vertical datum: GLO30 is referenced to EGM2008, SRTM and NASADEM to EGM96. Only slope, relief and roughness are used, never absolute heights (elev_mean is the one exception: it differs from the SRTM value by the geoid difference, a few metres at most, and is not used for ranking terrain roughness).
- Smoke test (interactive, 60 km boxes, no batch cost): Haughton median slope_med 1.72 degrees, slope_p90 5.57, relief 214 m; McMurdo Dry Valleys 12.17, 30.6, 1064 m. No masked cells in either box.
- Stage 1 (4 tasks, tag `terrain90_stage1_<site>`): boxes of 100 x 100 cells (10,000 tiles, 360,000 km2 since cells are equal area) around haughton (75.37N, 89.68W), samoylov (72.37N, 126.48E), mcmurdo_dry_valleys (77.5S, 162.0E), askja (65.03N, 16.75W), coordinates from `config/known_sites.yaml` on the targets-moon-mars branch. Boxes that reach a pole edge are shifted, not shrunk. Safety cap 15,000 EECU-s of finished stage-1 tasks.
- Stage 2 (95 tasks, tag `terrain90_stage2_r<row>_c<col>`): land from 60N to 83N, chunks of at most 120 x 80 cells (9,282 tiles at most), 98 planned. Greenland is excluded by the country polygon in `USDOS/LSIB_SIMPLE/2017` (`country_na` = Greenland, Iceland stays), evaluated server side on the 5 km coarse reduction with no raster export cost: chunks with less than 1.5% data outside Greenland were dropped (3 chunks: one ocean, two Greenland-only). Chunks that straddle Greenland are exported whole, so some Greenland terrain is still computed. Nothing in Antarctica beyond the McMurdo box. The masking probe showed that masking by a gate-style mask does not lower cost, so no permanent-ice mask is used. Planned tiles: 869,604. Safety cap 60,000 EECU-s of finished stage-2 tasks, after which queued stage-2 tasks are cancelled.
- Queue order: SRTM90 band (228 tasks), then stage 1 (4), then stage 2 (95). All submitted up front.
- Cost per tile for GLO30 at 100 m is not measured. Rough guess from the source pixel count (40 to 90 per cell against about 1 for SRTM90): 0.03 to 0.15 per tile, so 1,200 to 6,000 EECU-s for stage 1 and 26,000 to 130,000 for stage 2 (the cap cuts it at 60,000). This guess is unmeasured; the stage-1 first box (`terrain90_stage1_haughton`) will give the first real number.
- Stage 2 is allowed to stay unfinished at the cutoff (end of Saturday 2026-11-14). The plan is to use only stage-2 chunks that completed in time, and to say which latitudes are missing. Stage 2 runs last, behind the SRTM90 tasks, so it will most likely not finish by the cutoff unless the SRTM90 band is cheaper than the lower estimate above.
- Geometry caveat for all three terrain routes: the 6 km grid is EPSG:6933 (cylindrical equal-area, true scale at 30 degrees). Away from 30 degrees a projected metre is not a ground metre: at 60N the 500 m slope baseline is 289 m east-west and 866 m north-south on the ground, and at 75N 149 m and 1,673 m. The operator divides by 500 m in both directions, so slopes and roughness computed at high latitudes are anisotropic and scaled by latitude. This applies to the SRTM90 band above 30 degrees too, and to the 33 m route. It is not corrected here.


## Terrain export fix: source footprint limit and adaptive chunks (2026-11-14)

The SRTM90 chunks of 200 x 200 cells and the four stage-1 boxes failed in batch (145 tasks FAILED, including both calibration chunks and all four boxes, with no EECU-s reported; the other 546 were cancelled by the coordinator at 23:55 so the gate export could run). The state of 2026-11-13 is kept in `results/ee_terrain90_state_stale_*.json` (gitignored).

### Diagnosis

- Error text: `Reprojection output too large (14939x10791 pixels)` for the SRTM chunks (14939 x 12175 for both calibration chunks), 22650 x 40779 to 22426 x 74702 for the GLO30 boxes. One chunk gave `Number of pixels requested from Image.setDefaultProjection exceeds the maximum allowed (2^31)`.
- The reported size is the footprint of the region in the SOURCE lattice (3 arc second, 92.77 m). A region of w x h cells of 6 km spans 74.7 x w pixels east-west (independent of latitude, because x = R cos(30 deg) x longitude) and 56 x h / cos(lat) north-south. The footprint is therefore `4,183 / cos(lat)` source pixels per 6 km tile, whatever the shape.
- Interactive reduction of the same graph over a region (`reduceRegion` with the export grid) reproduces the error at once and gives the threshold: 60 x 60 tiles passed at lat 0 and 55; 100 x 100 at lat 55 failed (7551 x 9065 = 68.5M pixels); 140 x 140 at lat 0 failed (10536 x 7986 = 84M). All failures seen are above 2^26 = 67.1M pixels, all passes below, so the limit is taken as `FOOTPRINT_PX_LIMIT = 2^26`. (Interactive runs also hit unrelated "Object too large" and "User memory limit" errors for 100 x 100 tiles at 0 to 55 degrees, so interactive tests cannot find the batch maximum above the limit.)
- The earlier first chunk size of 40,000 tiles was 9 times the allowed footprint at the equator and 16 times at 55N.
- GLO30: the mosaic was read on the 1 arc second lattice of its first tile, which gives 92,000 source pixels per tile at 65N and only about 400 tiles per task. `dem("glo30")` now sets the default projection to a 3 arc second lattice (about 92.8 m, the SRTM90 resolution; Earth Engine reads a coarser pyramid level, so this is close to a 3 x 3 block mean before the average to 100 m). The "Too many input pixels per output pixel. Need 401, but only 4..." message reported for the stage-1 boxes was not seen again in the task list; the batch errors of those boxes were all footprint errors. A related error, `Need 401, but only 400 allowed`, did appear on four size-test tasks (110, 130 tiles at lat 0; 90, 100 at lat 55): the 400-pixel limit of the 6 km median of rough_a (a 20 x 20 block of 300 m cells) was exceeded by one pixel on regions that are not the calibration chunks. `_agg` now allows 25 percent plus 2 pixels more than asked, which changes no output value. Not yet confirmed on a rerun.

### Adaptive chunks

`gee_export.adaptive_chunks`: row bands of near-square chunks with at most `0.6 x 2^26 x cos(lat_poleward_edge) / 4,183` tiles (about 9,600 at the equator, 8,300 at 30 degrees, 5,500 at 55, 4,800 at 60, 4,500 at 61). `0.6` is the margin below the measured limit. Tasks: SRTM band 1,557 planned, 748 all-ocean skipped, 809 submitted (6,307,137 planned tiles, including ocean parts of coastal chunks); stage 1 27 tasks (100 x 100 cells per box, 4 to 9 pieces each, boxes kept equatorward of about 83 degrees); stage 2 321 tasks of 396 planned (786,766 tiles); 4 size-test tasks. Offline tests in `tests/test_terrain90_plan.py`.

### Calibration (measured)

| Chunk | What | Tiles | `batch_eecu_usage_seconds` | Run time | EECU-s per tile |
|---|---|---|---|---|---|
| terrain90_r05_c47 | Sahara, flat, all land (cells 4230, 557, 90 x 89) | 8,010 | 411.56 | 296 s | 0.0514 |
| terrain90_r06_c33 | Himalaya, mountainous (cells 3036, 646, 92 x 92) | 8,464 | 357.34 | 230 s | 0.0422 |

- Mean 0.0468 per tile (the mountain chunk is cheaper than the flat one; two chunks only). That is 1.6 to 6 times the guess made before measuring (0.008 to 0.0288), so the earlier 69,000 to 247,000 range was too low.
- Extrapolation for the SRTM band: 6,307,137 planned tiles x 0.0468 = 295,000 EECU-s if ocean parts of coastal chunks cost as much as land; land tiles alone (about 3.5M of the band) would be about 164,000. Either figure is above the 130,000 stop of the monitor, so the SRTM band will most likely be stopped at 130,000, which is about 2.8M tiles or 40 to 80 percent of the land, depending on how much of the finished work is ocean. This is an extrapolation from two chunks at similar cos(lat) (the Himalaya chunk is at 30N, the Sahara one at 25N); chunks at 50 to 60N have fewer tiles per task, so more tasks, with similar cost per tile.
- Wall time: two tasks run at once; each task ran about 1.4 EECU-s per second (412 in 296 s, 357 in 230 s), so about 9,900 EECU-s per hour for two slots, against the 7,000 assumed. 130,000 EECU-s takes 13 hours at 9,900 per hour and 18.6 hours at 7,000 per hour. The queue started the first terrain task at 03:05 IST on 2026-11-14 behind the last gate tasks.
- GLO30 at 100 m (first stage-1 piece, `terrain90_stage1_haughton_r00_c00`, 25 x 29 = 725 tiles at 77 to 85N): 107.9 EECU-s in 196 s, 0.149 per tile. A task this small is dominated by overhead, so larger stage-2 chunks (up to 4,554 tiles) should be cheaper per tile; one piece only. At 0.149 per tile stage 1 (40,000 tiles) would be about 6,000 EECU-s and stage 2 (786,766 tiles) about 117,000, which the 60,000 cap would cut. Use this as an upper estimate until more GLO30 pieces finish.
- Because the SRTM band takes the first 130,000 EECU-s, stage 1 and stage 2 run last in the queue order of `ee_terrain90_export.py start` only if the SRTM band is stopped or complete. Order submitted: 2 calibration chunks, 4 size tests, stage 1, SRTM band, stage 2.

### Handling and monitor

- One detached poller: `scripts/ee_terrain90_export.py poll` (every 90 s, 30 h cap, state `results/ee_terrain90_state.json`). `resubmit` cancels READY and failed-once tasks and resubmits them after a code fix; `reorder` moves stage 1 ahead of the SRTM band; `start` backs up the old state and submits everything.
- Caps and the failure rule are unchanged: srtm 130,000, stage1 15,000, stage2 60,000 (size tests 3,000), more than 20 percent of chunks failed after retry stops the stage. A failure whose text contains "too large" or "memory" is retried in two halves, any other failure is retried once unchanged.
