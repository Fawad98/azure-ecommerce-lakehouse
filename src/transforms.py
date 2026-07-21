"""Pure transformation functions, extracted from the notebooks so they can be
unit-tested without a cluster. The notebooks import from here; the tests import
from here. One definition, two consumers."""
from pyspark.sql import DataFrame, functions as F
from pyspark.sql.window import Window

VALID_EVENT_TYPES = ["page_view", "product_view", "add_to_cart",
                     "remove_from_cart", "begin_checkout", "purchase"]


def quality_filter(df: DataFrame) -> DataFrame:
    """Rows that pass every validation rule. The inverse is the quarantine set."""
    return df.filter(
        F.col("event_id").isNotNull() &
        F.col("user_id").isNotNull() &
        F.col("event_ts").isNotNull() &
        F.col("event_type").isin(VALID_EVENT_TYPES) &
        (F.col("price") >= 0))


def quarantine_reason(df: DataFrame) -> DataFrame:
    """Tag each failing row with the first rule it broke."""
    return df.withColumn(
        "quarantine_reason",
        F.when(F.col("event_id").isNull(), "null_event_id")
         .when(F.col("user_id").isNull(), "null_user_id")
         .when(F.col("event_ts").isNull(), "null_event_ts")
         .when(~F.col("event_type").isin(VALID_EVENT_TYPES), "invalid_event_type")
         .otherwise("negative_price"))


def dedupe_events(df: DataFrame) -> DataFrame:
    """One row per event_id."""
    return df.dropDuplicates(["event_id"])


def latest_per_key(df: DataFrame, key: str, order_col: str) -> DataFrame:
    """Keep the most recent row per key. Used for review deduplication where the
    same review_id appears multiple times."""
    w = Window.partitionBy(key).orderBy(F.col(order_col).desc_nulls_last())
    return (df.withColumn("_rn", F.row_number().over(w))
              .filter(F.col("_rn") == 1)
              .drop("_rn"))


def size_band(volume_col: str = "volume_cm3"):
    """Bucket a product volume into small/medium/large."""
    return (F.when(F.col(volume_col) < 5000, "small")
             .when(F.col(volume_col) < 30000, "medium")
             .otherwise("large"))
