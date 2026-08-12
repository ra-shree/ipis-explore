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
```

There is no lint/typecheck/test tooling configured in this repo (no ruff/mypy/pytest in `pyproject.toml`).

`storage/` is entirely git-ignored (both `storage/data/` raw input and `storage/processed/` pipeline output) — all data is local-only and must be regenerated or fetched separately, not assumed to be present.

## Architecture

**Pipeline → parquet → dashboard**, three independent stages that only communicate through `storage/processed/*.parquet`:

1. `scripts/build_parquet.py` — table-driven (a `TABLES` list of `{name, source, rename, columns}` specs) conversion of reference JSON (`parties.json`, `posts.json`, `symbols.json`, `storage/data/locations/*.json`) into flat reference parquet tables.
2. `scripts/process_elections.py` / `scripts/process_election_2074.py` — read raw per-district (2079) or per-province (2074) scrape output, join in district/province names via the reference parquets from step 1, and write one parquet per province into `storage/processed/election_{year}/`. The two years have structurally different raw sources (CSV+metadata.json per district vs. JSON per province) hence separate scripts, but converge on the same output schema/columns.
3. `lib/data.py` and `lib/tiers.py` — read-only consumers of the processed parquet, used by both `main.py` and `notebooks/visualize_data.ipynb`. `lib/data.py` handles loading/joining (`load_palikas`, `load_election`) and defines the shared vocabulary (`POST_NAMES`, `HEAD_POST_IDS`, `WARD_RACE_POST_IDS`, `NC_PARTY_ID`). `lib/tiers.py` derives everything election-analysis-specific on top: `compute_head_race` (per-palika NC margin and tier), `compute_ward_seats`, `ward_detail`, plus the tier color/order constants (`TIER_ORDER`, `TIER_COLORS`) used for both the plot and stat tiles.

`main.py` is a single-file Streamlit app: sidebar (year/type/tier filters, search, palika table) drives a `polars` filter applied to the cached `get_head_race(year)` frame, which feeds a Plotly scatter (positions are a stable per-`palika_id` pseudo-random layout since there's no real geographic data) and a detail panel with ward-level candidate results. All expensive computation is wrapped in `@st.cache_data`.

### Data model specifics worth knowing before touching `lib/`

- Palika type (Metropolitan City / Sub-Metropolitan City / Municipality / Rural Municipality) is **not** a stored column — `lib/data._derive_palika_type` derives it from the `palika_name_en` suffix. The source data consistently misspells "Metropolitan" as "Metropolitian"; match order matters (`Sub-Metropolitian City` must be checked before `Metropolitian City`).
- Post IDs 1 (Chairperson) and 3 (Mayor) are mutually exclusive per palika — together they're the "head-of-palika" race the strategic tier is computed from (`HEAD_POST_IDS`). Post IDs 5–8 are ward-level races that every ward elects regardless of palika type. A handful of rows carry post IDs outside 1–8 that don't resolve against `posts.parquet`; `load_election` drops these rather than guessing.
- `election_2074` (2017) and `election_2079` (2022) both have near-complete coverage (752 and 753 of 753 palikas respectively have any record). A palika with no head-race data for the selected year renders as `NO_DATA_TIER` ("No data"), not assigned a win/loss tier.
- Strategic tier is derived purely from `margin = (NC votes - best opponent's votes) / race total votes` at `STRONGHOLD_MARGIN = 0.10`: Stronghold (>+10%), Narrow hold (0 to +10%), Near miss (0 to -10%), Opposition (<-10%). There is no coalition/alliance data in any source and no candidate nomination data — both are deliberately out of scope, not partially implemented.
