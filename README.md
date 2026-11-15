<div align="center">

<img src="https://raw.githubusercontent.com/AnayDhawan/GSOP/main/public/brand/motifs/gsop-footer-dark-2560x640.webp" alt="The Moon, Earth and Mars under the GSOP signature ribbon" width="100%">

<br><br>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/AnayDhawan/GSOP/main/public/brand/logos/gsop-logo-horizontal-dark.png">
  <img src="https://raw.githubusercontent.com/AnayDhawan/GSOP/main/public/brand/logos/gsop-logo-horizontal-light.png" alt="GSOP" width="420">
</picture>

<h1>GSOP sim</h1>

**The simulation engine behind GSOP. It scores every 6 km land tile on Earth against Moon and Mars targets, and keeps the receipts.**

[![CI](https://github.com/AnayDhawan/sim/actions/workflows/ci.yml/badge.svg)](https://github.com/AnayDhawan/sim/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-3776ab.svg)](pyproject.toml)
[![uv](https://img.shields.io/badge/managed%20with-uv-6c47ff.svg)](https://docs.astral.sh/uv/)

[Live site](https://gsoplatform.vercel.app) · [Site repository](https://github.com/AnayDhawan/GSOP) · [Spec](docs/SPEC.md) · [Decisions](docs/DECISIONS.md) · [Status](STATUS.md)

</div>

> Not affiliated with or endorsed by NASA. A research prototype built for the NASA Space Apps Challenge 2026.

## What it is

- **A scoring engine.** Each land tile on an equal-area grid is compared with a Moon or Mars target on terrain and thermal layers.
- **A Monte Carlo.** The weights are varied over many runs, so a tile is flagged only if it stays near the top across the runs.
- **A checker.** Gates reject unsuitable ground, and validation runs against criteria that are written down before any result exists.
- **An exporter.** Results leave as files with a sha256 manifest. The [site](https://github.com/AnayDhawan/GSOP) reads them and never recomputes a score.

## Where it stands

[STATUS.md](STATUS.md) is the source of truth for what is done and what is not. Read it before you trust a number.

- The engine, the gates, the Monte Carlo, validation, export and the golden slice are written and tested, on synthetic data.
- The Earth Engine export is written but needs a login to run, so it has not been run.
- Known-site coordinates are mostly unverified, and every validation result is stamped provisional until a person confirms them ([docs/UNVERIFIED.md](docs/UNVERIFIED.md)).
- The v2 scoring and fitted-model results shown on the site live on the branches `v2/a-scoring` and `v2/d-fitted`. The published gate results are on the [gates page](https://gsoplatform.vercel.app/gates): three failed, one passed and three could not be tested.

## Pipeline

Every command goes through one CLI, `uv run gsop`.

| Stage | Command | What it does |
|---|---|---|
| Check | `doctor` | Cores, memory and the Monte Carlo budget on this machine |
| 1 | `s1 tiles` | The 6 km equal-area tile grid |
| 2 | `s2 earth`, `s2 open-data`, `s2 targets` | Earth features (Earth Engine or local rasters), and Moon and Mars targets |
| 3 | `s3` | Gates, with a reason for every rejected tile |
| 4 | `s4` | Base similarity |
| 5 | `s5` | Monte Carlo: fixed batches, resumable |
| 6 | `s6` | A machine-learning second opinion |
| 7 | `s7` | Validation against pre-registered criteria |
| 8 | `s8` | Export, with a sha256 manifest |
| 9 | `s9` | Flag regions |
| All | `run`, `golden` | The whole pipeline, and a small fast slice of it |
| Data | `verify-data`, `check-operators`, `compare`, `merge` | Check inputs, check operators, compare two runs, merge results |

## Quick start

Needs Python 3.11 and [uv](https://docs.astral.sh/uv/). Works on Windows and macOS.

```bash
git clone https://github.com/AnayDhawan/sim.git
cd sim
uv sync
uv run gsop doctor && uv run pytest -q
uv run gsop golden
```

The golden slice (a few thousand tiles, both bodies) is the fast end-to-end check. `gsop doctor` tells you whether your machine fits a full run.

## What it guarantees

- **Deterministic.** The same inputs give the same results whatever the number of worker processes.
- **Resumable.** The Monte Carlo runs in fixed batches and can be stopped and continued.
- **Provenance.** Every exported file carries a hash, and the manifest lists them all ([docs/PROVENANCE.md](docs/PROVENANCE.md)).
- **Pre-registered.** Validation criteria are fixed before results exist ([docs/DECISIONS.md](docs/DECISIONS.md)).
- **Honest across machines.** Results are not bit-identical between Windows and macOS (BLAS and SIMD differ), so the cross-machine check compares by tolerance, never by hash.

## Configuration

Everything tunable is in `config/`. Weights are derived by code, and the numbers in the plan match to four decimals.

| File | Holds |
|---|---|
| `run.yaml` | Run sizes, batches and the cross-machine tolerances |
| `targets.yaml`, `purposes.yaml` | Moon and Mars targets, and the purpose profiles |
| `weights.yaml`, `features.yaml` | Feature weights and the feature list |
| `gates.yaml`, `ledger.yaml` | The gates, and the failure-first ledger |
| `known_sites.yaml` | Reference sites used for validation (mostly unverified) |
| `earth_layers.yaml`, `open_data.yaml` | Earth Engine layers and the open-data fallback |

## Folder structure

```text
sim/
├── src/gsop/        the engine: grid, operators, similarity, gates, montecarlo, ml, validate, export, cli
├── config/          every tunable value, as YAML
├── tests/           unit tests and the golden slice
├── scripts/         benchmarks and results zips
├── docs/            SPEC, DECISIONS, UNVERIFIED, PROVENANCE, RESULTS_SCHEMA, UNCERTAINTY_SOURCES
├── STATUS.md        what is done, what is not, what a person must confirm
└── HANDOFF_S.md     teammate handoff for macOS
```

## Contributing

Start with [CONTRIBUTING.md](CONTRIBUTING.md). The most useful help is confirming the unverified items: known-site coordinates, the Arcadia centre, and a human read of the spec. Please read the [Code of Conduct](CODE_OF_CONDUCT.md). Report security problems through [SECURITY.md](SECURITY.md).

## How AI was used

- Parts of the design and its decision log were written with AI assistants. Those entries are marked "assistant, to be confirmed" in [docs/DECISIONS.md](docs/DECISIONS.md).
- One independent re-implementation of the spec was done by an AI agent. A person still has to read the spec ([STATUS.md](STATUS.md)).

## Licence

MIT, 2026, the GSOP team. See [LICENSE](LICENSE).
