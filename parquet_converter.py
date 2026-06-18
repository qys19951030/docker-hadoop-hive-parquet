#!/usr/bin/env python3
"""
CSV → Parquet → Hive DDL 半自动导入工具。

将本地 CSV 文件转换为无压缩 Parquet，并根据实际 schema 自动生成
可直接在 Hive/Hue 中执行的 CREATE EXTERNAL TABLE 语句。
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd


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


def map_dtype(dtype) -> str:
    """将 pandas dtype 映射到 Hive 数据类型。"""
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
    """将列名规范化为 Hive 友好的标识符。"""
    cleaned = name.strip().lower().replace(" ", "_").replace("-", "_").replace(".", "_")
    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in cleaned)
    if cleaned and cleaned[0].isdigit():
        cleaned = "col_" + cleaned
    return cleaned or "col"


def infer_schema(df: pd.DataFrame) -> list[tuple[str, str, str]]:
    """从 DataFrame 推断 Hive schema，返回 (原列名, 规范化列名, Hive类型)。"""
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
    """生成 Hive CREATE EXTERNAL TABLE DDL。"""
    lines = []
    lines.append(f"CREATE EXTERNAL TABLE IF NOT EXISTS {table_name} (")
    col_lines = []
    for orig, hive_col, hive_type in schema:
        col_comment = f"  COMMENT '{orig}'" if orig != hive_col else ""
        col_lines.append(f"  {hive_col} {hive_type}{col_comment}")
    lines.append(",\n".join(col_lines))
    lines.append(")")
    if comment:
        lines.append(f"COMMENT '{comment}'")
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
    """将 CSV 转换为 Parquet，返回 DataFrame 以便进一步推断 schema。"""
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


def generate_upload_script(
    parquet_path: str,
    hdfs_path: str,
    container: str = "namenode",
) -> str:
    """生成上传 Parquet 到 HDFS 的 docker 命令脚本。"""
    parquet_file = os.path.basename(parquet_path)
    abs_parquet = os.path.abspath(parquet_path)
    lines = [
        "# 将 Parquet 文件上传到 HDFS",
        f"# 本地文件: {abs_parquet}",
        f"# HDFS 目录: {hdfs_path}",
        "",
        f"docker cp {abs_parquet} {container}:/tmp/{parquet_file}",
        f"docker exec {container} su hadoop -c \"/opt/hadoop/bin/hdfs dfs -mkdir -p {hdfs_path}\"",
        f"docker exec {container} su hadoop -c \"/opt/hadoop/bin/hdfs dfs -put /tmp/{parquet_file} {hdfs_path}/\"",
        f"docker exec {container} su hadoop -c \"/opt/hadoop/bin/hdfs dfs -ls {hdfs_path}\"",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="CSV → Parquet → Hive DDL 半自动导入工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基本用法：转换 CSV 并生成 DDL
  python parquet_converter.py -i data/input.csv -o data/output.parquet \\
      --table my_table --hdfs-path /user/hue/my_table --ddl-output data/my_table.sql

  # 完整链路：转换 + DDL + 上传脚本
  python parquet_converter.py -i data/input.csv -o data/output.parquet \\
      --table sales --hdfs-path /user/hue/sales \\
      --ddl-output data/sales.sql --upload-script data/upload_sales.sh
        """,
    )
    parser.add_argument(
        "-i", "--input", required=True, help="输入 CSV 文件路径"
    )
    parser.add_argument(
        "-o", "--output", required=True, help="输出 Parquet 文件路径"
    )
    parser.add_argument(
        "--table",
        required=True,
        help="Hive 表名（例如: sales_data）",
    )
    parser.add_argument(
        "--hdfs-path",
        required=True,
        help="HDFS 上的外部表目录（例如: /user/hue/sales_data）",
    )
    parser.add_argument(
        "--ddl-output",
        default=None,
        help="Hive DDL 输出文件路径（默认: stdout 打印）",
    )
    parser.add_argument(
        "--upload-script",
        default=None,
        help="生成 HDFS 上传脚本的输出路径",
    )
    parser.add_argument(
        "--compression",
        default="none",
        choices=["none", "snappy", "gzip", "brotli"],
        help="Parquet 压缩方式（默认: none，Hue 兼容性最好）",
    )
    parser.add_argument(
        "--csv-encoding",
        default="utf-8",
        help="CSV 文件编码（默认: utf-8）",
    )
    parser.add_argument(
        "--comment",
        default="",
        help="表注释（可选）",
    )
    parser.add_argument(
        "--container",
        default="namenode",
        help="用于执行 hdfs 命令的 Docker 容器名（默认: namenode）",
    )

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"错误: 输入文件不存在: {args.input}", file=sys.stderr)
        sys.exit(1)

    print(f"[1/4] 读取 CSV: {args.input}")
    print(f"[2/4] 转换为 Parquet: {args.output} (压缩: {args.compression})")
    df = convert_csv_to_parquet(
        csv_path=args.input,
        parquet_path=args.output,
        compression=args.compression,
        csv_encoding=args.csv_encoding,
    )
    parquet_size = os.path.getsize(args.output)
    print(f"      ✓ 完成，共 {len(df)} 行 × {len(df.columns)} 列，文件大小 {parquet_size:,} 字节")

    print(f"[3/4] 推断 schema 并生成 Hive DDL")
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
            f.write(ddl)
        print(f"      ✓ DDL 已写入: {args.ddl_output}")
    else:
        print("\n" + "=" * 60)
        print(ddl)
        print("=" * 60 + "\n")

    print(f"[4/4] 生成 HDFS 上传命令")
    upload_script = generate_upload_script(
        parquet_path=args.output,
        hdfs_path=args.hdfs_path,
        container=args.container,
    )

    if args.upload_script:
        script_dir = os.path.dirname(args.upload_script)
        if script_dir:
            os.makedirs(script_dir, exist_ok=True)
        with open(args.upload_script, "w", encoding="utf-8") as f:
            f.write(upload_script)
        print(f"      ✓ 上传脚本已写入: {args.upload_script}")
    else:
        print("\n" + "-" * 60)
        print(upload_script)
        print("-" * 60)

    print("\n✓ 全部完成！下一步：")
    print(f"  1. 运行上传命令将 Parquet 放到 HDFS 的 {args.hdfs_path}/")
    if args.ddl_output:
        print(f"  2. 在 Hue 中执行 {args.ddl_output} 中的建表语句")
    else:
        print(f"  2. 在 Hue 中执行上面的 CREATE EXTERNAL TABLE 语句")
    print(f"  3. 查询: SELECT * FROM {args.table} LIMIT 10;")


if __name__ == "__main__":
    main()
