import os
import time

import pandas as pd
import requests
import streamlit as st


API = os.getenv("API_BASE_URL", "http://api:8000")
st.set_page_config(page_title="Smart Grid Operations", page_icon="⚡", layout="wide")
st.title("⚡ Smart Grid Energy Monitoring & Billing")
st.caption("Real-time load, renewable contribution, alerts, and simulated-daily billing")


def api_get(path: str):
    response = requests.get(f"{API}{path}", timeout=10)
    response.raise_for_status()
    return response.json()


try:
    overview = api_get("/api/v1/overview")
    zones = pd.DataFrame(api_get("/api/v1/zones"))
    series = pd.DataFrame(api_get("/api/v1/timeseries"))
    alerts = pd.DataFrame(api_get("/api/v1/alerts"))
    billing = pd.DataFrame(api_get("/api/v1/billing"))
    pipeline = pd.DataFrame(api_get("/api/v1/pipeline"))
except Exception as exc:
    st.warning(f"Pipeline is starting or API is unavailable: {exc}")
    time.sleep(5)
    st.rerun()

cols = st.columns(5)
cols[0].metric("Consumption (kWh)", f"{float(overview['total_consumption_kwh']):,.1f}")
cols[1].metric("Solar (kWh)", f"{float(overview['total_solar_kwh']):,.1f}")
cols[2].metric("Net grid load", f"{float(overview['net_grid_load_kwh']):,.1f}")
cols[3].metric("Renewable contribution", f"{float(overview['renewable_ratio']) * 100:.1f}%")
cols[4].metric("Active alerts", int(overview["active_alerts"]))

left, right = st.columns(2)
with left:
    st.subheader("Zone load and solar generation")
    if not zones.empty:
        chart = zones.set_index("grid_zone")[["consumption_kwh", "solar_kwh"]].astype(float)
        st.bar_chart(chart)
    else:
        st.info("Waiting for zone metrics")
with right:
    st.subheader("Renewable contribution by zone")
    if not zones.empty:
        renewable = zones.set_index("grid_zone")[["renewable_ratio"]].astype(float) * 100
        st.bar_chart(renewable)

st.subheader("Recent consumption vs solar")
if not series.empty:
    series["window_start"] = pd.to_datetime(series["window_start"])
    aggregate = series.groupby("window_start")[["total_consumption_kwh", "total_solar_kwh"]].sum().sort_index().astype(float)
    st.line_chart(aggregate)

alert_tab, billing_tab, health_tab = st.tabs(["Alerts", "Daily billing report", "Pipeline health"])
with alert_tab:
    st.dataframe(alerts, use_container_width=True, hide_index=True)
with billing_tab:
    st.dataframe(billing, use_container_width=True, hide_index=True)
with health_tab:
    st.dataframe(pipeline, use_container_width=True, hide_index=True)

st.caption("Auto-refreshes every 10 seconds · 1 simulated day = 5 minutes")
time.sleep(10)
st.rerun()

