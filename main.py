from __future__ import annotations

import random

import plotly.graph_objects as go
import polars as pl
import streamlit as st

from lib.data import POST_NAMES, available_years, load_election, load_palikas
from lib.tiers import (
    NO_DATA_TIER,
    TIER_COLORS,
    TIER_ORDER,
    TIER_TEXT_ON_FILL,
    compute_head_race,
    compute_ward_seats,
    tier_counts,
    ward_detail,
)

st.set_page_config(page_title="Nepal — Palika strategic tier map", layout="wide")

PALIKA_TYPES = ["Metropolitan City", "Sub-Metropolitan City", "Municipality", "Rural Municipality"]
MUTED_TEXT = "#898781"


# ---------------------------------------------------------------------------
# Cached data loading / derivation
# ---------------------------------------------------------------------------


@st.cache_data
def get_palikas() -> pl.DataFrame:
    return load_palikas()


@st.cache_data
def get_election(year: int) -> pl.DataFrame:
    return load_election(year)


@st.cache_data
def get_head_race(year: int) -> pl.DataFrame:
    palikas = get_palikas()
    race = compute_head_race(get_election(year))
    joined = palikas.join(race, on="palika_id", how="left")
    return joined.with_columns(
        pl.col("tier").fill_null(NO_DATA_TIER),
        pl.col("margin").fill_null(0.0),
    )


@st.cache_data
def get_ward_seats(year: int) -> pl.DataFrame:
    return compute_ward_seats(get_election(year), get_palikas())


@st.cache_data
def get_layout_coords(palika_ids: tuple[int, ...]) -> dict[int, tuple[float, float]]:
    # Stable pseudo-random position per palika (no geographic data exists, and
    # the mockup this is modeled on isn't a real map either) -- seeded on
    # palika_id so points don't jump around between filters/reruns.
    coords = {}
    for pid in palika_ids:
        rng = random.Random(pid)
        coords[pid] = (rng.uniform(0, 1), rng.uniform(0, 1))
    return coords


def tier_badge(tier: str) -> str:
    bg = TIER_COLORS[tier]
    fg = TIER_TEXT_ON_FILL[tier]
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 10px;'
        f'border-radius:999px;font-size:0.8rem;font-weight:600;">{tier}</span>'
    )


def stat_tile(col, label: str, value: int, tier: str) -> None:
    with col:
        st.markdown(
            f'<div style="border:1px solid rgba(11,11,11,0.10);border-radius:8px;'
            f'padding:12px 16px;text-align:center;">'
            f'<div style="font-size:1.8rem;font-weight:600;color:{TIER_COLORS[tier]};">{value}</div>'
            f'<div style="color:{MUTED_TEXT};font-size:0.85rem;">{label}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )


def format_pct(margin: float) -> str:
    sign = "+" if margin >= 0 else ""
    return f"{sign}{margin * 100:.1f}%"


# ---------------------------------------------------------------------------
# Sidebar — year, filters, search, palika list
# ---------------------------------------------------------------------------

years = available_years()
st.sidebar.markdown("### Election year")
year = st.sidebar.segmented_control("Election year", years, default=years[0], label_visibility="collapsed")
if year is None:
    year = years[0]

head_race = get_head_race(year)

st.sidebar.markdown("### Palika type")
type_filter = st.sidebar.segmented_control(
    "Palika type", PALIKA_TYPES, default=None, selection_mode="multi", label_visibility="collapsed"
)

st.sidebar.markdown("### Tier")
tier_filter = st.sidebar.segmented_control(
    "Tier", TIER_ORDER, default=None, selection_mode="multi", label_visibility="collapsed"
)

search = st.sidebar.text_input("Search palika (Nepali or English name)", "")

filtered = head_race
if type_filter:
    filtered = filtered.filter(pl.col("palika_type").is_in(type_filter))
if tier_filter:
    filtered = filtered.filter(pl.col("tier").is_in(tier_filter))
if search.strip():
    needle = search.strip().lower()
    filtered = filtered.filter(
        pl.col("palika_name_en").str.to_lowercase().str.contains(needle, literal=True)
        | pl.col("palika_name_np").str.contains(needle, literal=True)
    )

counts = tier_counts(filtered)

st.sidebar.markdown(f"**{filtered.height} / {head_race.height} palikas**")

sidebar_table = filtered.select(
    pl.col("palika_name_en").alias("Palika"),
    pl.col("province_name_en").alias("Province"),
    pl.col("tier").alias("Tier"),
).sort("Palika")

sidebar_event = st.sidebar.dataframe(
    sidebar_table,
    hide_index=True,
    width="stretch",
    height=420,
    on_select="rerun",
    selection_mode="single-row",
)

selected_palika_id: int | None = None
selected_rows = sidebar_event.selection.rows if sidebar_event.selection else []
if selected_rows:
    selected_name = sidebar_table["Palika"][selected_rows[0]]
    selected_palika_id = filtered.filter(pl.col("palika_name_en") == selected_name)["palika_id"][0]


# ---------------------------------------------------------------------------
# Main panel — scatter, stat tiles, detail
# ---------------------------------------------------------------------------

st.markdown(f"## Nepal — Palika strategic tier map <span style='color:{MUTED_TEXT};font-size:1rem;'>({year})</span>", unsafe_allow_html=True)
st.caption(f"{filtered.height} of {head_race.height} palikas shown")

# Coordinates are seeded on the full palika set so a point's position stays
# fixed as filters change -- filtering removes dots rather than reshuffling them.
coords = get_layout_coords(tuple(head_race["palika_id"].to_list()))
xs = [coords[pid][0] for pid in filtered["palika_id"]]
ys = [coords[pid][1] for pid in filtered["palika_id"]]
plot_df = filtered.with_columns(x=pl.Series(xs), y=pl.Series(ys))

fig = go.Figure()
for tier in [*TIER_ORDER, NO_DATA_TIER]:
    tdf = plot_df.filter(pl.col("tier") == tier)
    if tdf.height == 0:
        continue
    is_selected = tdf["palika_id"] == selected_palika_id if selected_palika_id else None
    marker_line = (
        [3 if pid == selected_palika_id else 1 for pid in tdf["palika_id"]]
        if selected_palika_id
        else 1
    )
    fig.add_trace(
        go.Scatter(
            x=tdf["x"],
            y=tdf["y"],
            mode="markers",
            name=tier,
            marker=dict(
                size=14,
                color=TIER_COLORS[tier],
                line=dict(width=marker_line, color="#fcfcfb"),
                opacity=0.9,
            ),
            customdata=tdf.select(
                "palika_name_en", "province_name_en", "tier", "margin", "palika_id"
            ).to_numpy(),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "%{customdata[1]}<br>"
                "%{customdata[2]} · margin %{customdata[3]:+.1%}"
                "<extra></extra>"
            ),
        )
    )

