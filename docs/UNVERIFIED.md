# Unverified items

Nothing below has been checked against a primary source. Each row says where it is used.

| Item | Where used | Status |
|---|---|---|
| Known-site coordinates (all of `known_sites.yaml`): Lonar, Haughton, McMurdo Dry Valleys, Atacama salars, Ladakh Puga, MDRS, SF volcanic field, Gosses Bluff, Mauna Kea, Askja, Manicouagan, Tatacoa, Samoylov, Amazon, Congo | `config/known_sites.yaml`, validation | From memory, `confirmed: false`. Shaurya must confirm before any result is published. Manicouagan and Tatacoa are "as given in our files". |
| Barker 2021 Moon slope uncertainty 2.0 deg and relief 0.4 m | `config/features.yaml`, sigma rule | Ranges (1.5 to 2.5 deg, 0.3 to 0.5 m) given in the setup prompt; the midpoints are the assistant's choice. |
| Earth Engine collection IDs for every Earth layer | `config/features.yaml` (leads), Phase 2 | Not checked. Verify in the live catalog and record in `PROVENANCE.md`. |
| Satellite surface minimum for the cold-traps ledger row | `config/ledger.yaml` | The row quotes about 184 K air-temperature record; the setup prompt says the satellite minimum is lower and must be checked before quoting. |
| Ledger relevance matrix (which rows matter for which purpose) | `config/ledger.yaml`, fidelity | Draft, `provisional: true`. Anay and Vihaan review. |
| Electrostatic dust and regolith mechanics rows | `config/ledger.yaml` | From Shiven's report, unverified. |
| `rough_a` 100 m and `rough_b` 1000 m baselines | `config/features.yaml`, operators | TODO confirm with Vihaan. |
| Mars `air_density` exponential-law constants | `config/features.yaml`, Phase 3 | Unsourced. |
| Cross-machine tolerances (score 1e-4, MC 1e-3, Jaccard 0.99) | `config/run.yaml` | First guess. |
| Validation site-score rule (mean over targets) | `docs/SPEC.md` section 10 | Assumption. |
| Arcadia Planitia centre | `config/targets.yaml` | Not in our files. Take from SWIM ice map (issue #4). |
| PSR share, Diviner and other Moon target sources | Phase 3 | Not wired. No URL or product ID has been checked. |
