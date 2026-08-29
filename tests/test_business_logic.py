import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path


def load_module(path: str, name: str):
    source = Path(path).resolve()
    sys.path.insert(0, str(source.parent))
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_meter_event_schema_and_ranges():
    producer = load_module("producers/meter_producer.py", "meter_producer")
    event = producer.build_event(1, datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert set(event) == {
        "event_id", "meter_id", "household_id", "power_consumption_kwh",
        "solar_generation_kwh", "grid_zone", "timestamp",
    }
    assert event["power_consumption_kwh"] >= 0
    assert event["solar_generation_kwh"] >= 0
    assert event["timestamp"].endswith("+00:00")


def test_reproducible_anomalies():
    producer = load_module("producers/meter_producer.py", "meter_producer_anomaly")
    assert producer.build_event(18)["solar_generation_kwh"] == 0
    assert producer.build_event(25)["power_consumption_kwh"] >= 8.5


def test_tariff_rows_cover_all_households():
    generator = load_module("producers/tariff_generator.py", "tariff_generator")
    rows = generator.tariff_rows(1)
    assert len(rows) == 30
    assert len({row["household_id"] for row in rows}) == 30
    assert all(row["tariff_rate"] > 0 for row in rows)
    assert any(row["subsidy_flag"] for row in rows)
