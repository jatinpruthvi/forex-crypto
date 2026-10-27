FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY core/ /app/core/
COPY services/brain_api/ /app/services/brain_api/
COPY config.yaml /app/

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "services.brain_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
