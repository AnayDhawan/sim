# Security policy

## Supported versions

Only the current `main` branch. There are no tagged releases yet.

## Reporting a vulnerability

Do not open a public issue for a security problem.

Email **dhawansanay@gmail.com** with a description, steps to reproduce, the likely impact and a suggested fix if you have one.

The engine runs locally and reads files you give it. The Earth Engine export uses your own login. Credentials, tokens and `.env` files must never be committed, and the `.gitignore` excludes them.

## What to expect

| Stage | Target |
|---|---|
| Acknowledgement | within 72 hours |
| Status update | within 7 days |
| Fix or mitigation | within 30 days |

This is a student team, so these are targets, not guarantees.

## Scope

In scope: unsafe handling of input files (for example a crafted raster or YAML), exposed secrets, a dependency with a known CVE that affects the engine.

Out of scope: problems in Google Earth Engine or other third-party services, and the scientific limits of the results, which are documented in `docs/UNVERIFIED.md` and on the site.
