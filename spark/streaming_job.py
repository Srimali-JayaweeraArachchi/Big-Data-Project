import json
import logging
import os
import sys
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import execute_values
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, StringType, StructField, StructType


logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")
logger = logging.getLogger("spark-processor")

SCHEMA = StructType(
    [
        StructField("event_id", StringType()),
        StructField("meter_id", StringType()),
        StructField("household_id", StringType()),
        StructField("power_consumption_kwh", DoubleType()),
        StructField("solar_generation_kwh", DoubleType()),
        StructField("grid_zone", StringType()),
        StructField("timestamp", StringType()),
    ]
)


def log_event(event: str, **details) -> None:
    print(
        json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "service": "spark-processor",
                "level": "INFO",
                "event": event,
                **details,
            }
        ),
        flush=True,
    )


def connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "smartgrid"),
        user=os.getenv("POSTGRES_USER", "smartgrid"),
        password=os.getenv("POSTGRES_PASSWORD", "smartgrid_dev_password"),
    )


def transform_events(df: DataFrame) -> DataFrame:
    return (
        df.withColumn("event_time", F.to_timestamp("timestamp"))
        .withColumn("net_grid_usage_kwh", F.col("power_consumption_kwh") - F.col("solar_generation_kwh"))
        .withColumn(
            "renewable_ratio",
            F.when(F.col("power_consumption_kwh") > 0, F.col("solar_generation_kwh") / F.col("power_consumption_kwh")).otherwise(F.lit(0.0)),
        )
    )


def valid_expression():
    return (
        F.col("event_id").isNotNull()
        & F.col("meter_id").isNotNull()
        & F.col("household_id").isNotNull()
        & F.col("grid_zone").isNotNull()
        & F.col("event_time").isNotNull()
        & (F.col("power_consumption_kwh") >= 0)
        & (F.col("solar_generation_kwh") >= 0)
    )


