# Contributing to GSOP sim

This repository is the simulation engine behind GSOP. The website lives in [AnayDhawan/GSOP](https://github.com/AnayDhawan/GSOP) and only reads what this engine exports.

## The most useful help

- Confirm an item in [docs/UNVERIFIED.md](docs/UNVERIFIED.md): a known-site coordinate, the Arcadia centre, an uncertainty choice.
- Read [docs/SPEC.md](docs/SPEC.md) as a person and report anything unclear or wrong.
- Fix a bug, with a test that fails without the fix.

## Set up

Needs Python 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run gsop doctor
uv run pytest -q
uv run gsop golden
```

CI runs the tests and the golden slice on Windows and on macOS (Apple silicon). Please run them before you open a pull request.

## Rules

1. **One CLI.** Every command goes through `uv run gsop ...`.
2. **Determinism.** The same inputs give the same results whatever the worker count. A change that breaks this is a bug.
3. **Config, not constants.** Tunable values live in `config/*.yaml`. Weights are derived by code.
4. **Decisions are logged.** A change to weights, gates or validation criteria needs an entry in `docs/DECISIONS.md`, with who made it and whether it is confirmed.
5. **Pre-register.** Validation criteria are written down before a run produces results, never after.
6. **Unverified stays unverified.** If you cannot confirm a fact from an opened source, list it in `docs/UNVERIFIED.md`, and results that depend on it stay stamped provisional.
7. **No raw data in git.** Rasters and downloads stay under `data/`, which is ignored. Share a recipe, not a file.
8. **Cross-machine results compare by tolerance.** Never compare Windows and macOS output by hash.

## Writing style

- No em dashes. Use commas, colons, semicolons, periods or parentheses.
- Sentence case in headings. Bullets over prose where a list is honest.
- No `Co-Authored-By` trailer and no AI attribution in commits or pull requests.

## Pull requests

- One change per pull request, atomic commits, an imperative subject line.
- Say what you ran and what it showed.
- One `Closes #n` keyword per issue.

By contributing you agree that your contribution is released under the project's MIT licence.
