from pyspark.sql.types import *

QUOTE_SCHEMA = StructType([
    StructField("event_ts",    TimestampType(), False),
    StructField("symbol",      StringType(),    False),
    StructField("venue",       StringType(),    False),
    StructField("bid",         DoubleType(),    False),
    StructField("ask",         DoubleType(),    False),
    StructField("bid_sz",      DoubleType(),    True),
    StructField("ask_sz",      DoubleType(),    True),
    StructField("depth_bid_5", DoubleType(),    True),
    StructField("depth_ask_5", DoubleType(),    True),
    StructField("seq",         LongType(),      True),
])
