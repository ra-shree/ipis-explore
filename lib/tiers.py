from __future__ import annotations

import polars as pl

from lib.data import (
    HEAD_POST_IDS,
    HEAD_RACE_POST_IDS,
    NC_PARTY_ID,
    WARD_CHAIR_POST_ID,
    WARD_RACE_POST_IDS,
)

# NC win/loss margin thresholds that define the strategic tier.
STRONGHOLD_MARGIN = 0.10

TIER_ORDER = ["Stronghold", "Narrow hold", "Near miss", "Opposition"]
NO_DATA_TIER = "No data"

# Status palette (dataviz skill): a fixed good -> warning -> serious -> critical
# scale, which is exactly what these four tiers are (win big -> win small ->
# lose small -> lose big). Same hex works on both light and dark surfaces.
TIER_COLORS = {
    "Stronghold": "#0ca30c",
    "Narrow hold": "#fab219",
    "Near miss": "#ec835a",
    "Opposition": "#d03b3b",
    NO_DATA_TIER: "#c3c2b7",
}
# Text color for a tier's colored badge/pill, picked for contrast against TIER_COLORS.
TIER_TEXT_ON_FILL = {
    "Stronghold": "#ffffff",
    "Narrow hold": "#0b0b0b",
    "Near miss": "#0b0b0b",
    "Opposition": "#ffffff",
    NO_DATA_TIER: "#0b0b0b",
}


def _tier_expr(margin: pl.Expr) -> pl.Expr:
    return (
        pl.when(margin > STRONGHOLD_MARGIN)
        .then(pl.lit("Stronghold"))
        .when(margin > 0)
        .then(pl.lit("Narrow hold"))
        .when(margin > -STRONGHOLD_MARGIN)
        .then(pl.lit("Near miss"))
        .otherwise(pl.lit("Opposition"))
    )


def compute_head_race(election: pl.DataFrame) -> pl.DataFrame:
    """One row per palika with any head-of-palika (Chairperson/Mayor) data.

    NC's margin = (NC votes - best non-NC party's votes) / race total votes.
    Positive means NC leads (win margin); negative means NC trails (loss margin) --
    a single formula handles both win and loss without branching on who won.
    """
    head = election.filter(pl.col("post_id").is_in(HEAD_POST_IDS))

    by_party = head.group_by(["palika_id", "party_id", "party_name_en"]).agg(
        pl.col("total_votes").sum()
    )

    race_totals = by_party.group_by("palika_id").agg(
        pl.col("total_votes").sum().alias("race_total_votes")
    )

    nc = by_party.filter(pl.col("party_id") == NC_PARTY_ID).select(
        "palika_id", pl.col("total_votes").alias("nc_votes")
    )

    best_opponent = (
        by_party.filter(pl.col("party_id") != NC_PARTY_ID)
        .sort("total_votes", descending=True)
        .group_by("palika_id", maintain_order=True)
        .agg(
            pl.col("party_name_en").first().alias("opponent_party"),
            pl.col("total_votes").first().alias("opponent_votes"),
        )
    )

    leader = (
        by_party.sort("total_votes", descending=True)
        .group_by("palika_id", maintain_order=True)
        .agg(pl.col("party_name_en").first().alias("leader_party"))
    )

    result = (
        race_totals.join(nc, on="palika_id", how="left")
        .join(best_opponent, on="palika_id", how="left")
        .join(leader, on="palika_id", how="left")
        .with_columns(
            pl.col("nc_votes").fill_null(0),
            pl.col("opponent_votes").fill_null(0),
        )
        .with_columns(
            margin=pl.when(pl.col("race_total_votes") > 0)
            .then((pl.col("nc_votes") - pl.col("opponent_votes")) / pl.col("race_total_votes"))
            .otherwise(0.0)
        )
        .with_columns(tier=_tier_expr(pl.col("margin")))
    )
    return result


def compute_ward_seats(election: pl.DataFrame, palikas: pl.DataFrame) -> pl.DataFrame:
    """Per palika: NC-won Ward Chairperson seats vs. total wards decided."""
    chairs = election.filter(
        (pl.col("post_id") == WARD_CHAIR_POST_ID) & pl.col("remarks_en").is_in(["Elected", "Unopposed"])
    )

    nc_seats = (
        chairs.filter(pl.col("party_id") == NC_PARTY_ID)
        .group_by("palika_id")
        .agg(pl.len().alias("nc_ward_seats"))
    )
    decided = chairs.group_by("palika_id").agg(pl.len().alias("ward_seats_decided"))

    return (
        palikas.select("palika_id", "total_wards")
        .join(nc_seats, on="palika_id", how="left")
        .join(decided, on="palika_id", how="left")
        .with_columns(
            pl.col("nc_ward_seats").fill_null(0),
            pl.col("ward_seats_decided").fill_null(0),
        )
    )


