FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY core/ /app/core/
COPY services/data_collector/ /app/services/data_collector/
COPY config.yaml /app/

ENV PYTHONPATH=/app

CMD ["python", "services/data_collector/collector.py"]
