.PHONY: help dev dev-hot stop clean build test lint migrate setup seed logs logs-backend eval

help:
	@echo ""
	@echo "  Enterprise AI Chatbot — available commands"
	@echo ""
	@echo "  make dev          Start full stack (prod images, detached)"
	@echo "  make dev-hot      Start with hot-reload (backend) + Vite dev (frontend)"
	@echo "  make build        Build all Docker images"
	@echo "  make stop         Stop all services"
	@echo "  make clean        Stop services and remove volumes (destructive!)"
	@echo "  make migrate      Run Alembic migrations inside backend container"
	@echo "  make test         Run backend unit tests"
	@echo "  make lint         Lint backend with ruff"
	@echo "  make setup        First-time setup: generate secrets + start services"
	@echo "  make logs         Tail all service logs"
	@echo "  make seed         Seed demo users and topic-guard patterns"
	@echo "  make eval         Run retrieval eval against golden_qa.json"
	@echo ""

seed:
	docker compose exec backend python -m scripts.seed_demo

eval:
	docker compose exec backend python -m scripts.eval_retrieval \
		--dataset data/eval/golden_qa.json --top-k 5

setup:
	@bash scripts/setup.sh

dev:
	docker compose up -d

dev-hot:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

build:
	docker compose build

stop:
	docker compose down

clean:
	docker compose down -v
	@echo "All containers and volumes removed."

migrate:
	docker compose exec backend alembic upgrade head

test:
	docker compose run --rm backend pytest tests/unit/ -v --tb=short

lint:
	docker compose run --rm backend ruff check .

logs:
	docker compose logs -f

logs-backend:
	docker compose logs -f backend
