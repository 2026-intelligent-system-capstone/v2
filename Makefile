.PHONY: api streamlit test lint format qdrant-up qdrant-down qdrant-reset qdrant-status reset-demo-data

api:
	uv run uvicorn services.api.app.main:app --reload

streamlit:
	uv run streamlit run apps/streamlit/Home.py

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .

qdrant-up:
	docker compose up -d qdrant

qdrant-down:
	docker compose down

qdrant-reset:
	docker compose down -v
	docker compose up -d qdrant

qdrant-status:
	@curl -s http://localhost:6333/collections | python3 -m json.tool

reset-demo-data:
	./scripts/reset-demo-data.sh
