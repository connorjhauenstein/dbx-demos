import os, sys

try:
    _script_dir = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # Databricks runs scripts via exec(compile(...)) — __file__ is not injected
    import inspect
    _script_dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
sys.path.insert(0, _script_dir)
sys.path.insert(0, os.path.dirname(_script_dir))  # repo root — for config.py

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.functions import col, from_json, window, last, sum, count
from pyspark.sql.types import IntegerType, TimestampType
from schema import QUOTE_SCHEMA
from metrics_listener import MetricsListener
import config as cfg

spark = SparkSession.getActiveSession()
spark.streams.addListener(MetricsListener())

BOOTSTRAP  = cfg.KAFKA_BOOTSTRAP
CHECKPOINT = cfg.CHECKPOINT_LOCATION

quotes = (spark.readStream
    .format("kafka")
    .option("kafka.bootstrap.servers", BOOTSTRAP)
    .option("subscribe", "md.quotes.normalized")
    .option("startingOffsets", "latest")
    .option("failOnDataLoss", "false")
    .load()
    .select(
        col("timestamp").cast(TimestampType()).alias("kafka_ts"),
        from_json(col("value").cast("string"), QUOTE_SCHEMA).alias("q"))
    .select("kafka_ts", "q.*"))

agg = (quotes
    .withWatermark("event_ts", "2 seconds")
    .groupBy(window(col("event_ts"), "1 second"), "symbol", "venue")
    .agg(last("bid").alias("bid"),
         last("ask").alias("ask"),
         sum("depth_bid_5").alias("depth_bid"),
         sum("depth_ask_5").alias("depth_ask"),
         count("*").cast(IntegerType()).alias("ticks"),
         last("event_ts").alias("last_event_ts"),
         last("kafka_ts").alias("last_kafka_ts"))
    .withColumn("spread_bps",
        F.when(col("bid") > 0, (col("ask") - col("bid")) / col("bid") * 10000))
    .withColumn("window_start", col("window.start"))
    .drop("window"))

query = (agg.writeStream
    .outputMode("update")
    .option("upsertkey", "symbol,venue,window_start")
    .option("checkpointLocation", CHECKPOINT)
    .trigger(realTime="5 minutes")
    .toTable("rtm_lakebase.market.quote_1s"))

query.awaitTermination()
