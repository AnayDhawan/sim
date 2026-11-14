# Reference thermal layers: where each one cannot match Earth

Written by ROLE B for `data/reference/thermal_refs.csv`. Numbers quoted here are rows in that file (site, layer, stat) or statements in the product labels listed in `data/reference/thermal_refs_files.csv`. ROLE A compares every pair by percentile rank inside each body's own set, never by absolute value. That rule exists because of the first limit below.

## Limit that applies to every thermal layer

- Earth has no surface near the Moon's polar cold-trap temperatures. In this file `prp_temp_max` at `shackleton_rim` has a minimum of 76.75 K and `prp_temp_avg` a minimum of 49.584 K (primary radius, 5 km). Earth's surface cannot reach those values, so an absolute match is impossible. Only the within-body rank can be compared.
- The Moon has no atmosphere, so its surface temperature follows sunlight, slope and shadow. Earth's surface temperature also follows air, humidity, cloud, vegetation and water. Two places with the same rank can be warm or cold for different reasons.

## Per layer

### prp_temp_avg (Moon, PRP `temp_avg`)

- What makes it analogous: annual mean temperature is a long-term thermal budget, the same kind of quantity as the Earth annual mean of (day+night)/2.
- Where it breaks down:
  - PRP `temp_avg` is a model value at 2 cm depth (product label), not a measured skin temperature. Earth (day+night)/2 from land-surface-temperature products is a skin temperature at a satellite overpass time. The depth and the definition differ.
  - The PRP is a thermal model fit on a triangle mesh of about 500 m edges (about 613 triangles inside 5 km at `connecting_ridge_c1`, row `prp_triangles, n`). Sub-mesh variation is not represented.
  - Earth skin temperature has cloud-gap and overpass-time bias; the Moon value has none of these.

### prp_temp_max (Moon, PRP `temp_max`)

- What makes it analogous: peak heating on a given surface, matched to the Earth annual maximum of monthly day LST.
- Where it breaks down:
  - PRP `temp_max` is the modelled annual maximum at the surface. The Earth partner is a maximum of monthly satellite day values, which samples a few clear-sky overpasses and can miss the true peak.
  - On the Moon the maximum depends on grazing sun and horizon shadowing at the poles. On Earth it depends on latitude, albedo, moisture and cloud. The two are not driven by the same terms.

### prp_cold_trap (Moon, share of triangles with `temp_max` below 110 K)

- What makes it analogous: it measures how much of a site stays cold enough to hold ice, which links to the water and ice layer of the analog argument.
- Where it breaks down:
  - 110 K is the pre-registered threshold (`runs/v2/PREREG_B.md`). What the sources say, checked on 2026-11-15:
    - Hayne et al., "Micro cold traps on the Moon" (arXiv:2005.05369, HTML v1, read to about 60% of its length; the PDF did not render): Section 1 gives "<110 K" as cold enough for ice to last longer than the age of the solar system. Section 2, Eq. 1 uses the maximum temperature of permanent shadows below 110 K. The Figure 3 caption calls 110 K the adopted sublimation temperature for water ice. Section 3 says Williams et al. (2019) used a Diviner threshold of 110 K. Appendix C was not read.
    - Diviner team post (diviner.ucla.edu, "New Diviner Seasonal Polar Data Products", 2020-07-20): surfaces below 110 K can cold-trap water over a billion years; the map caption refers to maximum summer and winter temperatures. It names Williams et al. 2019, JGR 124:2505-2521.
    - Paige et al. 2010, Science 330:479-482: not opened (publisher and USGS pages returned HTTP 403). Whether it uses 110 K is not known from this run.
    - Williams et al. 2019: not opened.
    - PRP label `dlre_prp_south.xml` and the PRP collection label: no statement about 110 K or cold traps. The collection label cites Paige et al. 2010 as its reference.
    - Fit to PRP: the sources apply 110 K to a maximum temperature of shadowed terrain. PRP `temp_max` is a modelled annual maximum at the surface. The definitions are close but not identical.
    - No Earth surface sits below 110 K at its annual maximum, so the Earth partner for this layer is "not covered". It is a Moon-only context number, not a scored pair.
  - Cold traps smaller than the 500 m mesh are not resolved, so the fraction is a lower bound at this scale.
  - `shackleton_rim` shows 88 of 612 triangles below the threshold at 5 km; `connecting_ridge_c1` shows 0 of 613. Both statements are specific to the 5 km radius and move with radius (rows with suffix `_R2p5km` and `_R10km`). The two sensitivity windows at 10 km overlap each other.

