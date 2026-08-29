FROM python:3.12-slim-bookworm
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends openjdk-17-jre-headless procps \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY streaming_job.py .
CMD ["spark-submit", "--master", "local[2]", "--driver-memory", "1536m", "--packages", "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.9", "streaming_job.py"]
