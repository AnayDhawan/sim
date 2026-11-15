# Open items triage (2026-11-14)

Read: `docs/UNVERIFIED.md` (70 rows, counting every table row and every bullet of its sections once, plus the DEM seam row added today = 71) and `docs/DECISIONS.md` (D1-D10, E1-E31). `UNVERIFIED.md` was not changed by this triage.

Classes:

- A = affects the v1 results; needs a stated limit in outputs or in the write-up.
- B = future work; no effect on v1.
- C = already resolved, or made moot, by a decision (id cited) or by evidence in the repo (doc cited).
- D = needs a human check before anything is published (site coordinates, ledger matrix, sources from Vihaan or Shiven, target values).

Where a row could be both A and D it is D (the human check comes first, the limit is stated afterwards).

## Counts

| Class | Rows |
|---|---|
| A | 9 |
| B | 6 |
| C | 38 |
| D | 18 |
| Total | 71 |

## A rows: affect v1 results

| Row | What | Why it matters | Recommended action |
|---|---|---|---|
| S6 samoylov gate test | 54% water, 40% herbaceous wetland; rejection is marginal | the gate test result is part of the validation criteria; whether it is rejected by the water gate or as missing data depends on whether its E23 stage-1 box finished (not checked here) | report the measured gate reason as is, state that it is marginal, do not move the threshold |
| U2 no uncertainty sourced for any column except Moon slope and relief | only 3 of the Moon columns and 0 of the Mars columns carry a measurement sigma (features.yaml) | the Monte Carlo band is narrower than the real uncertainty | print the one-sentence limit below in the write-up and in every summary |
| U3 sigma rule statistic | most sources give LE90 or percent accuracy, not a sigma | the width of the similarity function (and so the score) depends on it | keep the rule as coded (max of target spread, sigma, 0.25 IQR); say in the write-up that the 0.25 IQR term sets most widths |
| G4 gate definitions in the Earth Engine export | built_crop_frac counts IGBP classes 12 and 13 only (not 14); water_ice_frac counts 15 and 17 (ocean included); ndvi median rule | they decide which tiles survive (11,179 built or cropland and 15,282 water or ice rejections in the Moon run) | accept and list the class codes in the write-up |
| G6 tile is not 6 km square on the ground away from 30 deg latitude | 3.5 x 10.4 km at 60 deg | Earth tiles at different latitudes are different ground shapes compared with square Moon and Mars windows | E12 accepts it; state it in the write-up, the lat 20-40 run (E29) is the robustness check |
| G7 anisotropic slope cell and roughness windows | 289 x 866 m slope cell at 60 deg | same cause; kx fixes only the gradient (and the delivered slopes are not even kx corrected, E25) | state with G6; no re-export |
| O13 built_crop_frac class 14 (mosaic) not counted | choice not confirmed | affects the built or cropland gate | same as G4 |
| O19 obliquity 23.44 deg, S0 1361 W/m2, standard-atmosphere constants not re-checked on integrate | feed sun_max_elev, sun_low_share, insol_annual, air_density | small but unchecked inputs of scored columns | one-line check against the NASA fact sheets (Claude can do it); then close |
| DEM seam at 60 N (added today) | rough_a is 19 to 37 percent higher and rough_b 6 to 14 percent higher in GLO30 than SRTM90 on the same ground; slope, relief, elevation agree to 1 to 2 percent (SPEC 3g) | tiles above 60 N are 1.4 percent of tiles with terrain, and 0.0 to 3.5 percent of the robust tiles per job | accept for v1; state the step; do not rank above-60 N tiles on roughness alone |

## D rows: need a human before publishing

