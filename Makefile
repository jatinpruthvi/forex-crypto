.PHONY: setup test run-api run-collector lint backup clean

setup:
	python3 -m venv venv && \
	. venv/bin/activate && \
	pip install --upgrade pip && \
	pip install -r requirements.txt

test:
	pytest -v tests/ core/

run-api:
	uvicorn services.brain_api.main:app --host 0.0.0.0 --port 8000 --reload

run-collector:
	python services/data_collector/collector.py

backup:
	./scripts/backup.sh

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
