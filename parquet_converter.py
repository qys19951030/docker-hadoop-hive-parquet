#!/usr/bin/env python3
"""
CSV -> Parquet -> Hive DDL semi-automated import tool.

Converts a local CSV file to uncompressed Parquet, auto-detects the schema
from the CSV, and generates a ready-to-run CREATE EXTERNAL TABLE statement
for Hive/Hue, plus an upload script to push the Parquet file into HDFS.
"""

import argparse
import io
import os
import sys
from pathlib import Path


_encoding = getattr(sys.stdout, "encoding", None) or "ascii"
_supports_unicode = _encoding.lower() in ("utf-8", "utf8", "cp65001")


def _s(unicode_val: str, ascii_val: str) -> str:
    """Return unicode_val if the terminal supports it, otherwise ascii_val."""
    return unicode_val if _supports_unicode else ascii_val


CHECK = _s("\u2713", "OK")
ARROW = _s("\u2192", "->")
TIMES = _s("\u00d7", "x")


PANDAS_TO_HIVE = {
    "int8": "TINYINT",
    "int16": "SMALLINT",
    "int32": "INT",
    "int64": "BIGINT",
    "uint8": "SMALLINT",
    "uint16": "INT",
    "uint32": "BIGINT",
    "uint64": "BIGINT",
    "float32": "FLOAT",
    "float64": "DOUBLE",
    "bool": "BOOLEAN",
    "datetime64[ns]": "TIMESTAMP",
    "datetime64[ns, tz]": "TIMESTAMP",
    "timedelta[ns]": "INTERVAL",
    "object": "STRING",
    "category": "STRING",
    "string": "STRING",
}


def _configure_stdout_encoding():
    """Try to force UTF-8 on stdout to avoid UnicodeEncodeError on Windows."""
    if sys.version_info >= (3, 7):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
            global _supports_unicode
            _supports_unicode = True
            return True
        except Exception:
            pass
    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace"
        )
        _supports_unicode = True
        return True
    except Exception:
        return False


_configure_stdout_encoding()

import pandas as pd


def map_dtype(dtype) -> str:
    """Map a pandas dtype to a Hive data type."""
    dtype_str = str(dtype)
    if dtype_str in PANDAS_TO_HIVE:
        return PANDAS_TO_HIVE[dtype_str]
    if dtype_str.startswith("datetime64"):
        return "TIMESTAMP"
    if dtype_str.startswith("int"):
        return "BIGINT"
    if dtype_str.startswith("float"):
        return "DOUBLE"
    return "STRING"


def sanitize_column(name: str) -> str:
    """Normalize a column name to a Hive-friendly identifier."""
    cleaned = name.strip().lower().replace(" ", "_").replace("-", "_").replace(".", "_")
    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in cleaned)
    if cleaned and cleaned[0].isdigit():
        cleaned = "col_" + cleaned
    return cleaned or "col"


def infer_schema(df: pd.DataFrame) -> list[tuple[str, str, str]]:
    """Infer Hive schema from a DataFrame.

    Returns list of (original_name, hive_name, hive_type).
    """
    schema = []
    seen = set()
    for col in df.columns:
        hive_col = sanitize_column(col)
        orig_hive_col = hive_col
        i = 2
        while hive_col in seen:
            hive_col = f"{orig_hive_col}_{i}"
            i += 1
        seen.add(hive_col)
        hive_type = map_dtype(df[col].dtype)
        schema.append((col, hive_col, hive_type))
    return schema


def generate_ddl(
    table_name: str,
    schema: list[tuple[str, str, str]],
    hdfs_path: str,
    comment: str = "",
) -> str:
    """Generate a Hive CREATE EXTERNAL TABLE DDL statement."""
    lines = []
    lines.append(f"CREATE EXTERNAL TABLE IF NOT EXISTS {table_name} (")
    col_lines = []
    for orig, hive_col, hive_type in schema:
        col_comment = f"  COMMENT '{orig}'" if orig != hive_col else ""
        col_lines.append(f"  {hive_col} {hive_type}{col_comment}")
    lines.append(",\n".join(col_lines))
    lines.append(")")
    if comment:
        escaped_comment = comment.replace("'", "\\'")
        lines.append(f"COMMENT '{escaped_comment}'")
    lines.append("STORED AS PARQUET")
    lines.append(f"LOCATION '{hdfs_path}'")
    lines.append(";")
    return "\n".join(lines)


