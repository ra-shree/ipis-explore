from __future__ import annotations

from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "storage" / "processed"

NC_PARTY_ID = 1

# post_id -> role, per storage/processed/posts.parquet. The election data also
# carries a handful of post_ids (9-12) that aren't defined in posts.parquet and
# don't resolve to a known role -- those are dropped everywhere below rather
# than guessed at.
POST_NAMES = {
    1: "Chairperson",
    2: "Vice-Chairperson",
    3: "Mayor",
    4: "Deputy Mayor",
    5: "Ward Chairperson",
    6: "Member",
    7: "Female Member",
    8: "Dalit Female Member",
}
KNOWN_POST_IDS = tuple(POST_NAMES)

# Head-of-palika race: Chairperson (rural municipalities) or Mayor (municipalities/
# metros) -- mutually exclusive per palika, exactly one of the two applies.
HEAD_POST_IDS = (1, 3)

# Ward-level races: every ward elects all four regardless of palika type.
WARD_CHAIR_POST_ID = 5
WARD_RACE_POST_IDS = (5, 6, 7, 8)

ELECTION_YEARS = (2079, 2074)


def available_years() -> list[int]:
    return [y for y in ELECTION_YEARS if (PROCESSED_DIR / f"election_{y}").exists()]


def _derive_palika_type() -> pl.Expr:
    # Source data misspells "Metropolitan" as "Metropolitian" throughout.
    name = pl.col("palika_name_en")
    return (
        pl.when(name.str.contains("Metropolitian City"))
        .then(pl.lit("Metropolitan City"))
        .when(name.str.contains("Sub-Metropolitian City"))
        .then(pl.lit("Sub-Metropolitan City"))
        .when(name.str.contains("Rural Municipality"))
        .then(pl.lit("Rural Municipality"))
        .otherwise(pl.lit("Municipality"))
    )


def load_palikas() -> pl.DataFrame:
    palikas = pl.read_parquet(PROCESSED_DIR / "palikas.parquet")
    districts = pl.read_parquet(PROCESSED_DIR / "districts.parquet")
    provinces = pl.read_parquet(PROCESSED_DIR / "provinces.parquet")

    df = palikas.join(districts, on="district_id", how="left")
    df = df.join(provinces, on="province_id", how="left")
    return df.with_columns(palika_type=_derive_palika_type())


def load_election(year: int) -> pl.DataFrame:
    year_dir = PROCESSED_DIR / f"election_{year}"
    frames = [pl.read_parquet(p) for p in sorted(year_dir.glob("*.parquet"))]
    df = pl.concat(frames)
    return df.filter(pl.col("post_id").is_in(KNOWN_POST_IDS))
