# Light-field contract v2 — decisions + task for the Claude Code session

Source: sky-dome / Vizard questions (azimuth, horizon, time axis, regions, size, demo data).
Status: DECIDED here, NOT yet implemented. Implement on branch `imok/light-contract-v2`
(contracts/light.py + tests/test_contracts.py + docs/FORMATS.md). Keep v1 files loadable.

## Decisions (answers to the sky-dome questions)
1. **Azimuth: yes.** Add `sun_az_deg` and `earth_az_deg`, shape **[T]** (tile centre, not per cell).
   Compass degrees, clockwise from north, 0..360, in the tile ENU frame (row 0 = north).
   Why per-tile: across a 2 km tile the azimuth differs by ~0.07 deg, so [T,H,W] only wastes disk.
   Optional on load (v1 files have none -> sky dome falls back to elevation only).
2. **Horizon profile: yes.** `horizon_elev_deg` [K,360] (index = azimuth degree, 0 = north,
   clockwise), from the same LOLA ray-cast as KAN-23, for each cell in the point series (below).
3. **Time axis.** Cadence **1 h**, span **one synodic month = 709 samples** (708 h = 29.5 d, both
   ends inclusive). `<date>` in `<region>_<date>.npz` = **window start, UTC, YYYY-MM-DD (00:00:00Z)**,
   NOT a lunar-day id. Two dates per region; Imok picks them (suggest one near a lunar sunrise at
   the site and one a month later/earlier season so the sky dome shows both regimes).
4. **Regions.** One tile per site, region id = site id from `sites/sites.json`
   (e.g. `chandrayaan3_shiv_shakti` at -69.373, 32.319 gets its OWN tile). `sites[].region` must
   equal the tile/light region name. The other 3 sites come from KAN-38; do not invent them.
5. **Size.** A full 400x400x709 float32 field is ~0.45 GB per variable (not 1.1 GB), 3 variables
   ~1.4 GB uncompressed. Fine for the 4090 / pen drive, not for git. Add a small
   **per-site point series** `data/light/<region>_<date>_points.npz` for the Navigator + Vizard:
   `cells` [K,2] (row,col; candidate landing cell + 8 neighbours, K<=9), `times_utc` [T],
   `et_s` [T], `sun_fraction` [T,K], `sun_elev_deg` [T,K], `earth_elev_deg` [T,K],
   `sun_az_deg` [T], `earth_az_deg` [T], `horizon_elev_deg` [K,360], header with Meta.
   Cadence for points may be 10 min (T=4249) — default 1 h to match the field.
6. **Demo data.** The sky-dome owner may write a GENERATED stand-in in exactly this format
   (Meta.provenance = "generated", banner "GENERATED — NOT OBSERVED"). The format above is the
   commitment; any change gets announced in docs/STATUS.md.

## Prompt for Claude Code
> Read docs/team/LIGHT_CONTRACT_V2.md. On branch imok/light-contract-v2 extend contracts/light.py
> (optional sun_az_deg/earth_az_deg [T]; new PointSeries dataclass + save/load/validate for the
> `_points.npz` format; v1 files still load), add tests in tests/test_contracts.py (round-trip,
> shape errors, az range 0..360, horizon shape [K,360], v1 backward compat), update docs/FORMATS.md
> and validate_formats --selftest. Keep pytest green and ruff clean. Commit locally, then push.
