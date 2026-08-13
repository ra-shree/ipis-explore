# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Data pipeline and Streamlit dashboard for exploring Nepal's local-level election results (2074/2017 and 2079/2022), built around a Nepali Congress strategic-tier view of the country's 753 palikas (local government units).

## Commands

```bash
# Run the dashboard
uv run streamlit run main.py

# Regenerate storage/processed/ from storage/data/ (run in this order — later
# scripts join against reference tables the earlier ones produce)
uv run python scripts/build_parquet.py           # parties/posts/symbols/provinces/districts/palikas
uv run python scripts/process_elections.py       # election_2079, per-district CSV+JSON -> per-province parquet
uv run python scripts/process_election_2074.py   # election_2074, per-province JSON -> per-province parquet
uv run python scripts/build_geojson.py           # province/palika boundaries (needs build_parquet.py's output)
```

There is no lint/typecheck/test tooling configured in this repo (no ruff/mypy/pytest in `pyproject.toml`).

`storage/data/` (raw scrape input, plus raw boundary geojson under `storage/data/geojson/`) is git-ignored and must be fetched/regenerated separately. `storage/processed/` (pipeline output — parquet + geojson) **is committed to git**, despite the blanket `storage/**` rule at the top of `.gitignore` — a later `!storage/processed/` / `!storage/processed/**` pair re-includes it, so the dashboard runs from a fresh clone without regenerating anything.

## Architecture

**Pipeline → parquet/geojson → dashboard**, stages that only communicate through `storage/processed/` (step 3 additionally reads step 1's parquet output, as noted in Commands above):

1. `scripts/build_parquet.py` — table-driven (a `TABLES` list of `{name, source, rename, columns}` specs) conversion of reference JSON (`parties.json`, `posts.json`, `symbols.json`, `storage/data/locations/*.json`) into flat reference parquet tables.
2. `scripts/process_elections.py` / `scripts/process_election_2074.py` — read raw per-district (2079) or per-province (2074) scrape output, join in district/province names via the reference parquets from step 1, and write one parquet per province into `storage/processed/election_{year}/`. The two years have structurally different raw sources (CSV+metadata.json per district vs. JSON per province) hence separate scripts, but converge on the same output schema/columns.
3. `scripts/build_geojson.py` — reads raw province/municipality boundaries from `storage/data/geojson/` (HDX-style province export + a community municipality shapefile-turned-geojson that also bundles ~19 non-administrative protected-area polygons), joins each feature to a `palika_id`/`province_id` via a normalized-name match (province is a clean arithmetic join on `ADM1_PCODE`; municipality matching needs suffix-stripping, a district-name alias table for spelling drift, a fuzzy fallback, and a hand-reviewed `MANUAL_OVERRIDES`/`KNOWN_UNRESOLVABLE` dict for renames and historic spellings the automated passes can't resolve), and writes cleaned/rounded-precision geojson to `storage/processed/geojson/`. ~31 of 753 palikas currently have no matched geometry at all (source data gap, not a bug) — listed in the generated `storage/processed/geojson/unmatched_palikas.json` for future manual backfill. `nepal-districts-new.geojson` and `nepal-wards.geojson` (the latter is legacy pre-2017 VDC boundaries, not the current 6,743-ward system, and can't be joined to `palika_id`/`ward`) are left unprocessed — out of scope.
4. `lib/data.py`, `lib/tiers.py`, and `lib/geo.py` — read-only consumers of the processed output, used by both `main.py` and `notebooks/visualize_data.ipynb`. `lib/data.py` handles loading/joining (`load_palikas`, `load_election`) and defines the shared vocabulary (`POST_NAMES`, `HEAD_POST_IDS`, `HEAD_RACE_POST_IDS`, `WARD_CHAIR_POST_ID`, `WARD_RACE_POST_IDS`, `NC_PARTY_ID`). `lib/tiers.py` derives everything election-analysis-specific: `compute_head_race` (per-palika NC margin and tier), `compute_province_tier` (vote-weighted province-level aggregate of the same), `compute_ward_seats`, `head_race_detail`, `ward_detail`, `tier_counts`, `compute_tier_changes` + `tier_transition_matrix`, plus the tier color/order/text constants (`TIER_ORDER`, `TIER_COLORS`, `TIER_TEXT_ON_FILL`). `lib/geo.py` loads the processed geojson (cached) and builds per-rerun enriched `FeatureCollection`s (`enrich_municipalities`, `enrich_provinces`) with tier fill color/opacity/border/tooltip fields baked into each feature's properties, so `main.py` never does per-feature lookups.

`main.py` is a single-file Streamlit app with two tabs, both driven off the same sidebar (demo-mode toggle, year, palika-type filter, tier filter, search, sortable palika table):
- **Tier map** — a `folium`/`streamlit-folium` choropleth: a full-country province layer (always unfiltered, at reduced opacity — a backdrop that also shows through wherever a municipality has no matched geometry) under a municipality layer where each palika's real polygon is filled by tier color; sidebar-filtered-out palikas render muted rather than disappearing. Map clicks recover `palika_id` from the clicked feature's baked-in properties and take precedence over the sidebar-table selection, matching it in every other respect (same detail panel below the map, same stat tiles).
- **Tier changes** — a `year_old → year_new` tier-transition matrix (custom `Scatter` with square markers, not `go.Heatmap`, specifically so clicking a cell fires `on_select`) plus a filterable/sortable palika-level diff table (`compute_tier_changes`/`tier_transition_matrix`), only for palikas with a real tier in both years.

`demo_mode` (default on) restricts both tabs to a fixed 7-palika roster (`DEMO_PALIKA_IDS` in `main.py`) for presentation purposes — on the map this restricts the municipality layer to just those palikas (province backdrop stays full Nepal) and auto-zooms to their bounds. All expensive computation is wrapped in `@st.cache_data`.

### Data model specifics worth knowing before touching `lib/`

- Palika type (Metropolitan City / Sub-Metropolitan City / Municipality / Rural Municipality) is **not** a stored column — `lib/data._derive_palika_type` derives it from the `palika_name_en` suffix. The source data consistently misspells "Metropolitan" as "Metropolitian"; match order matters (`Sub-Metropolitian City` must be checked before `Metropolitian City`).
- Post IDs 1 (Chairperson) and 3 (Mayor) are mutually exclusive per palika — together they're the "head-of-palika" race the strategic tier is computed from (`HEAD_POST_IDS`); `HEAD_RACE_POST_IDS` additionally includes the deputy posts (2, 4) and is palika-wide (null `ward`). Post IDs 5–8 are ward-level races that every ward elects regardless of palika type. A handful of rows carry post IDs outside 1–8 that don't resolve against `posts.parquet`; `load_election` drops these rather than guessing.
- `election_2074` (2017) and `election_2079` (2022) both have near-complete coverage (752 and 753 of 753 palikas respectively have any record). A palika with no head-race data for the selected year renders as `NO_DATA_TIER` ("No data"), not assigned a win/loss tier.
- Strategic tier is derived purely from `margin = (NC votes - best opponent's votes) / race total votes` at `STRONGHOLD_MARGIN = 0.10`: Stronghold (>+10%), Narrow hold (0 to +10%), Near miss (0 to -10%), Opposition (<-10%). There is no coalition/alliance data in any source and no candidate nomination data — both are deliberately out of scope, not partially implemented.
- `candidate_name_en` is sometimes null; UI candidate tables display `pl.coalesce(candidate_name_en, candidate_name_np)` rather than assuming English is always present.
