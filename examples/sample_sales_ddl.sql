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