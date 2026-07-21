"""Unit tests for src/transforms.py. These run on a local Spark session in CI —
no cluster, no cloud, no data. They protect the transformation logic against
regressions: change a filter and break a rule, and the test goes red before the
change ever reaches a notebook."""
import pytest
from datetime import datetime
from pyspark.sql import SparkSession

from pyspark.sql.types import (
    StructType, StructField, StringType, TimestampType, DoubleType,
)

from src.transforms import (
    quality_filter, quarantine_reason, dedupe_events, latest_per_key,
)


@pytest.fixture(scope="session")
def spark():
    s = (SparkSession.builder
         .master("local[2]")
         .appName("transform-tests")
         .config("spark.sql.shuffle.partitions", "1")
         .getOrCreate())
    yield s
    s.stop()


_EVENT_SCHEMA = StructType([
    StructField("event_id", StringType(), True),
    StructField("user_id", StringType(), True),
    StructField("event_ts", TimestampType(), True),
    StructField("event_type", StringType(), True),
    StructField("price", DoubleType(), True),
])


def _events(spark, rows):
    # Explicit schema so a column that is all-null in a small test does not
    # break Spark's type inference.
    return spark.createDataFrame(rows, _EVENT_SCHEMA)


def test_quality_filter_keeps_valid_row(spark):
    df = _events(spark, [("e1", "u1", datetime(2024, 1, 1), "page_view", 10.0)])
    assert quality_filter(df).count() == 1


def test_quality_filter_drops_null_event_id(spark):
    df = _events(spark, [
        (None, "u1", datetime(2024, 1, 1), "page_view", 10.0),
        ("e2", "u1", datetime(2024, 1, 1), "page_view", 10.0)])
    assert quality_filter(df).count() == 1


def test_quality_filter_drops_null_user_id(spark):
    df = _events(spark, [("e1", None, datetime(2024, 1, 1), "page_view", 10.0)])
    assert quality_filter(df).count() == 0


def test_quality_filter_rejects_negative_price(spark):
    df = _events(spark, [("e1", "u1", datetime(2024, 1, 1), "purchase", -5.0)])
    assert quality_filter(df).count() == 0


def test_quality_filter_rejects_unknown_event_type(spark):
    df = _events(spark, [("e1", "u1", datetime(2024, 1, 1), "teleport", 10.0)])
    assert quality_filter(df).count() == 0


def test_quarantine_reason_labels_null_user(spark):
    df = _events(spark, [("e1", None, datetime(2024, 1, 1), "page_view", 10.0)])
    reason = quarantine_reason(df).collect()[0]["quarantine_reason"]
    assert reason == "null_user_id"


def test_quarantine_reason_labels_negative_price(spark):
    df = _events(spark, [("e1", "u1", datetime(2024, 1, 1), "purchase", -1.0)])
    reason = quarantine_reason(df).collect()[0]["quarantine_reason"]
    assert reason == "negative_price"


def test_dedupe_keeps_one_row_per_event_id(spark):
    df = spark.createDataFrame(
        [("e1", "a"), ("e1", "a"), ("e2", "b")], ["event_id", "x"])
    assert dedupe_events(df).count() == 2


def test_latest_per_key_keeps_most_recent(spark):
    df = spark.createDataFrame(
        [("r1", datetime(2024, 1, 1), "old"),
         ("r1", datetime(2024, 6, 1), "new"),
         ("r2", datetime(2024, 1, 1), "solo")],
        ["review_id", "answered_at", "label"])
    out = {r["review_id"]: r["label"]
           for r in latest_per_key(df, "review_id", "answered_at").collect()}
    assert out == {"r1": "new", "r2": "solo"}
