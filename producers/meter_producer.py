import json
import os
import random
import signal
import time
import uuid
from datetime import datetime, timezone

from kafka import KafkaProducer

from common import get_logger

os.environ["SERVICE_NAME"] = "meter-producer"
logger = get_logger(__name__)
running = True

HOUSEHOLDS = [f"H{i:03d}" for i in range(1, 31)]
ZONES = ["NORTH", "SOUTH", "EAST", "WEST"]


def build_event(sequence: int, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    household_number = (sequence % len(HOUSEHOLDS)) + 1
    household_id = f"H{household_number:03d}"
    consumption = round(random.uniform(0.4, 6.5), 3)
    solar = round(random.uniform(0.0, min(consumption * 1.2, 4.5)), 3)

    # Deterministic anomalies make the alert path reproducible during a demo.
    if sequence > 0 and sequence % 25 == 0:
        consumption = round(random.uniform(8.5, 12.0), 3)
    if sequence > 0 and sequence % 18 == 0:
        solar = 0.0

    return {
        "event_id": str(uuid.uuid4()),
        "meter_id": f"M{household_number:03d}",
        "household_id": household_id,
        "power_consumption_kwh": consumption,
        "solar_generation_kwh": solar,
        "grid_zone": ZONES[(household_number - 1) % len(ZONES)],
        "timestamp": now.isoformat(),
    }


def stop(_signum, _frame):
    global running
    running = False


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    topic = os.getenv("KAFKA_TOPIC", "smart-meter-readings")
    interval = float(os.getenv("METER_INTERVAL_SECONDS", "2"))
    producer = KafkaProducer(
        bootstrap_servers=bootstrap,
        key_serializer=lambda value: value.encode("utf-8"),
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
        acks="all",
        retries=10,
        linger_ms=100,
    )
    logger.info("connected to Kafka", extra={"event": "producer_started"})
    sequence = 0
    try:
        while running:
            event = build_event(sequence)
            producer.send(topic, key=event["household_id"], value=event).get(timeout=15)
            logger.info(
                "meter event published",
                extra={"event": "event_published", "meter_id": event["meter_id"]},
            )
            sequence += 1
            time.sleep(interval)
    finally:
        producer.flush(timeout=10)
        producer.close()


if __name__ == "__main__":
    main()