### prp_ice_depth (Moon, PRP `ice_depth`, reference context only, not scored)

- What makes it analogous: it answers the same question as Earth permafrost depth (how far below the surface ice is stable).
- Where it breaks down:
  - The Moon value is the depth where ice would sublimate at 1 kg m-2 per billion years (label). Earth permafrost depth is set by ground temperature and heat flow over millennia, with liquid water and salts that the Moon does not have.
  - `-999` means deeper than 2.8738 m. In this file `connecting_ridge_c1` has 421 of 613 triangles at `-999` and `shackleton_rim` has 280 of 612. These are counted separately and never averaged.
  - The file also holds `-1.0` in 100,319 of 2,880,000 records, which the label does not define. Supplemental rows report it separately (see `runs/v2/PREREG_B_DEVIATIONS.md`, item 11). Cross-count at `shackleton_rim`, 5 km radius (rows `prp_ice_depth_x_cold_trap`): 87 triangles hold `-1`, 88 have `temp_max` below 110 K, 87 are in both, 0 hold `-1` without being below 110 K, 1 is below 110 K without `-1`. At 10 km: 563 hold `-1`, 580 are below 110 K, 563 are in both, 17 are below 110 K without `-1`. At 2.5 km neither group has a triangle. These are counts only; the label and the PRP collection label do not say what `-1` means, so it is not interpreted here.
  - The product shows where ice could be stable. It does not show that ice is present.

### rcp_diurnal_range and pcp_diurnal_range (Moon): not covered

- No v1 reference site is non-polar, so the RCP tile (Lacus Mortis only) was not used.
- The PCP polar diurnal files are about 250 MB per local-time file and 96 per season. They support byte-range reads (HTTP 206 in the step 2 probe) but were not downloaded, because the pre-registration fixed diurnal range as "not covered" for both polar sites.
- Consequence: the Moon diurnal range to Earth day-night range pair has no Moon values in this run.

### tes_ti_day and tes_ti_night (Mars, thermal inertia)

- What makes it analogous: thermal inertia is a property of the near-surface material (grain size, rock, cementation). Earth day-night temperature range responds to the same property, inverted: high inertia gives a small range.
- Where it breaks down:
  - The Earth partner is an inverted proxy. Earth day-night range is also driven by air humidity, cloud, vegetation and soil moisture. A damp soil and a high-inertia rock can have the same range.
  - The TES maps are 20 pix/deg, 2.96 km per pixel (label). About 38 pixels fall inside the 10 km radius at `jezero`. A 3 km pixel averages terrain that an Earth 1 km pixel would separate.
  - The labels give no scale factor and no fill value; the whole-map range is 0 to 4999 (deviations file, items 5 and 9). The values at `jezero` are well inside that range.
  - Interpolated pixels are flagged by the mask files. At `jezero` the interpolated share inside the radius is 0 for both maps (row `frac_interpolated`).
  - Mars atmosphere is thin and dusty, so the atmosphere does not damp the surface range the way Earth air does. The day-night range on Earth would partly measure the air, which the Mars thermal inertia does not.

### mars surface temperature: not covered

- No surface-temperature product was pulled for Mars. The TES TIMAP bundle holds thermal inertia only.

### arcadia (Mars site): not covered

- The v1 target file has no centre for Arcadia Planitia (`docs/DECISIONS.md` D10). No coordinates were guessed, so no layer is extracted for it.

### lunar terrain: not covered here

- LOLA terrain was skipped on purpose; the v1 run already carries Moon terrain.

## Reading the CSV

- `stat = not_covered` rows have an empty `value`. The reason for each is in this file.
- Sensitivity rows carry the suffix `_R2p5km` or `_R10km` on `stat`.
- The `sha256` column holds the checksum of the source file the number came from. Mask-file checksums are in `data/reference/thermal_refs_files.csv`.
