from __future__ import annotations

import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "storage" / "processed"
ELECTION_DIR = ROOT / "storage" / "data" / "election_2079"

GENDER_EN = {"पुरुष": "male", "महिला": "female"}

CSV_RENAME = {
    "CandidateID": "candidate_id",
    "CandidateName": "candidate_name_np",
    "CandidateNameEng": "candidate_name_en",
    "Gender": "gender_np",
    "Age": "age",
    "PartyID": "party_id",
    "SymbolID": "symbol_id",
    "SymbolName": "symbol_name_np",
    "SymbolNameEng": "symbol_name_en",
    "PoliticalPartyName": "party_name_np",
    "PoliticalPartyNameEng": "party_name_en",
    "TotalVoteReceived": "total_votes",
    "Remarks": "remarks_np",
    "RemarksEng": "remarks_en",
    "PostId": "post_id",
    "Ward": "ward",
    "local_body_id": "palika_id",
}

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


def load_district_candidates(district_dir: Path) -> pl.DataFrame:
    with open(district_dir / "metadata.json") as f:
        meta = json.load(f)

    df = pl.read_csv(district_dir / "results.csv").rename(CSV_RENAME)
    df = df.with_columns(
        election=pl.lit(meta["election"]),
        district_name_en=pl.lit(meta["district_name"]),
        scraped_at=pl.lit(meta["scraped_at"]),
        gender_en=pl.col("gender_np").replace_strict(GENDER_EN),
    )
    return df


def main() -> None:
    districts = pl.read_parquet(PROCESSED_DIR / "districts.parquet")
    provinces = pl.read_parquet(PROCESSED_DIR / "provinces.parquet")

    frames = []
    for district_dir in sorted(p for p in ELECTION_DIR.iterdir() if p.is_dir()):
        df = load_district_candidates(district_dir)
        df = df.join(districts, on="district_name_en", how="left")
        df = df.join(provinces, on="province_id", how="left")
        frames.append(df)

    all_df = pl.concat(frames).select(COLUMNS)

    out_dir = PROCESSED_DIR / "election_2079"
    out_dir.mkdir(parents=True, exist_ok=True)
    for province_id, prov_df in all_df.group_by("province_id", maintain_order=True):
        province_id = province_id[0]
        name_en = prov_df["province_name_en"].first().replace(" ", "_").lower()
        out_path = out_dir / f"{province_id}_{name_en}.parquet"
        prov_df.write_parquet(out_path)
        print(f"wrote {out_path.name} ({prov_df.height} candidates)")


if __name__ == "__main__":
    main()