def convert_csv_to_parquet(
    csv_path: str,
    parquet_path: str,
    compression: str = "none",
    csv_encoding: str = "utf-8",
) -> pd.DataFrame:
    """Convert CSV to Parquet. Returns the DataFrame for schema inference."""
    df = pd.read_csv(csv_path, encoding=csv_encoding)
    parquet_dir = os.path.dirname(parquet_path)
    if parquet_dir:
        os.makedirs(parquet_dir, exist_ok=True)
    df.to_parquet(
        path=parquet_path,
        engine="pyarrow",
        compression=None if compression == "none" else compression,
        index=False,
    )
    return df


def _to_posix_path(path_str: str) -> str:
    """Convert a native path to POSIX (forward-slash) form for docker commands."""
    return path_str.replace(os.sep, "/")


def generate_upload_script(
    parquet_path: str,
    hdfs_path: str,
    container: str = "namenode",
    script_path: str = None,
) -> str:
    """Generate a cross-platform bash script to upload Parquet to HDFS.

    The script uses a path relative to its own location so it works regardless
    of where the user runs it from.
    """
    parquet_file = os.path.basename(parquet_path)

    if script_path:
        script_dir = os.path.dirname(os.path.abspath(script_path))
        parquet_abs = os.path.abspath(parquet_path)
        try:
            rel_path = os.path.relpath(parquet_abs, script_dir)
        except ValueError:
            rel_path = parquet_abs
        rel_parquet = _to_posix_path(rel_path)
    else:
        rel_parquet = _to_posix_path(os.path.relpath(parquet_path, "."))

    lines = [
        "#!/usr/bin/env bash",
        "#",
        "# Upload a Parquet file to HDFS via docker.",
        "#",
        "# Usage: bash <this-script>",
        "# Run from the repository root (or wherever your relative paths make sense).",
        "#",
        f"# Parquet file (relative to this script's directory): {rel_parquet}",
        f"# HDFS target directory:                    {hdfs_path}",
        f"# Docker container for hdfs commands:       {container}",
        "",
        'set -euo pipefail',
        "",
        '# Resolve the directory containing this script so relative paths work',
        '# regardless of the user\'s cwd.',
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        f'PARQUET_FILE="${{SCRIPT_DIR}}/{rel_parquet}"',
        f'PARQUET_BASENAME="{parquet_file}"',
        f'HDFS_PATH="{hdfs_path}"',
        f'CONTAINER="{container}"',
        "",
        'if [ ! -f "$PARQUET_FILE" ]; then',
        '  echo "ERROR: Parquet file not found: $PARQUET_FILE" >&2',
        '  exit 1',
        'fi',
        "",
        'echo "==> Copying $PARQUET_FILE into $CONTAINER:/tmp/$PARQUET_BASENAME"',
        f'docker cp "$PARQUET_FILE" "${{CONTAINER}}:/tmp/${{PARQUET_BASENAME}}"',
        "",
        'echo "==> Creating HDFS directory $HDFS_PATH"',
        f'docker exec "${{CONTAINER}}" su hadoop -c "/opt/hadoop/bin/hdfs dfs -mkdir -p {hdfs_path}"',
        "",
        'echo "==> Uploading to HDFS"',
        f'docker exec "${{CONTAINER}}" su hadoop -c "/opt/hadoop/bin/hdfs dfs -put /tmp/${{PARQUET_BASENAME}} {hdfs_path}/"',
        "",
        'echo "==> Verifying"',
        f'docker exec "${{CONTAINER}}" su hadoop -c "/opt/hadoop/bin/hdfs dfs -ls {hdfs_path}"',
        "",
        'echo ""',
        f'echo "Upload complete. Now run the DDL in Hue to create the table."',
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="CSV -> Parquet -> Hive DDL semi-automated import tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Basic usage: convert CSV and emit DDL to stdout
  python parquet_converter.py -i data/input.csv -o data/output.parquet \\
      --table my_table --hdfs-path /user/hue/my_table

  # Full pipeline: write DDL file + bash upload script
  python parquet_converter.py -i data/input.csv -o data/output.parquet \\
      --table sales --hdfs-path /user/hue/sales \\
      --ddl-output data/sales.sql --upload-script data/upload_sales.sh
""",
    )
    parser.add_argument(
        "-i", "--input", required=True, help="Input CSV file path"
    )
    parser.add_argument(
        "-o", "--output", required=True, help="Output Parquet file path"
    )
    parser.add_argument(
        "--table",
        required=True,
        help="Hive table name (e.g. sales_data)",
    )
    parser.add_argument(
        "--hdfs-path",
        required=True,
        help="HDFS directory for the external table (e.g. /user/hue/sales_data)",
    )
    parser.add_argument(
        "--ddl-output",
        default=None,
        help="Write Hive DDL to this file (default: print to stdout)",
    )
    parser.add_argument(
        "--upload-script",
        default=None,
        help="Generate an HDFS upload script at this path (.sh)",
    )
    parser.add_argument(
        "--compression",
        default="none",
        choices=["none", "snappy", "gzip", "brotli"],
        help="Parquet compression (default: none, best Hue compatibility)",
    )
    parser.add_argument(
        "--csv-encoding",
        default="utf-8",
        help="CSV file encoding (default: utf-8)",
    )
    parser.add_argument(
        "--comment",
        default="",
        help="Optional table comment",
    )
    parser.add_argument(
        "--container",
        default="namenode",
        help="Docker container running hdfs commands (default: namenode)",
    )

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"ERROR: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    print(f"[1/4] Reading CSV: {args.input}")
    print(f"[2/4] Converting {ARROW} Parquet: {args.output} (compression: {args.compression})")
    df = convert_csv_to_parquet(
        csv_path=args.input,
        parquet_path=args.output,
        compression=args.compression,
        csv_encoding=args.csv_encoding,
    )
    parquet_size = os.path.getsize(args.output)
    print(
        f"      {CHECK} done, {len(df)} rows {TIMES} {len(df.columns)} cols, "
        f"{parquet_size:,} bytes"
    )

    print(f"[3/4] Inferring schema {ARROW} generating Hive DDL")
    schema = infer_schema(df)
    ddl = generate_ddl(
        table_name=args.table,
        schema=schema,
        hdfs_path=args.hdfs_path,
        comment=args.comment,
    )

    if args.ddl_output:
        ddl_dir = os.path.dirname(args.ddl_output)
        if ddl_dir:
            os.makedirs(ddl_dir, exist_ok=True)
        with open(args.ddl_output, "w", encoding="utf-8") as f:
            f.write(ddl + "\n")
        print(f"      {CHECK} DDL written to: {args.ddl_output}")
    else:
        print("\n" + "=" * 60)
        print(ddl)
        print("=" * 60 + "\n")

    print(f"[4/4] Generating HDFS upload commands")
    upload_script = generate_upload_script(
        parquet_path=args.output,
        hdfs_path=args.hdfs_path,
        container=args.container,
        script_path=args.upload_script,
    )

    if args.upload_script:
        script_dir = os.path.dirname(args.upload_script)
        if script_dir:
            os.makedirs(script_dir, exist_ok=True)
        with open(args.upload_script, "w", encoding="utf-8", newline="\n") as f:
            f.write(upload_script)
        print(f"      {CHECK} upload script written to: {args.upload_script}")
    else:
        print("\n" + "-" * 60)
        print(upload_script)
        print("-" * 60)

    print(f"\n{CHECK} All done! Next steps:")
    print(f"  1. Upload the Parquet file to HDFS at {args.hdfs_path}/")
    if args.upload_script:
        print(f"     bash {args.upload_script}")
    if args.ddl_output:
        print(f"  2. Run the DDL in Hue (or Hive): {args.ddl_output}")
    else:
        print(f"  2. Run the CREATE EXTERNAL TABLE statement above in Hue")
    print(f"  3. Query: SELECT * FROM {args.table} LIMIT 10;")


if __name__ == "__main__":
    main()
