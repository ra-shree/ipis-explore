from __future__ import annotations

import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "storage" / "data" / "election_2074"
OUT_DIR = ROOT / "storage" / "processed" / "election_2074"

COLUMNS = [
    "election",
    "candidate_id",
    "candidate_name_np",
    "candidate_name_en",
    "gender_np",
    "gender_en",
    "age",
    "party_id",
    "party_name_np",
    "party_name_en",
    "symbol_id",
    "symbol_name_np",
    "symbol_name_en",
    "post_id",
    "ward",
    "total_votes",
    "remarks_np",
    "remarks_en",
    "palika_id",
    "district_id",
    "district_name_np",
    "district_name_en",
    "province_id",
    "province_name_np",
    "province_name_en",
    "scraped_at",
]

INT_COLUMNS = {
    "candidate_id",
    "age",
    "party_id",
    "symbol_id",
    "post_id",
    "ward",
    "total_votes",
    "palika_id",
    "district_id",
    "province_id",
}

SCHEMA = {col: (pl.Int64 if col in INT_COLUMNS else pl.Utf8) for col in COLUMNS if col != "election"}
SCHEMA["election"] = pl.Int64


def load_province_candidates(json_path: Path) -> pl.DataFrame:
    with open(json_path, encoding="utf-8") as f:
        records = json.load(f)

    df = pl.DataFrame(records, schema=SCHEMA)
    df = df.with_columns(
        election=pl.lit("election_2074"),
        gender_en=pl.col("gender_en").str.to_lowercase(),
    )
    return df.select(COLUMNS)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_paths = sorted(DATA_DIR.glob("province_*.json"))

    for json_path in json_paths:
        df = load_province_candidates(json_path)

        province_id = df["province_id"].first()
        name_en = df["province_name_en"].first().replace(" ", "_").lower()
        out_path = OUT_DIR / f"{province_id}_{name_en}.parquet"

        df.write_parquet(out_path)
        print(f"wrote {out_path.name} ({df.height} candidates)")


if __name__ == "__main__":
    main()
