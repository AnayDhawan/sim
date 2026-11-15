# Proposal: candidate-stage climate re-scoring (exploratory)

Status: proposal only, nothing implemented, no Earth Engine call made for it. Written 2026-11-14 for the Mars Jezero run, applies to any body.

## Problem

The Earth feature file has no `ti_proxy`, `t_mean` or `t_coldest`. They were not exported globally because of cost (EE_COST.md, "Climate bands one at a time", 400-tile Atacama box, one batch task per band): `t_mean` 0.0480, `t_coldest` 0.0435, `ti_proxy` 0.1018 EECU-s per tile, 0.1933 together. For 3,972,955 land tiles that is about 768,000 EECU-s, 1.4 times the 540,000 monthly quota, so a global export is out. With the target side now holding `t_mean` and `t_coldest` for Jezero, a run that stops dropping them fails under SPEC section 7 (unavailable Earth column). The columns stay in `run.yaml drop_columns.mars` for the main run.

## Idea

Compute the three bands only for the tiles that survive the first pass, then re-score those tiles with the temperature family added.

1. Main run as today (gates, terrain, sunlight, air density families). Select candidates: the top N tiles by base score (N 3,000 to 5,000; the robust set is about 10,000 tiles at 100 runs, too large to cost this way).
2. Export candidates. A new command (for example `gsop s2 climate --body mars --job jezero__base --top 3000`) writes the tile ids and centres, builds the same Earth Engine bands as `earth/gee_export.py` (MODIS LST 2015-2024 climatology) with `reduceRegions` over the 6 km tile boxes, and downloads one small table, `candidate_climate.parquet` (tile_id, t_mean, t_coldest, ti_proxy, ti_is_fallback).
3. Cost: 3,000 tiles x 0.1933 = about 580 EECU-s; 5,000 tiles about 970 EECU-s. Per-task overhead dominates small tasks (EE_COST.md), so expect the same order. Run it after the terrain export finishes, because the monthly quota is shared.
4. Re-score: add the `temperature` family (`t_mean`, `t_coldest`) with weights renormalised, sigma by the same rule (`max(target spread, uncertainty, 0.25 IQR)`) with the IQR taken over the candidates, then rank inside the candidate set. Output goes to its own folder (`results/<body>_exploratory/`) and every file carries `exploratory: true`, `candidate_n`, `candidate_rule` and the climate source.

## Why it must be labelled exploratory

- Selection bias. The candidates were chosen by the other families. A tile with a perfect climate match and mediocre terrain was never costed, so the second pass can reorder the candidates but cannot find a new tile. A rank here means "best climate match among tiles that already scored well", not "best tile on Earth".
- Different population. The sigma IQR term, the Monte Carlo ranks and the validation percentiles are defined over all gated tiles. Over 3,000 candidates they are narrower and not comparable with the main run or with the pre-registered validation criteria (SPEC section 10). Validation cannot be re-run on this ranking.
- Post hoc change of the scored model. Adding a family after seeing the first ranking is not pre-registered. Weights are never tuned to pass, so the family weights must stay the derived ones.
- Comparability is partial. The Mars target is Mars Climate Database model output, the Earth column is MODIS LST observations, a model against a measurement of a different surface type and sensor.
- `ti_proxy` stays out until a conversion exists. The Earth column is a day-night temperature swing in K and the Jezero target is THEMIS thermal inertia in J m-2 K-1 s-1/2; no conversion is defined, so the target keeps it as `aux_thermal_inertia_si` only.
- Coverage. Only tiles with terrain can be candidates (22.9 percent of land tiles in the 2026-11-14 assembly), so the candidate list changes when more terrain arrives.

## Open points for a decision

- N and the cut rule (top N by base score, or the robust set capped at N).
- Whether MODIS LST maps to the MCD quantity well enough to report even as exploratory. A check on a few known sites (Lonar, Atacama salars) against MCD-style daily minima would show the size of the offset, but needs a person to choose the sites before any value is seen.
- A conversion for `ti_proxy`, if the team wants it in.
