# Decisions (made by Anay, 2026-11-13, not to be reopened)

- D1. Tile size 6 km x 6 km on the equal-area grid EPSG:6933 (6000 m cells). Land only, polar ice gated out.
- D2. 2,000 Monte Carlo runs per configuration (`--runs` overridable). Master seed 20261114. Per-run seeds from `SeedSequence(master).spawn(n)`, so results do not depend on worker count.
- D3. Lunar thermal-inertia weight is the derived 0.019. The published 0.03 is a rounding-up artifact. Both are in config; the derived value drives the run.
- D4. The primary Moon run follows the published weights (illumination 0.18). A `no_illumination` variant (illumination 0, rest renormalised) is also run and the report says whether the robust tiles survive. Illumination match is also reported in the fidelity output.
- D5. Purpose profiles: Moon has landing_mobility, power_night, ice_resources plus base. Mars adds geology_life. No Moon life-detection. Mars landing_mobility and power_night are `confidence: low`.
- D6. The Mars target check (within 50 deg latitude, below 2 km, thermal inertia at least 100) is `warn` by default. A failing target still runs and is labelled `fails_own_gate: true`, and is listed in `validation.json`.
- D7. Mars ice variables are one composite, `water_index`. Ice depth, ice consistency and thermal inertia are not counted separately.
- D8. The Monte Carlo jitters weights and data (SPEC section 8).
- D9. ML is a second opinion only and never produces the score.
- D10. Arcadia Planitia's centre is not in our files. It is loaded from the SWIM ice map or Arcadia stays `unscored: no target data`. No guessed coordinates.

# Decisions made while building (assistant, to be confirmed)

- E1. The grid runs pole to pole (y extent 7,342,230.136 m) instead of stopping at 85.04 deg.
- E2. A column that cannot be built stops scoring with an explicit error. Dropping it needs a deliberate entry in `run.yaml: drop_columns`.
- E3. Validation site score is the mean over the body's scored targets of the best-tile rank percentile within 20 km.
- E4. Per-tile noise is not applied in the Monte Carlo.
- E5. Candidate tiles for pass 2 are the robust tiles plus the top 3 percent by mean score and by top-5 membership, capped at 250,000.
- E6. `docs/source/` (the combined plan document) is gitignored because it holds competition strategy and the repo is public.
- E7. Mars air density uses the NASA Glenn lower-atmosphere model (699 Pa, scale 11.1 km) via `config/targets.yaml mars_atmosphere.use`. PENDING a human decision: the plan's "610 Pa, 11.1 km" is in no source found, and NASA's fact sheet gives 636 Pa and 11.0 km (no temperature model). Every Mars `air_density` row names the model in its `source` text.
- E8. Earth sun_max_elev, sun_low_share and insol_annual are computed from latitude and obliquity only (parameters in `config/features.yaml solar`). SPEC section 3 also names slope and aspect. PENDING.
