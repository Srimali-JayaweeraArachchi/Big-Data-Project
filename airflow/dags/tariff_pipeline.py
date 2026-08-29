import csv
import json
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import psycopg2
from airflow.sdk import dag, task


INCOMING = Path("/data/incoming")
ARCHIVE = Path("/data/archive")
REQUIRED_FIELDS = {"household_id", "tariff_rate", "billing_tier", "subsidy_flag", "effective_date"}


def db_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "smartgrid"),
        user=os.getenv("POSTGRES_USER", "smartgrid"),
        password=os.getenv("POSTGRES_PASSWORD", "smartgrid_dev_password"),
    )


@dag(
    dag_id="smart_grid_daily_tariff_pipeline",
    schedule="*/5 * * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(seconds=20)},
    tags=["smart-grid", "batch", "billing"],
)
def tariff_pipeline():
    @task
    def discover_files() -> list[str]:
        INCOMING.mkdir(parents=True, exist_ok=True)
        ARCHIVE.mkdir(parents=True, exist_ok=True)
        return [str(path) for path in sorted(INCOMING.glob("tariffs_day_*.csv"))]

    @task
    def load_tariffs(files: list[str]) -> dict:
        loaded_files = 0
        loaded_rows = 0
        with db_connection() as conn, conn.cursor() as cursor:
            for filename in files:
                path = Path(filename)
                cursor.execute("SELECT status FROM batch_ingestion_audit WHERE source_file=%s", (path.name,))
                audit_row = cursor.fetchone()
                if audit_row and audit_row[0] == "success":
                    continue
                try:
                    with path.open(newline="", encoding="utf-8") as stream:
                        reader = csv.DictReader(stream)
                        if not REQUIRED_FIELDS.issubset(reader.fieldnames or []):
                            raise ValueError(f"missing fields: {sorted(REQUIRED_FIELDS - set(reader.fieldnames or []))}")
                        rows = list(reader)
                    for row in rows:
                        rate = float(row["tariff_rate"])
                        if rate <= 0 or not row["household_id"].startswith("H"):
                            raise ValueError("invalid household or tariff rate")
                        cursor.execute(
                            """
                            INSERT INTO tariffs(household_id, effective_date, tariff_rate, billing_tier,
                                                subsidy_flag, source_file)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (household_id, effective_date) DO UPDATE SET
                                tariff_rate=EXCLUDED.tariff_rate,
                                billing_tier=EXCLUDED.billing_tier,
                                subsidy_flag=EXCLUDED.subsidy_flag,
                                source_file=EXCLUDED.source_file,
                                loaded_at=NOW()
                            """,
                            (
                                row["household_id"], row["effective_date"], rate,
                                row["billing_tier"], row["subsidy_flag"].lower() == "true", path.name,
                            ),
                        )
                    cursor.execute(
                        """INSERT INTO batch_ingestion_audit(source_file, row_count, status, error_message)
                           VALUES (%s,%s,'success',NULL) ON CONFLICT(source_file) DO UPDATE SET
                           row_count=EXCLUDED.row_count,status='success',error_message=NULL,processed_at=NOW()""",
                        (path.name, len(rows)),
                    )
                    loaded_files += 1
                    loaded_rows += len(rows)
                    shutil.move(str(path), ARCHIVE / path.name)
                except Exception as exc:
                    conn.rollback()
                    cursor.execute(
                        """INSERT INTO batch_ingestion_audit(source_file,row_count,status,error_message)
                           VALUES (%s,0,'failed',%s) ON CONFLICT(source_file) DO UPDATE SET
                           status='failed',error_message=EXCLUDED.error_message,processed_at=NOW()""",
                        (path.name, str(exc)),
                    )
                    conn.commit()
                    raise
        return {"files": loaded_files, "rows": loaded_rows}

    @task
    def generate_billing_report(load_result: dict) -> dict:
        with db_connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO daily_billing_report (
                    report_date, household_id, total_consumption_kwh, total_solar_kwh,
                    billable_grid_kwh, tariff_rate, subsidy_flag, estimated_bill
                )
                SELECT u.usage_date, u.household_id, u.total_consumption_kwh, u.total_solar_kwh,
                       GREATEST(u.net_grid_usage_kwh, 0), t.tariff_rate, t.subsidy_flag,
                       ROUND((GREATEST(u.net_grid_usage_kwh, 0) * t.tariff_rate
                              * CASE WHEN t.subsidy_flag THEN 0.85 ELSE 1.0 END)::numeric, 2)
                FROM household_usage_daily u
                JOIN LATERAL (
                    SELECT * FROM tariffs t
                    WHERE t.household_id=u.household_id AND t.effective_date <= u.usage_date
                    ORDER BY t.effective_date DESC LIMIT 1
                ) t ON TRUE
                ON CONFLICT (report_date, household_id) DO UPDATE SET
                    total_consumption_kwh=EXCLUDED.total_consumption_kwh,
                    total_solar_kwh=EXCLUDED.total_solar_kwh,
                    billable_grid_kwh=EXCLUDED.billable_grid_kwh,
                    tariff_rate=EXCLUDED.tariff_rate,
                    subsidy_flag=EXCLUDED.subsidy_flag,
                    estimated_bill=EXCLUDED.estimated_bill,
                    generated_at=NOW()
                """
            )
            affected = cursor.rowcount
            cursor.execute(
                """
                INSERT INTO pipeline_heartbeats(service_name,last_seen_at,status,details)
                VALUES ('airflow-tariff-pipeline',NOW(),'healthy',%s::jsonb)
                ON CONFLICT(service_name) DO UPDATE SET
                    last_seen_at=EXCLUDED.last_seen_at,status=EXCLUDED.status,details=EXCLUDED.details
                """,
                (json.dumps({"billing_rows": affected, **load_result}),),
            )
        return {"billing_rows": affected, **load_result}

    generate_billing_report(load_tariffs(discover_files()))


tariff_pipeline()
