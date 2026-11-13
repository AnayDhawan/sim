# GSOP sim

Simulation engine for GSOP (Geospatial Similarity Observation Platform), NASA Space Apps 2026.
Scores every 6 km land tile on Earth by similarity to a Moon-base or Mars landing target, runs a Monte Carlo on the score, validates against known analog sites, exports results for the site.

- Spec: `docs/SPEC.md`
- Decisions: `docs/DECISIONS.md`
- Unverified items: `docs/UNVERIFIED.md`
- Teammate handoff (macOS): `HANDOFF_S.md`

## Quick start

```
uv sync
uv run gsop doctor
uv run pytest -q
uv run gsop golden
```

All commands go through the single CLI `uv run gsop ...`. Works on Windows and macOS.
