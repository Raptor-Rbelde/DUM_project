PYTHON ?= python3
API_HOST ?= 127.0.0.1
API_PORT ?= 8000

.PHONY: install install-dev test api web dev clean

install:
	$(PYTHON) -m pip install -r requirements.txt

install-dev:
	$(PYTHON) -m pip install -r requirements-dev.txt
	cd apps/web && npm install

test:
	$(PYTHON) -m pytest

api:
	$(PYTHON) -m uvicorn apps.api.main:app --host $(API_HOST) --port $(API_PORT) --reload

web:
	cd apps/web && npm run dev

dev:
	@echo "Run 'make api' and 'make web' in separate terminals."

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache apps/web/node_modules apps/web/dist