| Row | What | Why it matters | Recommended action |
|---|---|---|---|
| S2 mcmurdo_dry_valleys, atacama_salars | areas, Wikipedia only, `confirmed: false` | validation results are stamped provisional while any site is unconfirmed | check a primary page, or publish with the provisional stamp |
| S3 mdrs_utah, sf_volcanic_field, mauna_kea, askja, tatacoa | Wikipedia or snippet only | same | same |
| S5 tatacoa gate test | its tile has 0% water and 0.1% built; only NDVI can reject; proxy 0.197 vs threshold 0.2 | "expect: rejected" may not hold | report the measured result; do not adjust |
| S8 congo_basin negative control | no coordinate source recorded | a control with an unchecked point | accept or confirm one source |
| T9 Mars v1 and Jezero target values | Mars has four families left; runs only after Anay confirms the Jezero values | the finished Mars run (4 jobs) is provisional until then | confirm the 2026-11-14 values (see J1) or keep Mars labelled provisional |
| T11 Mars air_density constants | Glenn 699 Pa and 11.1 km vs NASA fact sheet 636 Pa and 11.0 km (E17 pending) | 10% difference in the target density 0.0188 kg/m3 against a sigma of 0.024 | keep Glenn, label it, accept; the effect is well inside the sigma |
| L2 cold-traps target side (was "below 110 K, down to 38 K") | RESOLVED 2026-11-14: ledger now says 29 K measured (Paige 2010), 38 K removed (modelled subsurface) | a ledger number that could be published wrong | read Hayne and Paige and fix or remove the number |
| L3 ledger relevance matrix provisional | `relevance_provisional: true` until Anay and Vihaan review | fidelity output rests on it | review it, or publish the ledger as provisional |
| O1 all known-site coordinates | from memory, `confirmed: false`; Shaurya to confirm | validation and discovery distances use them | same as S2 and S3 |
| O5 ledger relevance matrix | draft | same as L3 | same as L3 |
| O6 electrostatic dust and regolith mechanics rows | from Shiven's report, unverified | published ledger rows | verify against sources or drop the rows |
| O15 rough_a 300 m and rough_b 1000 m baselines | `TODO confirm with Vihaan` | defines the roughness columns for all bodies | ask Vihaan once, record the answer |
| M1 Moon t_mean and t_coldest NOT FOUND | Vihaan's evidence table, agent-assisted, not re-verified | the write-up says why the columns are dropped | spot-check the Diviner PRP and PCP pages before wording it as "not available" |
| M3 Moon silica_index NONE EXISTS above 70 deg | same | same | open Zenodo 4558235 once |
| R1 Mars silica_index NONE EXISTS | Shiven's table, not re-verified | same | spot-check the cited pages |
| R2 Mars water_index NOT FOUND at Jezero | same (SWIM 2.0) | same | spot-check SWIM |
| R3 Mars dust_index NOT FOUND | same (MGS TES dust cover) | same | spot-check |
| J1 aux_thermal_inertia_si 204.08 and the D6 check | derived from the Zenodo THEMIS mosaic (E31, assistant, to be confirmed) | it turned the D6 check from unknown to true | confirm the value and the record 4931348 |

## B and C rows (no action for v1)

B, future work: G9 (open-data fallback untested on real downloads), T2 (LOLA and PSR clip; full PSR download not needed), O16 (cross-machine tolerances are a first guess; measured differences are 0 here and under 8e-6 on macOS, against allowed 1e-4; CI on both runners still to do), J3 (t_coldest definition for Mars, columns stay dropped), J4 (Mars MCD month-centre approximation, column unused), J5 (candidate-stage climate re-scoring proposal).

C, resolved or moot, with the deciding item:

| Rows | Resolved by |
|---|---|
| S1 confirmed sites | E11 (confirmed against opened sources; Anay sign-off is covered by the D rows) |
| S4 manicouagan gate test | E13 (two points) |
| S7 amazon_basin control | E14 (moved to -2.9, -60.0) |
| S9 lonar tile fails built gate | E28 (gated_out, outside the median) |
| U1, O2 Barker midpoints | E15 |
| G1, G2, O3 gee_export written without a login; collection ids from the catalog page | the exports ran for real (E22, E23, SPEC section 11 last bullet); ids checked in the live catalog 2026-11-13 (`PROVENANCE.md`) |
| G3, O10, O11, O12 water, silica, dust not built; aridity-only water_index; silica and dust formulas | E19, E20, E21, E31 (columns dropped, Earth silica export not needed) |
| G5, O20 sun columns use latitude and obliquity only | E18 (confirmed), E26 |
| G8 SRTM90 covers 56 S to 60 N; haughton, mcmurdo, samoylov, askja | E22, E23 (GLO30 above 60 N and stage-1 boxes) |
| T1 Moon and Jezero targets built | E19, E24 |
| T3, T5, M2, M4, M5 Moon temperatures, ti_proxy and water_index dropped; the Williams C2 warning | E19 |
| T4 Moon silica_index | E16 |
| T6, T7, R4 Mars roughness and climate columns dropped | E20, E31 |
| T8 Mars sunlight constants | E24 |
| T10, O8 Arcadia centre | D10 (stays unscored) |
| L1, O4 cold-traps Earth cell numbers | verified quotes in `PROVENANCE.md` and `UNVERIFIED.md` (184.0 K air, about 174.6 K satellite) |
| O7 validation site-score rule | E3 (confirmed) |
| O9 PSR and Diviner not wired | E19 (PSR built; Diviner columns dropped) |
| O14 NASADEM against Copernicus datum | E22 (SRTM90 replaces NASADEM); measured elev_mean difference at the seam is at most 2 percent in the median (SPEC 3g) |
| O17 lunar thermal-inertia weight 0.019 outside its MC range | D3, E18; moot because the Moon thermal_inertia family is dropped (E19) |
| O18 Monte Carlo run time on Windows | `docs/PERF.md` (measured today) |
| O21 Earth slope not kx corrected | E25, E29 (accepted, labelled, lat 20-40 robustness run) |
| J2 ti_proxy for Mars not filled from THEMIS | E31 |

