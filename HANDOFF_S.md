# Handoff for S (macOS, Apple M1)

You run the Mars targets. Do not edit code. If anything fails, send the full error text and the output of `uv run gsop doctor`.

1. Unzip the sim zip Anay sent. Install `uv` (`brew install uv`, or `curl -LsSf https://astral.sh/uv/install.sh | sh`). In the unzipped `gsop-sim` folder:
   ```
   uv sync
   uv run gsop doctor
   ```
   Send Anay the `doctor` output.
2. Put `earth_features_6km.parquet`, `grid.json` and `MANIFEST.json` (from the shared Drive link) into `data/processed/`, then:
   ```
   uv run gsop verify-data
   ```
   It must print `PASS`. If it does not, download the files again.
3. ```
   uv run pytest -q
   uv run gsop golden --out golden.json
   ```
   Send `golden.json` to Anay. Anay runs `gsop compare` on your file and the Windows one.
4. Build the Mars target profiles, then run:
   ```
   uv run gsop s2 targets --body mars --dem <path to the MOLA GeoTIFF>
   uv run gsop run --body mars --runs 2000
   ```
   The run is resumable: if it stops, run the same command again.
5. Zip the results and send them back:
   ```
   uv run python scripts/make_results_zip.py mars
   ```
   This writes `results-mars.zip` (it contains `run_meta.json`).
6. If anything fails, send the full error text and the `doctor` output. Do not edit code.

Notes
- Mars landing_mobility and power_night are labelled low confidence on purpose.
- Arcadia is skipped until its centre is taken from the SWIM ice map. That is expected.
- Your results and the Moon results are merged by Anay with `uv run gsop merge results/moon <your results/mars>`.

## Making the zip (Anay)

```
uv run python scripts/make_zip.py
```
This zips tracked files at the last commit, plus `uv.lock`, to `../gsop-sim-<commit>.zip`. Send it with the Earth feature file (`data/processed/earth_features_6km.parquet`, `grid.json`, `MANIFEST.json`).
