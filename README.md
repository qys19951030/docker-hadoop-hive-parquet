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

## CSV → Parquet → Hive: 半自动导入链路

`parquet_converter.py` 是一个可复用的命令行工具，一站式完成：

1. 将本地 CSV 转换为无压缩 Parquet（Hue 兼容性最好）
2. 根据 CSV 的实际 schema 自动推断列类型
3. 生成可直接在 Hive/Hue 中执行的 `CREATE EXTERNAL TABLE` DDL
4. 生成 HDFS 上传脚本

不需要手写列定义，也不需要手工在 Hue 的 File Browser 里上传。

### 安装依赖

```bash
pip install -r requirements.txt
```

### 用法速览

```bash
python parquet_converter.py \
  -i <输入CSV> \
  -o <输出Parquet> \
  --table <Hive表名> \
  --hdfs-path <HDFS目录> \
  --ddl-output <DDL输出文件> \
  --upload-script <上传脚本输出文件>
```

全部参数：

| 参数 | 必填 | 说明 |
|------|------|------|
| `-i / --input` | ✅ | 输入 CSV 文件路径 |
| `-o / --output` | ✅ | 输出 Parquet 文件路径 |
| `--table` | ✅ | Hive 表名，如 `sales_data` |
| `--hdfs-path` | ✅ | HDFS 外部表目录，如 `/user/hue/sales_data` |
| `--ddl-output` | ❌ | DDL 输出文件路径；不填则打印到 stdout |
| `--upload-script` | ❌ | 生成 HDFS 上传脚本（docker 命令） |
| `--compression` | ❌ | Parquet 压缩方式：`none`(默认) / `snappy` / `gzip` / `brotli` |
| `--csv-encoding` | ❌ | CSV 编码，默认 `utf-8` |
| `--comment` | ❌ | 表注释 |
| `--container` | ❌ | 执行 hdfs 命令的容器名，默认 `namenode` |

### 完整示例：从 CSV 到可查询的 Hive 表

仓库自带了一个最小样例
[`examples/sample_sales.csv`](examples/sample_sales.csv)，
可以拿来直接跑通全流程。

**第 1 步：生成 Parquet + DDL + 上传脚本**

```bash
python parquet_converter.py \
  -i examples/sample_sales.csv \
  -o examples/sample_sales.parquet \
  --table sample_sales \
  --hdfs-path /user/hue/sample_sales \
  --ddl-output examples/sample_sales_ddl.sql \
  --upload-script examples/upload_sample_sales.sh \
  --comment "Sample sales data for demo"
```

输出：

```
[1/4] 读取 CSV: examples/sample_sales.csv
[2/4] 转换为 Parquet: examples/sample_sales.parquet (压缩: none)
      ✓ 完成，共 8 行 × 8 列，文件大小 5,443 字节
[3/4] 推断 schema 并生成 Hive DDL
      ✓ DDL 已写入: examples/sample_sales_ddl.sql
[4/4] 生成 HDFS 上传命令
      ✓ 上传脚本已写入: examples/upload_sample_sales.sh

✓ 全部完成！下一步：
  1. 运行上传命令将 Parquet 放到 HDFS 的 /user/hue/sample_sales/
  2. 在 Hue 中执行 examples/sample_sales_ddl.sql 中的建表语句
  3. 查询: SELECT * FROM sample_sales LIMIT 10;
```

**第 2 步：上传 Parquet 到 HDFS**

```bash
docker cp examples/sample_sales.parquet namenode:/tmp/sample_sales.parquet
docker exec namenode su hadoop -c "/opt/hadoop/bin/hdfs dfs -mkdir -p /user/hue/sample_sales"
docker exec namenode su hadoop -c "/opt/hadoop/bin/hdfs dfs -put /tmp/sample_sales.parquet /user/hue/sample_sales/"
docker exec namenode su hadoop -c "/opt/hadoop/bin/hdfs dfs -ls /user/hue/sample_sales"
```

（或者直接运行 `bash examples/upload_sample_sales.sh`）

**第 3 步：在 Hue 中建表**

打开 `examples/sample_sales_ddl.sql`，把内容粘到 Hue 的 Hive Editor 里执行：

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

**第 4 步：查询**

```sql
SELECT product, quantity, unit_price, quantity * unit_price AS total
FROM sample_sales
WHERE is_returned = false
ORDER BY total DESC
LIMIT 5;
```

### Schema 推断规则

工具根据 pandas 推断的 dtype 映射到 Hive 类型：

| pandas dtype | Hive 类型 |
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

列名会自动规范化：转小写、空格/连字符/点号换成下划线、非法字符替换、数字开头补 `col_` 前缀。

### 旧的固定文件名用法仍可用

如果只是想快速转换
[2018 UK Punctuality Statistics](https://www.kaggle.com/datasets/alenanorshtein/punctuality-statistics-full-analysis)
数据集（放到 `data/` 目录下），可以这么用：

```bash
python parquet_converter.py \
  -i data/201801_Punctuality_Statistics_Full_Analysis.csv \
  -o data/201801_Punctuality_Statistics_Full_Analysis.parquet \
  --table punctuality_2018 \
  --hdfs-path /user/hue/punctuality_2018 \
  --ddl-output data/punctuality_2018.sql
```

默认仍然是**无压缩** Parquet —— Hue 的内置 Parquet 读取器历史上对 snappy 的支持有问题，这也是这个转换器存在的原因。

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
