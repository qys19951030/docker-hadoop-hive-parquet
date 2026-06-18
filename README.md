# docker-hadoop-hive-parquet

A Docker Compose stack for running SQL queries against Parquet files via
**Apache Hive 4** on **Apache Hadoop 3 (HDFS)**, with **Hue** as the web UI.
Companion to the article
[*Making big moves in Big Data with Hadoop, Hive, Parquet, Hue and Docker*](https://medium.com/data-science/making-big-moves-in-big-data-with-hadoop-hive-parquet-hue-and-docker-320a52ca175).

The original 2020 stack used the (now-unmaintained) `bde2020/*` images. This
2026 refresh moves everything to the official upstream images and trims the
demo down to the parts the article actually uses.

## Stack

| Service        | Image                       | Purpose                       |
|----------------|-----------------------------|-------------------------------|
| `namenode`     | `apache/hadoop:3.4.1`       | HDFS NameNode                 |
| `datanode`     | `apache/hadoop:3.4.1`       | HDFS DataNode                 |
| `hive-metastore` | `apache/hive:4.0.1`       | Hive Metastore (Thrift 9083)  |
| `hive-server`  | `apache/hive:4.0.1`         | HiveServer2 (Thrift 10000)    |
| `postgres`     | `postgres:16-alpine`        | Backs both Hue and the Hive Metastore |
| `hue`          | `gethue/hue:4.11.0`         | SQL editor + HDFS file browser |

## Ports

| Port  | Service                       |
|-------|-------------------------------|
| 8888  | Hue UI                        |
| 10000 | HiveServer2 Thrift            |
| 10002 | HiveServer2 Web UI            |
| 9870  | HDFS NameNode UI / WebHDFS    |
| 9864  | HDFS DataNode HTTP            |
| 8020  | HDFS NameNode RPC             |
| 9083  | Hive Metastore Thrift         |

PostgreSQL (port 5432) is internal to the compose network and is not
published to the host, so it won't collide with a local Postgres.

## Prerequisites

- Docker Desktop / Colima with **≥8 GB RAM** allocated and ~6 GB free disk.
- Python 3.10+ if you want to run the Parquet converter locally.

### Apple Silicon / arm64

Only `apache/hive:4.0.1` ships a `linux/arm64` manifest. `apache/hadoop:3.4.1`
and `gethue/hue` are `linux/amd64`-only as of writing, so the namenode,
datanode, and Hue containers run under emulation on M-series Macs (slow on
first boot, then fine). They are pinned with `platform: linux/amd64` in
`docker-compose.yml` so the warning doesn't appear on every `docker compose`
invocation. If you'd rather avoid emulation entirely, run the stack inside an
x86-64 Colima VM:

```bash
colima start --arch x86_64 --cpu 4 --memory 8
```

## Quickstart

```bash
# 1. One-time: fetch the PostgreSQL JDBC driver for the Hive Metastore.
mkdir -p jars
curl -L -o jars/postgres-jdbc.jar \
  https://jdbc.postgresql.org/download/postgresql-42.7.4.jar

# 2. Bring everything up. The first run pulls ~5 GB of images.
docker compose up -d --wait

# 3. Confirm health.
docker compose ps
curl -fsS http://localhost:9870/dfshealth.html >/dev/null && echo "HDFS OK"
```

Then open <http://localhost:8888>, create the first Hue user (it becomes the
admin), and you're in.

## CSV -> Parquet -> Hive: Semi-automated import pipeline

`parquet_converter.py` is a reusable command-line tool that handles the
entire pipeline in one go:

1. Converts a local CSV to **uncompressed** Parquet (best Hue compatibility)
2. Auto-detects column types from the actual CSV schema
3. Generates a ready-to-run `CREATE EXTERNAL TABLE` DDL for Hive/Hue
4. Generates a cross-platform bash script to upload the Parquet to HDFS

No more hand-copying column definitions into Hue, and no more manual uploads
through the Hue File Browser.

### Cross-platform notes

- **Console output**: On Windows terminals that don't support UTF-8 (e.g.,
  PowerShell 5 with default code page), the tool automatically falls back to
  ASCII characters (`OK`, `->`, `x`) instead of Unicode symbols
  (`✓`, `→`, `×`) to avoid `UnicodeEncodeError`.