def _elected_expr() -> pl.Expr:
    # fill_null(False): is_in() returns null (not False) for null remarks_en,
    # and nulls sort last regardless of descending -- without this, unelected
    # candidates with no remarks would silently outrank the elected one.
    return pl.col("remarks_en").is_in(["Elected", "Unopposed"]).fill_null(False)


def head_race_detail(election: pl.DataFrame, palika_id: int) -> pl.DataFrame:
    """Elected candidate plus the next 4 highest-vote candidates, per post, for
    the head-of-palika race (Chairperson/Vice-Chairperson or Mayor/Deputy
    Mayor) of one palika.

    This race is palika-wide, not per-ward -- its rows carry a null `ward`,
    so it's never reachable through ward_detail()'s ward filter.
    """
    detail = election.filter(
        (pl.col("palika_id") == palika_id) & pl.col("post_id").is_in(HEAD_RACE_POST_IDS)
    ).sort(["post_id", _elected_expr(), "total_votes"], descending=[False, True, True])
    return detail.filter(pl.int_range(pl.len()).over("post_id") < 5)


def ward_detail(election: pl.DataFrame, palika_id: int, ward: int) -> pl.DataFrame:
    """Candidate-level results for every ward-level race in one ward of one
    palika, elected candidate first within each post."""
    return election.filter(
        (pl.col("palika_id") == palika_id)
        & (pl.col("ward") == ward)
        & pl.col("post_id").is_in(WARD_RACE_POST_IDS)
    ).sort(["post_id", _elected_expr(), "total_votes"], descending=[False, True, True])


def compute_province_tier(head_race: pl.DataFrame) -> pl.DataFrame:
    """One row per province_id: race_total_votes-weighted average NC margin
    across that province's palikas, excluding NO_DATA_TIER palikas from the
    weighting, bucketed with the same _tier_expr thresholds as the palika-
    level tier. Expects `head_race` to already carry `province_id` and
    `race_total_votes` (i.e. the output of get_head_race(year), not raw
    compute_head_race()).
    """
    weighted = head_race.filter(pl.col("tier") != NO_DATA_TIER)
    agg = weighted.group_by("province_id").agg(
        margin=(pl.col("margin") * pl.col("race_total_votes")).sum() / pl.col("race_total_votes").sum()
    )
    return agg.with_columns(tier=_tier_expr(pl.col("margin")))


def tier_counts(head_race: pl.DataFrame) -> dict[str, int]:
    counts = head_race.group_by("tier").agg(pl.len().alias("count"))
    lookup = dict(zip(counts["tier"].to_list(), counts["count"].to_list()))
    return {tier: lookup.get(tier, 0) for tier in TIER_ORDER}


def compute_tier_changes(old_head_race: pl.DataFrame, new_head_race: pl.DataFrame) -> pl.DataFrame:
    """Per-palika tier movement between two elections' head-race results.

    Restricted to palikas with a real tier in both years -- 2074 has no
    Madhesh Province data, so those palikas have no old-year tier to diff.
    """
    tier_rank = {tier: i for i, tier in enumerate(TIER_ORDER)}

    old = old_head_race.filter(pl.col("tier") != NO_DATA_TIER).select(
        "palika_id",
        pl.col("tier").alias("tier_old"),
        pl.col("margin").alias("margin_old"),
    )
    new = new_head_race.filter(pl.col("tier") != NO_DATA_TIER).select(
        "palika_id",
        pl.col("tier").alias("tier_new"),
        pl.col("margin").alias("margin_new"),
    )

    return old.join(new, on="palika_id", how="inner").with_columns(
        # Positive = moved toward Stronghold (improved for NC); negative = toward Opposition.
        shift=pl.col("tier_old").replace_strict(tier_rank) - pl.col("tier_new").replace_strict(tier_rank),
        margin_change=pl.col("margin_new") - pl.col("margin_old"),
    )


def tier_transition_matrix(changes: pl.DataFrame) -> pl.DataFrame:
    """Dense palika counts for every (old tier, new tier) pair, in TIER_ORDER."""
    counts = changes.group_by(["tier_old", "tier_new"]).agg(pl.len().alias("count"))
    lookup = dict(zip(zip(counts["tier_old"], counts["tier_new"]), counts["count"].to_list()))
    return pl.DataFrame(
        [
            {"tier_old": old, "tier_new": new, "count": lookup.get((old, new), 0)}
            for old in TIER_ORDER
            for new in TIER_ORDER
        ]
    )
