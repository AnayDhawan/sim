# PREREG_B deviations and label findings

`PREREG_B.md` is not edited (its sha256 is in `prereg_b.sha256`). Items found after registration go here, dated, and each is written before the large downloads start.

## 2026-11-15 01:30 IST, before any download over 1 MB

1. Repo mismatch. The brief names `v1-final` and `data/reference/raw/*.csv`. This clone has no tag and no `data/reference/`; the score CSVs are in `data/raw/`. Impact: none on this run.
2. PCP byte-range probe. Step 2 says HEAD only. A 200-byte `Range: bytes=0-199` request on `pcp_avg_tbol_poln_sum_ltim01_240.tab` was also sent. Result: HTTP 206, so PCP supports byte ranges. Per PREREG_B, PCP is still not used and diurnal range stays "not covered".
3. Accept-Ranges: `bytes` for the TES day map, the PRP south file and the PCP file. PRP Content-Length 604,800,210 matches the brief.
4. Mars radius. The TES labels give A, B and C axis radii of 3396.0 km. PREREG_B wrote 3389.5 km. The label wins: 3396.0 km is used. Pixel geometry comes from the label (`LINE_PROJECTION_OFFSET` 1800.5, `SAMPLE_PROJECTION_OFFSET` 3600.5, 20 pix/deg, planetocentric, east-positive, -180 to 180).
5. TES scale and fill. The brief says to read them from the `.lbl` files. Neither `global_ti_day_2007.lbl` nor the night label states a scale factor or a fill value (the labels hold units, size and projection only). Rule fixed now: scale 1.0 (units J m-2 K-1 s-1/2 as the label states), no fill value. Pixels with value <= 0 are excluded and counted; the maximum is reported unfiltered.
6. TES masks. The mask labels say `SAMPLE_BITS = 8` and `RECORD_BYTES = 7200` (one byte per pixel). Value 0 means interpolated, from each mask's own label. `datainfo.txt` names `global_ti_day_2007.img` in the night-mask text; that is the copy error the brief mentions and is ignored.
7. PRP label. `version_id` 1.0, `lro:product_version_id` 2, Moon radius 1737.4 km, `-999` is the declared invalid constant for `ice_depth`. Data table starts at byte offset 210 (one header record), fields 1-based: `tri_clon` at 127 (15 wide), `tri_clat` at 144 (15), `tri_calt` at 161 (15), `temp_avg` at 178 (8), `temp_max` at 188 (8), `ice_depth` at 198 (11). Bundle version 5.0 is taken from the brief; the PRP label does not state it.
8. Line endings. Git here converts LF to CRLF on checkout (`core.autocrlf`). The sha256 in `prereg_b.sha256` is of the LF file as written; a Windows checkout may hash differently.

## 2026-11-15 01:20 IST (clock time approximate), after smoke test, before full run

9. TES value range. The day map spans 0 to 4999 over the whole map (smoke test). 4999 may be a cap and 0 an empty pixel. The label does not say. Exclusion rule from item 5 stands (value <= 0 excluded and counted). An extra count row `n_value_4999_in_R` is written; 4999 values are not removed. Jezero day pixels in the smoke test ranged 255 to 417, so this is expected to be moot at Jezero.
10. Smoke test used the first 100,000 PRP records (a byte-range read, kept out of the committed outputs). PRP `tri_clon` is in -180 to 180 in the data; the label says east longitude. Distances use 3D unit vectors, so this does not matter.

## 2026-11-15 01:35 IST (clock approximate), after the first full run

11. Undocumented ice_depth value. In the south PRP file 100,319 of 2,880,000 records hold `ice_depth = -1.0`. The label defines only 0 (ice stable to sublimation at the surface) and -999.0 (deeper than 2.8738 m). No definition of -1.0 was found in the label. The pre-registered primary rows (everything except -999 counts as valid) are kept unchanged and still include -1.0 in `p5_valid`. Supplemental rows `n_minus1_undocumented`, `frac_minus1_undocumented` and `*_valid_excl_minus1` are added. `ice_depth` is reference context only and not scored, so no score depends on this choice. No other pre-registered quantity changed. The first run took about 2.5 minutes in total because the files are small; the 17:00 IST stop and the 10-minute status interval were not tested by a long run.

## 2026-11-15, B2 follow-ups (after commit fbf6dfa)

12. Arcadia: the follow-up brief carried the placeholder `<LAT, LON>` instead of coordinates. No amendment was written and no Arcadia rows were extracted; Arcadia stays "not covered".
13. Line endings: `.gitattributes` with `runs/v2/*.md text eol=lf` added. `git add --renormalize runs/v2/` changed nothing, because the stored blob was already LF. The sha256 of PREREG_B.md is unchanged (2751d789...). The git blob id is recorded in `prereg_b.sha256`.
14. Cross-count of `ice_depth = -1.0` against `temp_max` below 110 K at `shackleton_rim` (script `scripts/b_followup_ice_minus1.py`, rows with layer `prp_ice_depth_x_cold_trap`). Counts only.
15. 110 K sources re-checked; the outcome (Paige 2010 and Williams 2019 not opened) is in `docs/refs_limits.md`.