- **Upload scripts**: The generated upload script is a bash script. On
  Windows, run it via **Git Bash**, **WSL**, or any bash-compatible shell.
  The script uses paths relative to its own location, so it works regardless
  of your current working directory.

### Install dependencies

```bash
pip install -r requirements.txt
```

### Quick reference

```bash
python parquet_converter.py ^
  -i <input-csv> ^
  -o <output-parquet> ^
  --table <hive-table-name> ^
  --hdfs-path <hdfs-directory> ^
  --ddl-output <ddl-output-file> ^
  --upload-script <upload-script-output>
```

> **Note**: Use `^` for line continuation in Windows PowerShell / cmd.
> Use `\` on Linux / macOS / WSL / Git Bash.

All parameters:

| Parameter | Required | Description |
|-----------|----------|-------------|
| `-i / --input` | Yes | Input CSV file path |
| `-o / --output` | Yes | Output Parquet file path |
| `--table` | Yes | Hive table name, e.g. `sales_data` |
| `--hdfs-path` | Yes | HDFS directory for the external table, e.g. `/user/hue/sales_data` |
| `--ddl-output` | No | Write DDL to this file (default: print to stdout) |
| `--upload-script` | No | Generate an HDFS upload script (.sh) |
| `--compression` | No | Parquet compression: `none` (default) / `snappy` / `gzip` / `brotli` |
| `--csv-encoding` | No | CSV file encoding (default: `utf-8`) |
| `--comment` | No | Optional table comment |
| `--container` | No | Docker container for hdfs commands (default: `namenode`) |

### Full example: from CSV to queryable Hive table

The repository ships with a minimal sample dataset at
[`examples/sample_sales.csv`](examples/sample_sales.csv)
that you can use to verify the entire pipeline end-to-end.

**Step 1: Generate Parquet + DDL + upload script**

Run this from the repository root:

```bash
python parquet_converter.py ^
  -i examples/sample_sales.csv ^
  -o examples/sample_sales.parquet ^
  --table sample_sales ^
  --hdfs-path /user/hue/sample_sales ^
  --ddl-output examples/sample_sales_ddl.sql ^
  --upload-script examples/upload_sample_sales.sh ^
  --comment "Sample sales data for demo"
```

Output (Unicode on UTF-8 terminals, ASCII on Windows):

```
[1/4] Reading CSV: examples/sample_sales.csv
[2/4] Converting -> Parquet: examples/sample_sales.parquet (compression: none)
      OK done, 8 rows x 8 cols, 5,443 bytes
[3/4] Inferring schema -> generating Hive DDL
      OK DDL written to: examples/sample_sales_ddl.sql
[4/4] Generating HDFS upload commands
      OK upload script written to: examples/upload_sample_sales.sh

OK All done! Next steps:
  1. Upload the Parquet file to HDFS at /user/hue/sample_sales/
     bash examples/upload_sample_sales.sh
  2. Run the DDL in Hue (or Hive): examples/sample_sales_ddl.sql
  3. Query: SELECT * FROM sample_sales LIMIT 10;
