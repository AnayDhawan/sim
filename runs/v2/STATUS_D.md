# STATUS_D (ROLE D, fitted thermal terms, leave-one-site-out)

- updated: 2026-11-15 09:35 IST
- hard stop: 2026-11-15 17:00 IST
- stage: waiting for Role A's global Earth thermal layer (pull about 15 percent done at 09:10 IST per STATUS_A)
- done: PREREG_D committed and hashed (single-tile metrics, shuffled-feature baseline, Moon with and without illumination); reference side rebuilt from raw products, sha256 match Role B, value-space medians match Role B rows; scoring, fit, shuffle and report scripts written and tested on a synthetic layer (not kept); engine check reproduces v1 base scores exactly
- next: poll STATUS_A.md every 10 min; when the layer is listed: copy it, run prep, real, shuffle (1000 draws), report; push after each stage
- failures: none
