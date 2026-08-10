# IPIS Explore

Data pipeline and Streamlit dashboard for exploring Nepal's local-level election
results (2074/2017 and 2079/2022), built around a Nepali Congress strategic-tier
view of the country's 753 palikas (local government units).

## Project structure

```
ipis-explore/
├── main.py                    # Streamlit dashboard
├── lib/
│   ├── data.py                 # Loading and joining processed parquet data
│   └── tiers.py                 # Margin, tier, and ward-seat computation
├── scripts/
│   ├── build_parquet.py         # Builds reference tables (parties, posts, symbols,
│   │                             #   provinces, districts, palikas) from raw JSON
│   ├── process_elections.py     # Builds election_2079 parquet from per-district CSV/JSON
│   └── process_election_2074.py # Builds election_2074 parquet from per-province JSON
├── notebooks/
│   └── visualize_data.ipynb     # Ad-hoc data exploration
└── storage/
    ├── data/                    # Raw scraped data (git-ignored)
    └── processed/                # Pipeline output consumed by the dashboard (git-ignored)
```

`storage/` is git-ignored in its entirety; all data is local-only. Run the
scripts in `scripts/` to (re)generate `storage/processed/` from `storage/data/`.

## Running the dashboard

```bash
uv run streamlit run main.py
```

## Data

### Reference tables (`storage/processed/`)

| File | Rows | Description |
|---|---|---|
| `palikas.parquet` | 753 | `palika_id, palika_name_np, palika_name_en, district_id, total_wards` |
| `districts.parquet` | 77 | `district_id, district_name_np, district_name_en, province_id` |
| `provinces.parquet` | 7 | `province_id, province_name_np, province_name_en` |
| `parties.parquet` | 24 | `party_id, party_name_np, party_name_en` |
| `posts.parquet` | 8 | `post_id, post_name_np, post_name_en` |

Palika type (Metropolitan City / Sub-Metropolitan City / Municipality / Rural
Municipality) is not a stored column — it is derived from the `palika_name_en`
suffix (`lib/data.py`). Note the source data consistently misspells
"Metropolitan" as "Metropolitian".

### Election results (`storage/processed/election_2079/`, `election_2074/`)

Candidate-level results, one parquet per province:

- `election_2079` (2022) — all 7 provinces, 152,960 rows, complete coverage of
  all 753 palikas.
- `election_2074` (2017) — 6 of 7 provinces; Madhesh Province is absent from
  the raw source entirely. 616 of 753 palikas have any 2074 record.

Key columns: `candidate_id, candidate_name_np/en, party_id, party_name_np/en,
post_id, ward, total_votes, remarks_np/en (elected/unopposed flag), palika_id,
district_id, province_id`.

Post IDs used by the dashboard (`lib/data.py:POST_NAMES`):

| post_id | Role | Scope |
|---|---|---|
| 1 | Chairperson | Rural Municipality head |
| 2 | Vice-Chairperson | Rural Municipality |
| 3 | Mayor | Municipality / Sub-Metropolitan / Metropolitan head |
| 4 | Deputy Mayor | Municipality / Sub-Metropolitan / Metropolitan |
| 5 | Ward Chairperson | Ward-level, every palika |
| 6 | Member | Ward-level |
| 7 | Female Member | Ward-level |
| 8 | Dalit Female Member | Ward-level |

Post IDs 1 and 3 are mutually exclusive per palika (a palika elects one or the
other, never both) and together form the "head-of-palika" race the strategic
tier is based on. A handful of rows carry post IDs outside 1-8 that do not
resolve against `posts.parquet`; these are excluded rather than guessed at.

## Strategic tier methodology

Each palika is classified from its head-of-palika race (Chairperson or Mayor,
whichever applies), based on Nepali Congress's margin against the strongest
non-NC party:

```
margin = (NC votes - best opponent's votes) / race total votes
```

| Tier | Condition |
|---|---|
| Stronghold | NC wins by more than 10% |
| Narrow hold | NC wins by 10% or less |
| Near miss | NC loses by 10% or less |
| Opposition | NC loses by more than 10% |

A palika with no head-race data for the selected year (e.g. Madhesh Province
under 2074) is reported as "No data" rather than assigned a tier.

Ward seat counts (e.g. "NC 21/33") come from Ward Chairperson (post_id 5)
results only, counted per palika.

### Known gaps / deliberately out of scope

- No coalition or pre-poll alliance data exists in any source; the "Coalition"
  tier from the original mockup is not implemented.
- No candidate nomination/application data exists; that field from the
  original mockup is not implemented.
- Wards have no name field in the data, only numbers — ward navigation is by
  palika name/type first, then ward number.
- A small number of candidate rows have a null `party_name_en` (likely
  independents where the scrape left the field blank).