def write_batch(batch: DataFrame, batch_id: int) -> None:
    if batch.rdd.isEmpty():
        return
    cached = batch.cache()
    valid = cached.filter(valid_expression())
    invalid = cached.filter(~valid_expression())
    valid_rows = [row.asDict(recursive=True) for row in valid.collect()]
    invalid_rows = [row.asDict(recursive=True) for row in invalid.collect()]
    low_threshold = float(os.getenv("LOW_RENEWABLE_THRESHOLD", "0.10"))
    high_threshold = float(os.getenv("HIGH_LOAD_THRESHOLD_KWH", "8.0"))

    with connection() as conn, conn.cursor() as cursor:
        if valid_rows:
            execute_values(
                cursor,
                """
                INSERT INTO meter_readings_clean (
                    event_id, meter_id, household_id, power_consumption_kwh,
                    solar_generation_kwh, net_grid_usage_kwh, renewable_ratio,
                    grid_zone, event_time
                ) VALUES %s ON CONFLICT (event_id) DO NOTHING
                """,
                [
                    (
                        row["event_id"], row["meter_id"], row["household_id"],
                        row["power_consumption_kwh"], row["solar_generation_kwh"],
                        row["net_grid_usage_kwh"], row["renewable_ratio"],
                        row["grid_zone"], row["event_time"],
                    )
                    for row in valid_rows
                ],
            )

            zone_aggregates = (
                valid.groupBy(F.window("event_time", "1 minute"), "grid_zone")
                .agg(
                    F.sum("power_consumption_kwh").alias("consumption"),
                    F.sum("solar_generation_kwh").alias("solar"),
                    F.sum("net_grid_usage_kwh").alias("net"),
                    F.count("*").alias("count"),
                )
                .collect()
            )
            execute_values(
                cursor,
                """
                INSERT INTO zone_metrics (
                    window_start, window_end, grid_zone, total_consumption_kwh,
                    total_solar_kwh, net_grid_load_kwh, renewable_ratio, reading_count
                ) VALUES %s
                ON CONFLICT (window_start, grid_zone) DO UPDATE SET
                    window_end = EXCLUDED.window_end,
                    total_consumption_kwh = zone_metrics.total_consumption_kwh + EXCLUDED.total_consumption_kwh,
                    total_solar_kwh = zone_metrics.total_solar_kwh + EXCLUDED.total_solar_kwh,
                    net_grid_load_kwh = zone_metrics.net_grid_load_kwh + EXCLUDED.net_grid_load_kwh,
                    reading_count = zone_metrics.reading_count + EXCLUDED.reading_count,
                    renewable_ratio = (zone_metrics.total_solar_kwh + EXCLUDED.total_solar_kwh)
                        / GREATEST(zone_metrics.total_consumption_kwh + EXCLUDED.total_consumption_kwh, 0.0001),
                    updated_at = NOW()
                """,
                [
                    (
                        row["window"]["start"], row["window"]["end"], row["grid_zone"],
                        row["consumption"], row["solar"], row["net"],
                        row["solar"] / max(row["consumption"], 0.0001), row["count"],
                    )
                    for row in zone_aggregates
                ],
            )

            household_aggregates = (
                valid.withColumn("usage_date", F.to_date("event_time"))
                .groupBy("usage_date", "household_id")
                .agg(
                    F.sum("power_consumption_kwh").alias("consumption"),
                    F.sum("solar_generation_kwh").alias("solar"),
                    F.sum("net_grid_usage_kwh").alias("net"),
                    F.count("*").alias("count"),
                )
                .collect()
            )
            execute_values(
                cursor,
                """
                INSERT INTO household_usage_daily (
                    usage_date, household_id, total_consumption_kwh,
                    total_solar_kwh, net_grid_usage_kwh, reading_count
                ) VALUES %s
                ON CONFLICT (usage_date, household_id) DO UPDATE SET
                    total_consumption_kwh = household_usage_daily.total_consumption_kwh + EXCLUDED.total_consumption_kwh,
                    total_solar_kwh = household_usage_daily.total_solar_kwh + EXCLUDED.total_solar_kwh,
                    net_grid_usage_kwh = household_usage_daily.net_grid_usage_kwh + EXCLUDED.net_grid_usage_kwh,
                    reading_count = household_usage_daily.reading_count + EXCLUDED.reading_count,
                    updated_at = NOW()
                """,
                [(r["usage_date"], r["household_id"], r["consumption"], r["solar"], r["net"], r["count"]) for r in household_aggregates],
            )

            alerts = []
            for row in valid_rows:
                if row["renewable_ratio"] < low_threshold:
                    alerts.append(("LOW_RENEWABLE", "WARNING", row["meter_id"], "Renewable contribution below threshold", row["renewable_ratio"], low_threshold))
                if row["net_grid_usage_kwh"] > high_threshold:
                    alerts.append(("HIGH_GRID_LOAD", "CRITICAL", row["meter_id"], "Net grid load above threshold", row["net_grid_usage_kwh"], high_threshold))
            if alerts:
                execute_values(
                    cursor,
                    """INSERT INTO pipeline_alerts
                    (alert_type, severity, entity_id, message, metric_value, threshold_value) VALUES %s""",
                    alerts,
                )

        if invalid_rows:
            execute_values(
                cursor,
                "INSERT INTO rejected_events (raw_payload, rejection_reason) VALUES %s",
                [(json.dumps(row, default=str), "schema_or_range_validation_failed") for row in invalid_rows],
            )

        cursor.execute(
            """
            INSERT INTO pipeline_heartbeats(service_name, last_seen_at, status, details)
            VALUES ('spark-processor', NOW(), 'healthy', %s::jsonb)
            ON CONFLICT (service_name) DO UPDATE SET
                last_seen_at=EXCLUDED.last_seen_at, status=EXCLUDED.status, details=EXCLUDED.details
            """,
            (json.dumps({"batch_id": batch_id, "valid": len(valid_rows), "invalid": len(invalid_rows)}),),
        )
    cached.unpersist()
    log_event("micro_batch_completed", batch_id=batch_id, valid=len(valid_rows), invalid=len(invalid_rows))


def main() -> None:
    spark = (
        SparkSession.builder.appName("smart-grid-structured-streaming")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.streaming.stopGracefullyOnShutdown", "true")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    source = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"))
        .option("subscribe", os.getenv("KAFKA_TOPIC", "smart-meter-readings"))
        .option("startingOffsets", "earliest")
        .option("failOnDataLoss", "false")
        .load()
    )
    parsed = source.select(
        F.from_json(F.col("value").cast("string"), SCHEMA).alias("event"),
        F.col("value").cast("string").alias("raw_payload"),
    ).select("event.*", "raw_payload")
    transformed = transform_events(parsed)
    query = (
        transformed.writeStream.foreachBatch(write_batch)
        .option("checkpointLocation", "/checkpoints/smart-grid")
        .trigger(processingTime="10 seconds")
        .start()
    )
    log_event("stream_started", topic=os.getenv("KAFKA_TOPIC", "smart-meter-readings"))
    query.awaitTermination()


if __name__ == "__main__":
    main()

