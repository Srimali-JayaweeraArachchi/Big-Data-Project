FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --uid 50000 --create-home appuser && mkdir -p /data/incoming /data/archive && chown -R appuser:appuser /app /data
USER appuser
