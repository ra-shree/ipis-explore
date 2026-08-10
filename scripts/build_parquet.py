from __future__ import annotations

import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "storage" / "data"
OUT_DIR = ROOT / "storage" / "processed"

PARTY_COLUMNS = ["party_id", "party_name_np", "party_name_en"]
POST_COLUMNS = ["post_id", "post_name_np", "post_name_en"]
SYMBOL_COLUMNS = ["symbol_id", "symbol_name_np", "symbol_name_en"]
PROVINCE_COLUMNS = ["province_id", "province_name_np", "province_name_en"]
DISTRICT_COLUMNS = ["district_id", "district_name_np", "district_name_en", "province_id"]
PALIKA_COLUMNS = ["palika_id", "palika_name_np", "palika_name_en", "district_id", "total_wards"]

TABLES = [
    {
        "name": "parties",
        "source": DATA_DIR / "parties.json",
        "rename": {
            "PartyID": "party_id",
            "PoliticalPartyName": "party_name_np",
            "PoliticalPartyNameEng": "party_name_en",
        },
        "columns": PARTY_COLUMNS,
    },
    {
        "name": "posts",
        "source": DATA_DIR / "posts.json",
        "rename": {
            "PostId": "post_id",
            "PostName": "post_name_np",
            "PostNameEng": "post_name_en",
        },
        "columns": POST_COLUMNS,
    },
    {
        "name": "symbols",
        "source": DATA_DIR / "symbols.json",
        "rename": {
            "SymbolID": "symbol_id",
            "SymbolName": "symbol_name_np",
            "SymbolNameEng": "symbol_name_en",
        },
        "columns": SYMBOL_COLUMNS,
    },
    {
        "name": "provinces",
        "source": DATA_DIR / "locations" / "provinces.json",
        "rename": {"id": "province_id", "name_np": "province_name_np", "name_en": "province_name_en"},
        "columns": PROVINCE_COLUMNS,
    },
    {
        "name": "districts",
        "source": DATA_DIR / "locations" / "districts.json",
        "rename": {"id": "district_id", "name_np": "district_name_np", "name_en": "district_name_en", "parentId": "province_id"},
        "columns": DISTRICT_COLUMNS,
    },
    {
        "name": "palikas",
        "source": DATA_DIR / "locations" / "palikas.json",
        "rename": {"id": "palika_id", "name_np": "palika_name_np", "name_en": "palika_name_en", "parentId": "district_id"},
        "columns": PALIKA_COLUMNS,
    },
]


def build_table(spec: dict) -> pl.DataFrame:
    with open(spec["source"]) as f:
        records = json.load(f)
    df = pl.DataFrame(records)
    df = df.rename(spec["rename"])
    return df.select(spec["columns"]).sort(spec["columns"][0])


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for spec in TABLES:
        df = build_table(spec)
        out_path = OUT_DIR / f"{spec['name']}.parquet"
        df.write_parquet(out_path)
        print(f"wrote {out_path} ({df.height} rows, {', '.join(df.columns)})")


if __name__ == "__main__":
    main()