fig.update_layout(
    height=440,
    margin=dict(l=10, r=10, t=10, b=10),
    xaxis=dict(visible=False),
    yaxis=dict(visible=False),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    plot_bgcolor="#fcfcfb",
    paper_bgcolor="#fcfcfb",
)

click_event = st.plotly_chart(fig, width="stretch", on_select="rerun", selection_mode="points")
if click_event and click_event.selection and click_event.selection.points:
    point = click_event.selection.points[0]
    selected_palika_id = int(point["customdata"][4])

cols = st.columns(4)
for col, tier in zip(cols, TIER_ORDER):
    stat_tile(col, tier, counts[tier], tier)

st.divider()

if selected_palika_id is None:
    st.info("Select a palika from the sidebar list or the map to see details.")
else:
    row = head_race.filter(pl.col("palika_id") == selected_palika_id).row(0, named=True)
    seats_row = get_ward_seats(year).filter(pl.col("palika_id") == selected_palika_id)
    nc_seats = seats_row["nc_ward_seats"][0] if seats_row.height else 0
    total_wards = row["total_wards"]

    st.markdown(
        f"### {row['palika_name_en']} <span style='color:{MUTED_TEXT};font-size:1rem;'>· {row['palika_name_np']}</span>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"{row['province_name_en']} Province · {row['district_name_en'].title()} District · "
        f"{total_wards} wards · {row['palika_type']}  &nbsp; {tier_badge(row['tier'])}",
        unsafe_allow_html=True,
    )

    detail_cols = st.columns(4)
    with detail_cols[0]:
        st.metric(f"{year} margin (NC)", format_pct(row["margin"]) if row["tier"] != NO_DATA_TIER else "No data")
    with detail_cols[1]:
        st.metric("Primary competitor", row["opponent_party"] or "—")
    with detail_cols[2]:
        st.metric("Ward seats (NC)", f"{nc_seats} / {total_wards}")
    with detail_cols[3]:
        st.metric("Leader", row["leader_party"] or "—")

    st.markdown("#### Ward detail")
    ward_options = list(range(1, total_wards + 1))
    ward = st.selectbox("Ward", ward_options, key=f"ward-{selected_palika_id}")

    ward_df = ward_detail(get_election(year), selected_palika_id, ward)
    if ward_df.height == 0:
        st.caption("No candidate data for this ward.")
    else:
        display = ward_df.select(
            pl.col("post_id").replace_strict(POST_NAMES).alias("Post"),
            pl.col("candidate_name_en").alias("Candidate"),
            pl.col("party_name_en").alias("Party"),
            pl.col("total_votes").alias("Votes"),
            pl.col("remarks_en").fill_null("—").alias("Result"),
        )
        st.dataframe(display, hide_index=True, width="stretch")
