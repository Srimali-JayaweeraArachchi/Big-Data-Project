import os
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest


app = FastAPI(title="Smart Grid Serving API", version="1.0.0")
last_event_age = Gauge("smart_grid_last_event_age_seconds", "Age of latest clean meter event")
active_alerts = Gauge("smart_grid_active_alerts", "Number of unresolved alerts")


def connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "smartgrid"),
        user=os.getenv("POSTGRES_USER", "smartgrid"),
        password=os.getenv("POSTGRES_PASSWORD", "smartgrid_dev_password"),
        cursor_factory=RealDictCursor,
    )


def fetch_all(query: str, params=()):
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()


@app.get("/health")
def health():
    try:
        rows = fetch_all("SELECT MAX(event_time) AS latest, COUNT(*) AS total FROM meter_readings_clean")
        latest = rows[0]["latest"]
        age = None if latest is None else (datetime.now(timezone.utc) - latest).total_seconds()
        threshold = int(os.getenv("NO_DATA_ALERT_SECONDS", "120"))
        status = "starting" if latest is None else ("unhealthy" if age > threshold else "healthy")
        return {"status": status, "database": "connected", "latest_event": latest, "last_event_age_seconds": age, "threshold_seconds": threshold}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc}") from exc


@app.get("/api/v1/overview")
def overview():
    result = fetch_all(
        """
        SELECT COALESCE(SUM(total_consumption_kwh),0) AS total_consumption_kwh,
               COALESCE(SUM(total_solar_kwh),0) AS total_solar_kwh,
               COALESCE(SUM(net_grid_load_kwh),0) AS net_grid_load_kwh,
               COALESCE(SUM(total_solar_kwh)/NULLIF(SUM(total_consumption_kwh),0),0) AS renewable_ratio,
               COALESCE(SUM(reading_count),0) AS reading_count,
               MAX(window_end) AS last_updated
        FROM zone_metrics WHERE window_start >= NOW() - INTERVAL '10 minutes'
        """
    )
    alerts = fetch_all("SELECT COUNT(*) AS count FROM pipeline_alerts WHERE resolved_at IS NULL")
    return {**result[0], "active_alerts": alerts[0]["count"]}


@app.get("/api/v1/zones")
def zones():
    return fetch_all(
        """
        SELECT grid_zone, SUM(total_consumption_kwh) AS consumption_kwh,
               SUM(total_solar_kwh) AS solar_kwh, SUM(net_grid_load_kwh) AS net_load_kwh,
               SUM(total_solar_kwh)/NULLIF(SUM(total_consumption_kwh),0) AS renewable_ratio
        FROM zone_metrics WHERE window_start >= NOW() - INTERVAL '10 minutes'
        GROUP BY grid_zone ORDER BY grid_zone
        """
    )


@app.get("/api/v1/timeseries")
def timeseries():
    return fetch_all(
        """
        SELECT window_start, grid_zone, total_consumption_kwh, total_solar_kwh,
               net_grid_load_kwh, renewable_ratio
        FROM zone_metrics ORDER BY window_start DESC LIMIT 120
        """
    )


@app.get("/api/v1/alerts")
def alerts(limit: int = 30):
    return fetch_all(
        """SELECT alert_type,severity,entity_id,message,metric_value,threshold_value,created_at
           FROM pipeline_alerts WHERE resolved_at IS NULL ORDER BY created_at DESC LIMIT %s""",
        (min(max(limit, 1), 100),),
    )


@app.get("/api/v1/billing")
def billing(limit: int = 100):
    return fetch_all(
        """SELECT report_date,household_id,total_consumption_kwh,total_solar_kwh,
                  billable_grid_kwh,tariff_rate,subsidy_flag,estimated_bill,generated_at
           FROM daily_billing_report ORDER BY report_date DESC,estimated_bill DESC LIMIT %s""",
        (min(max(limit, 1), 500),),
    )


@app.get("/api/v1/pipeline")
def pipeline():
    return fetch_all("SELECT service_name,last_seen_at,status,details FROM pipeline_heartbeats ORDER BY service_name")


@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    latest = fetch_all("SELECT MAX(event_time) AS latest FROM meter_readings_clean")[0]["latest"]
    age = 0 if latest is None else (datetime.now(timezone.utc) - latest).total_seconds()
    alert_count = fetch_all("SELECT COUNT(*) AS count FROM pipeline_alerts WHERE resolved_at IS NULL")[0]["count"]
    last_event_age.set(age)
    active_alerts.set(alert_count)
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)

