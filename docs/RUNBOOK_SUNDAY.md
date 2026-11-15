# Runbook: Moon results by Sun 2026-11-15 09:00 IST

PowerShell, one command per line. Every path is absolute, so the commands work from any folder once `$W` is set.

## 0. Where to run

The `integrate` branch is checked out in a scratch worktree. Move it to a stable place once (this only moves the folder, the branch and commits stay):

    git -C C:\Users\lenovo\sim worktree move C:\Users\lenovo\AppData\Local\Temp\claude\9e40d91707d31236\78d9b3f7-9aef-44d2-a11f-6dc40658b4c7\scratchpad\sim-integrate C:\Users\lenovo\sim-integrate
    $W = "C:\Users\lenovo\sim-integrate"
    $R = "C:\Users\lenovo\sim\data\raw"
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine")+";"+[System.Environment]::GetEnvironmentVariable("Path","User")
    cd $W

Leave `C:\Users\lenovo\sim` on phase2-gee while the Earth Engine pollers run there. If the move fails (a file is open), skip it and set `$W` to the scratch path above.

## 1. Download from Google Drive

Download each Drive folder as a zip and extract it so the GeoTIFFs end up here (a sub-folder level is fine, the assembler searches recursively):

| Drive folder | Extract to | Files |
|---|---|---|
| `gsop_gate` | `C:\Users\lenovo\sim\data\raw\gate_full\gsop_gate\` (the complete set of 64 files) | `gate_6km_r??_c??[_p?][_s?].tif` |
| `gsop_terrain90` | `C:\Users\lenovo\sim\data\raw\terrain90\gsop_terrain90\` | `terrain90_r??_c??[_r?].tif` |
| `gsop_terrain90_hi` | `C:\Users\lenovo\sim\data\raw\terrain90_hi\gsop_terrain90_hi\` | `terrain90_stage1_*.tif`, `terrain90_stage2_*.tif` |

- New zips from Drive can be extracted over the old folders. Duplicate files (`name (1).tif`) and split retries (`_r0`, `_r1`) are handled; two files that disagree on a tile stop the build with both names (send me that line).
- Gate coverage decides which tiles exist at all: a tile whose gate file is missing is not in the table. Terrain coverage decides which tiles can score: a land tile without terrain is rejected as `missing_data`.

## 2. Target profiles

`targets_moon.parquet` must be in `$W\data\processed\`. It is there already in the integrate worktree. If not:

    Copy-Item C:\Users\lenovo\AppData\Local\Temp\claude\9e40d91707d31236\78d9b3f7-9aef-44d2-a11f-6dc40658b4c7\scratchpad\sim-pr14\data\processed\targets_moon.parquet $W\data\processed\

## 3. Assemble the Earth table

    uv run gsop s2 assemble --gate "$R\gate_full\gsop_gate" --terrain "$R\terrain90\gsop_terrain90" --terrain-hi "$R\terrain90_hi\gsop_terrain90_hi"

- Takes about 15 to 30 s. Writes `$W\data\processed\earth_features_6km.parquet`, `grid.json`, `earth_coverage.json` and `MANIFEST.json`, and prints the coverage report (gate share of the grid, land tiles, tiles per terrain source, land tiles with and without terrain).
- On the partial downloads of Saturday 08:00 (48 gate, 219 SRTM, 27 GLO30 files): 2,812,694 land tiles, 910,977 (32.4%) with terrain. With the complete gate set (64 files, Saturday afternoon): 3,972,955 land tiles, still 910,977 (22.9%) with terrain until more terrain is downloaded.
- Re-run this step after every new download; it always rebuilds from the folders.

## 4. Check the data

    uv run gsop verify-data

Must print `[PASS] data/processed matches MANIFEST.json`.

## 5. Run the Moon (2,000 runs)

Move the smoke-test results out of the way first, so nothing old is mixed in:

    if (Test-Path $W\results\moon) { Rename-Item $W\results\moon ("moon_old_" + (Get-Date -Format HHmm)) }
    uv run gsop run --body moon --runs 2000

- Jobs: 2 targets (connecting_ridge_c1, shackleton_rim) x 3 profiles (base, landing_mobility, power_night). `ice_resources` is skipped on purpose (E19); the run says so.
- Time: the 50-run smoke test on 4.0M land tiles (0.9M with terrain) took 53 s on this machine (16 cores). Monte Carlo scales with runs and with the tiles that pass the gates, so 2,000 runs with full terrain is roughly 1 hour. Close other heavy programs: free RAM was 3.3 GB during an earlier smoke test.
- A `WARNING: 10 known-site coordinates are unconfirmed` line is expected; validation stays `provisional`.
- Validation follows the amended criteria (E28 and E30, SPEC section 10, Moon criteria sha256 `6bdaaf3a...`): a site whose every tile fails a land-cover gate is `gated_out` and left out of the median, with an informational `ungated_terrain_only` score. For the Moon expect Lonar `gated_out` (vegetated), so only Haughton is scorable and the primary criterion is `not_testable`. Negative controls for the Moon: amazon_basin and congo_basin (rainforest, `gated_out`) and the sand seas rub_al_khali and namib_sand_sea (E30), which pass the gates and decide the controls criterion once their terrain chunks (terrain90_r07_c39, terrain90_r17_c33) are downloaded; until then they show `no_gated_tile` and the criterion stays `not_testable`. Gate tests must all be rejected.
- Every output carries `slope_ground_scale_corrected: false` (E29, SPEC section 3f).

## 6. Run the Moon latitude-band robustness run (2,000 runs)

    if (Test-Path $W\results\moon_lat20-40) { Rename-Item $W\results\moon_lat20-40 ("moon_lat20-40_old_" + (Get-Date -Format HHmm)) }
    uv run gsop run --body moon --runs 2000 --lat-band 20 40

- Scores only Earth tiles with absolute latitude 20 to 40 deg (inclusive), where the uncorrected slope is within about 1.5 deg for a 10 deg slope. Not a gate. Results go to `$W\results\moon_lat20-40\`; run_meta.json and export/index.json carry `lat_band_abs_deg: [20, 40]`. About a third of the land tiles, so it is faster than step 5.

## 7. Compare the two runs

    uv run python $W\scripts\compare_runs.py $W\results\moon $W\results\moon_lat20-40

- Prints per target and profile the Jaccard overlap of the top 1 percent and of the robust sets, raw and "in band" (full run restricted to the band; the raw value is small by construction because the band run has about a sixth of the gated tiles), and how many of the full run's top-20 robust tiles lie outside the band (the band run cannot check them). Writes `$W\results\moon_lat20-40\compare_with_full.json`.
- Smoke test (50 runs, partial terrain): in-band Jaccard 0.55 to 0.87 for the top 1 percent and 0.77 to 0.85 for the robust sets; 15 to 20 of each job's top-20 robust tiles lie outside the band.

## 8. Where the outputs land

- `$W\results\moon\export\` : the deliverable (index.json, fidelity.json, validation.json, candidates and convergence per job, MANIFEST.json).
- `$W\results\moon\validation.json`, `$W\results\moon\run_meta.json`, `$W\results\moon\<target>__<profile>\` (scores, Monte Carlo summary, ML).
- `$W\results\moon_lat20-40\` : the same for the band run, plus `compare_with_full.json`.
- `$W\data\processed\earth_coverage.json` : what Earth data the run had.

## 9. Zip and send

Two zips, because both runs have a folder called `export`:

    Compress-Archive -Force -DestinationPath C:\Users\lenovo\Desktop\gsop_moon_full.zip -Path $W\results\moon\export, $W\results\moon\validation.json, $W\results\moon\run_meta.json, $W\data\processed\earth_coverage.json, $W\data\processed\grid.json, $W\data\processed\MANIFEST.json
    Compress-Archive -Force -DestinationPath C:\Users\lenovo\Desktop\gsop_moon_lat20-40.zip -Path $W\results\moon_lat20-40\export, $W\results\moon_lat20-40\run_meta.json, $W\results\moon_lat20-40\compare_with_full.json

Send me:
1. both zips (a few MB each; the per-tile parquet files are not in them on purpose);
2. the printed coverage report from step 3, the last 20 lines of the runs in steps 5 and 6, and the output of step 7;
3. any `[FAIL]` line, word for word.

Mars: do NOT run for results until the Mars target values are confirmed (E20). `gsop run --body mars` was checked to prepare and complete on the smoke data only.