```

> **Verification**: The exact output from the run used to generate this
> documentation is preserved in
> [`examples/verify_output.txt`](examples/verify_output.txt).

**Step 2: Upload Parquet to HDFS**

Run the generated upload script (requires bash):

```bash
bash examples/upload_sample_sales.sh
```

The script:
- Resolves its own directory to find the Parquet file (works from any cwd)
- Checks that the Parquet file exists
- Copies it into the namenode container via `docker cp`
- Creates the HDFS directory
- Uploads the file
- Lists the directory to verify

If you prefer to run the commands manually:

```bash
docker cp examples/sample_sales.parquet namenode:/tmp/sample_sales.parquet
docker exec namenode su hadoop -c "/opt/hadoop/bin/hdfs dfs -mkdir -p /user/hue/sample_sales"
docker exec namenode su hadoop -c "/opt/hadoop/bin/hdfs dfs -put /tmp/sample_sales.parquet /user/hue/sample_sales/"
docker exec namenode su hadoop -c "/opt/hadoop/bin/hdfs dfs -ls /user/hue/sample_sales"
```

**Step 3: Create the Hive table**

Open [`examples/sample_sales_ddl.sql`](examples/sample_sales_ddl.sql)
and paste its contents into the Hue Hive Editor, or run via `beeline`:

```sql
CREATE EXTERNAL TABLE IF NOT EXISTS sample_sales (
  order_id BIGINT,
  customer_name STRING,
  product STRING,
  quantity BIGINT,
  unit_price DOUBLE,
  order_date STRING,
  is_returned BOOLEAN,
  rating DOUBLE
)
COMMENT 'Sample sales data for demo'
STORED AS PARQUET
LOCATION '/user/hue/sample_sales'
;
```

**Step 4: Query**

```sql
SELECT product, quantity, unit_price, quantity * unit_price AS total
FROM sample_sales
WHERE is_returned = false
ORDER BY total DESC
LIMIT 5;
```

### Schema inference rules

The tool maps pandas-detected dtypes to Hive types:

| pandas dtype | Hive type |
|--------------|-----------|
| `int8`       | `TINYINT` |
| `int16`      | `SMALLINT` |
| `int32`      | `INT` |
| `int64`      | `BIGINT` |
| `float32`    | `FLOAT` |
| `float64`    | `DOUBLE` |
| `bool`       | `BOOLEAN` |
| `datetime64` | `TIMESTAMP` |
| `object` / `string` / `category` | `STRING` |

Column names are automatically normalized: lowercased, spaces/hyphens/dots
replaced with underscores, illegal characters replaced, and numeric-leading
names prefixed with `col_`.

### Legacy usage (Punctuality Statistics dataset)

If you just want to convert the
[2018 UK Punctuality Statistics](https://www.kaggle.com/datasets/alenanorshtein/punctuality-statistics-full-analysis)
dataset (drop it in `data/`), use:

```bash
python parquet_converter.py ^
  -i data/201801_Punctuality_Statistics_Full_Analysis.csv ^
  -o data/201801_Punctuality_Statistics_Full_Analysis.parquet ^
  --table punctuality_2018 ^
  --hdfs-path /user/hue/punctuality_2018 ^
  --ddl-output data/punctuality_2018.sql
```

The default is still **uncompressed** Parquet — Hue's bundled Parquet reader
has historically choked on snappy, which is why this converter exists in the
first place.

## Teardown

```bash
docker compose down -v   # also removes namenode/datanode/postgres volumes
```

## Troubleshooting

- **`docker compose up` hangs on `hive-metastore`** — check that
  `jars/postgres-jdbc.jar` exists; the metastore can't start without it.
- **Hue shows `Could not connect to hive-server:10000`** — give HiveServer2
  ~30 seconds after the metastore is healthy; the `depends_on` only waits
  for it to be *started*, not *ready*.
- **`Failed to read Parquet file` in Hue's preview** — re-run the converter
  with `compression=None` (this is the default; do not change it).
- **`Database is locked` in Hue** — Hue is pointed at SQLite somewhere; it
  should be using PostgreSQL via `hue-overrides.ini`. Check that the file
  is mounted (`docker compose exec hue cat /usr/share/hue/desktop/conf/hue-overrides.ini`).

## What changed vs the 2020 version

- Migrated off the unmaintained `bde2020/*` images to `apache/hadoop:3.4.1`,
  `apache/hive:4.0.1`, `postgres:16-alpine`, and date-tagged `gethue/hue`.
- Collapsed the two PostgreSQL services into one (separate `hue` and
  `metastore` databases bootstrapped via `postgres-init/init.sql`).
- Removed the YARN `resourcemanager` — the demo never submits YARN jobs.
- Replaced the bde2020 env-var-to-XML config convention with mounted XML
  configs under `conf/hadoop/`.
- Replaced `SERVICE_PRECONDITION` polling with proper `healthcheck` +
  `depends_on: condition: service_healthy`.
- Rewrote `parquet_converter.py` as a proper CLI tool with `argparse`; it
  now takes arbitrary CSV/Parquet paths, a Hive table name, an HDFS path,
  and auto-generates both a `CREATE EXTERNAL TABLE` DDL and an HDFS upload
  script. No more hand-copying column definitions into Hue.
- Added `examples/sample_sales.csv` as a minimal reproducible dataset plus
  pre-generated DDL and upload script for validation.
- Fixed `parquet_converter.py` for pandas 2.x (`fname=` → `path=`).
- Added a `platform: linux/amd64` pin and arm64 notes for Hue.

## License

[MIT](LICENSE)
