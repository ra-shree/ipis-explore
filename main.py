import polars as pl

def main():
    df = pl.read_parquet('storage/processed/election_2079/1_koshi_province.parquet')
    palika_df = pl.read_parquet('storage/processed/palikas.parquet')
    joint_df = df.join(palika_df, on='palika_id', how='left')
    result = (
        joint_df.group_by(['palika_id', 'palika_name_en', 'party_name_en'])
        .agg(pl.col('total_votes').sum())
        .sort(['palika_id', 'total_votes'], descending=[False, True])
    )
    print(result)


if __name__ == "__main__":
    main()
