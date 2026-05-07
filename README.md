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

## Convert a CSV to Parquet

The example dataset is the
[2018 UK Punctuality Statistics](https://www.kaggle.com/datasets/alenanorshtein/punctuality-statistics-full-analysis)
from Kaggle. Drop the CSV into `data/`, then:

```bash
pip install -r requirements.txt
python parquet_converter.py
```

This writes `data/201801_Punctuality_Statistics_Full_Analysis.parquet` with
no compression (Hue's bundled Parquet reader has historically choked on
snappy — that gotcha is the whole reason the converter exists).

## Run a SQL query

1. In Hue → **File Browser**, upload the `.parquet` to e.g. `/user/hue/`.
2. In Hue → **Editor → Hive**, create a table over the Parquet file. Use
   `parquet-tools schema <file>` locally to grab the column types, then:

   ```sql
   CREATE EXTERNAL TABLE punctuality_2018 (
     run_date STRING,
     reporting_period STRING,
     -- ... rest of the columns
     average_delay_mins DOUBLE,
     origin_destination_country STRING
   )
   STORED AS PARQUET
   LOCATION '/user/hue/';
   ```

3. Query it:

   ```sql
   SELECT *
   FROM punctuality_2018
   WHERE origin_destination_country = 'POLAND'
     AND average_delay_mins >= 10;
   ```

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
- Fixed `parquet_converter.py` for pandas 2.x (`fname=` → `path=`).
- Added a `platform: linux/amd64` pin and arm64 notes for Hue.

## License

[MIT](LICENSE)
