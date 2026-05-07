import pandas as pd

"""
/data/ is in .gitignore. Download your CSV dataset from Kaggle (or use your own)
and place it under data/. Install dependencies first: pip install -r requirements.txt
"""


def main():
    df = pd.read_csv("data/201801_Punctuality_Statistics_Full_Analysis.csv")
    # compression=None: Hue's bundled Parquet reader has historically failed on
    # snappy-compressed files ("Failed to read Parquet file"). Leave uncompressed
    # so the file uploads and previews cleanly via the Hue File Browser.
    df.to_parquet(
        path="data/201801_Punctuality_Statistics_Full_Analysis.parquet",
        engine="pyarrow",
        compression=None,
    )


if __name__ == "__main__":
    main()
