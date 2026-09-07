from __future__ import annotations

from pyspark.sql import SparkSession


def get_spark_session(app_name: str) -> SparkSession:
    """A local[2] SparkSession tuned for a small single-node box, not a cluster.

    Data volumes here are tiny (hundreds of rows) - this exists to demonstrate the
    processing pattern, not because the data needs distributed compute. Kept
    deliberately low-memory since it runs alongside Postgres/webserver/scheduler on a
    2 vCPU / 7.6GB box.
    """
    return (
        SparkSession.builder.appName(app_name)
        .master("local[2]")
        .config("spark.driver.memory", "1g")
        .config("spark.sql.shuffle.partitions", "4")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
