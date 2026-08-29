# Technical Report Outline (recommended 8-15 pages)

## 1. Introduction and business problem

Explain the utility-company scenario and the two questions: live zone load/renewable contribution and household bills after tariff reconciliation.

## 2. Requirements and assumptions

Document the streaming and batch fields, the five-minute simulated day, 30 households, four zones, thresholds, and billing assumptions.

## 3. Lambda versus Kappa decision

Compare latency, replay, implementation duplication, consistency, cost, and operational complexity. Defend the Kappa-oriented choice and explicitly explain the retained Airflow reference-data batch path.

## 4. Architecture and data flow

Include the diagram from the README and a second deployment diagram showing Docker services, ports, volumes, and dependencies.

## 5. Technology stack justification

Tie each technology to a scenario constraint. Avoid generic claims based only on popularity.

## 6. Ingestion implementation

Describe Kafka keys, three partitions, `acks=all`, retries, atomic tariff file drops, schema validation, idempotency, and the compressed clock.

## 7. Processing implementation

Explain validation, quarantine, event time, one-minute windows, enrichment equations, household aggregation, thresholds, and daily tariff reconciliation.

## 8. Storage and serving

Show the main PostgreSQL tables and primary keys. Explain the FastAPI endpoints and Streamlit panels.

## 9. Observability

Cover JSON logs, heartbeats, `/health`, `/metrics`, Airflow history, alert rules, and a no-data failure demonstration.

## 10. Results

Include screenshots of:

- `docker compose ps`
- Kafka producer logs
- Spark micro-batch logs
- Successful Airflow DAG
- API health/metrics
- Dashboard overview and zone charts
- Alerts and daily billing report

## 11. Testing

Report unit-test results, Compose validation, end-to-end record counts, and the producer-stop health-check test.

## 12. Limitations and production evolution

Discuss single-node availability, database sink scalability, security, schema registry, dead-letter retention, alert routing, object storage, and centralized observability.

## 13. Conclusion

Answer the business question using representative dashboard/report results.

