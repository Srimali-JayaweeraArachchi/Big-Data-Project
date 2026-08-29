import csv
import os
import random
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

from common import get_logger

os.environ["SERVICE_NAME"] = "tariff-generator"
logger = get_logger(__name__)
running = True


def tariff_rows(simulated_day: int) -> list[dict]:
    rows = []
    for number in range(1, 31):
        tier = "SUBSIDISED" if number % 7 == 0 else ("PEAK" if number % 5 == 0 else "STANDARD")
        rate = {"SUBSIDISED": 22.0, "STANDARD": 35.5, "PEAK": 46.0}[tier]
        rows.append(
            {
                "household_id": f"H{number:03d}",
                "tariff_rate": round(rate + random.uniform(-0.5, 0.5), 2),
                "billing_tier": tier,
                "subsidy_flag": tier == "SUBSIDISED",
                "effective_date": datetime.now(timezone.utc).date().isoformat(),
                "simulated_day": simulated_day,
            }
        )
    return rows


def write_tariff_file(output_dir: Path, simulated_day: int) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / f"tariffs_day_{simulated_day:04d}.csv"
    temporary_path = final_path.with_suffix(".tmp")
    rows = tariff_rows(simulated_day)
    with temporary_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    temporary_path.replace(final_path)
    return final_path


def stop(_signum, _frame):
    global running
    running = False


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    output_dir = Path(os.getenv("OUTPUT_DIR", "/data/incoming"))
    day_seconds = int(os.getenv("SIMULATED_DAY_SECONDS", "300"))
    simulated_day = 1
    while running:
        path = write_tariff_file(output_dir, simulated_day)
        logger.info(
            "daily tariff file created",
            extra={"event": "batch_file_created", "file": path.name, "records": 30},
        )
        simulated_day += 1
        for _ in range(day_seconds):
            if not running:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()