## Earth biases and measurement uncertainties still TODO

- `earth_uncertainty` in `config/features.yaml` is `{}`: none of the 15 Earth columns has a systematic bias term. The 15 columns are slope_med, slope_p90, relief, rough_a, rough_b, sun_max_elev, sun_low_share, insol_annual, t_mean, t_coldest, ti_proxy, dust_index, water_index, silica_index, air_density. The Monte Carlo still draws one Earth-bias normal per column (SPEC section 8), but it is multiplied by 0.
- Measurement uncertainty is set only for Moon slope_med 2.0 deg, slope_p90 2.0 deg and relief 0.4 m (Barker 2021 midpoints, a choice, E15). Mars has none; no Earth column has one. Sourced candidates that were not applied are in `UNCERTAINTY_SOURCES.md` (GLO30 LE90 under 4 m, SRTM 16 m at 90 percent, MODIS LST 1 K, THEMIS 20 percent). Not sourced at all: rough_a, rough_b, sun_*, water_index, dust_index, air_density.
- Per-tile noise is not applied (E4).
- Consequence, one sentence for the write-up: "The Monte Carlo varies the weights and, for the Moon only, the slope and relief measurement error, and applies no systematic Earth bias to any of the 15 Earth columns, so the reported score bands and robust-tile counts understate the real uncertainty."

## What Anay has to sign off (11 items)

1. **Mars Jezero target values and the four-family Mars model** (T9, J1). Recommend: accept the 2026-11-14 values, keep the label "four families" on every Mars output, leave ti_proxy, t_mean, t_coldest dropped.
2. **Unconfirmed site coordinates** (S2, S3, S8, O1, and rub_al_khali from E30). Recommend: have the primary pages checked once (Claude per E11, Anay signs); until then everything stays stamped provisional and the validation line is not quoted.
3. **Tatacoa and samoylov gate tests** (S5, S6). Recommend: report whatever the gate says, call both marginal, move nothing.
4. **Mars air density source** (T11). Recommend: keep NASA Glenn 699 Pa, 11.1 km; the 10 percent gap to 636 Pa is far inside the sigma.
5. **Roughness baselines 300 m and 1000 m** (O15). Recommend: accept and ask Vihaan for one yes or no.
6. **Ledger** (L2, L3, O5, O6). Recommend: publish the ledger as provisional, remove or flag the unverified dust and regolith rows and the 38 K figure.
7. **"No comparable source" claims from the evidence tables** (M1, M3, R1, R2, R3). Recommend: spot-check the five cited pages; until then write "not found by us", not "does not exist".
8. **Uncertainty limit** (U2, U3, Earth biases above). Recommend: accept v1 as it is and print the one sentence above with the results.
9. **Tile shape and slope bias** (G6, G7). Recommend: accept E12 and E29, no re-export, quote the lat 20-40 run as the check.
10. **DEM seam roughness step** (new). Recommend: accept for v1 and state it; above-60 N tiles are 1.4 percent of terrain tiles and at most 3.5 percent of any job's robust set.
11. **Gate definitions and solar constants** (G4, O13, O19). Recommend: accept class 12 plus 13 for built or cropland and ocean inside water_ice_frac; Claude checks the constants against the NASA sheets and closes O19.
