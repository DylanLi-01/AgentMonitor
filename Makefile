.PHONY: setup build test check run dev docker-up clean

PYTHON ?= python3
PORT ?= 8765
HOST ?= 127.0.0.1

setup:
	cd backend && $(PYTHON) -m venv .venv && . .venv/bin/activate && python -m pip install -r requirements.txt
	cd frontend && npm ci

build:
	cd frontend && npm run build

test:
	cd backend && . .venv/bin/activate && PYTHONPATH=. python -m unittest discover -s tests
	cd frontend && npm run build

check:
	./scripts/check.sh

run:
	HOST=$(HOST) PORT=$(PORT) ./scripts/start.sh

dev:
	./scripts/dev.sh

docker-up:
	./scripts/docker-up.sh

clean:
	rm -rf frontend/dist frontend/node_modules backend/.venv backend/.pytest_cache
	find backend -type d -name __pycache__ -prune -exec rm -rf {} +
