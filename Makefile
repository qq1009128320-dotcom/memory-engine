.PHONY: help install test lint format clean run audit check

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install:  ## Install dependencies
	python3 -m venv venv
	. venv/bin/activate && pip install -e ".[dev]"

test:  ## Run tests
	. venv/bin/activate && pytest tests/ -v --tb=short

test-cov:  ## Run tests with coverage
	. venv/bin/activate && pytest tests/ -v --cov=. --cov-report=term-missing --cov-report=xml

lint:  ## Run linters
	. venv/bin/activate && ruff check .
	. venv/bin/activate && mypy . --ignore-missing-imports

format:  ## Auto-format code
	. venv/bin/activate && ruff check --fix .
	. venv/bin/activate && ruff format .

clean:  ## Clean build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache

run:  ## Start MCP server
	. venv/bin/activate && python3 memory_server.py

audit:  ## Run security audit
	. venv/bin/activate && pip-audit || echo "Install pip-audit: pip install pip-audit"

check: lint test  ## Run all checks

init-db:  ## Initialize database
	. venv/bin/activate && python3 -c "from memory_server import _init_db; _init_db()"

reindex:  ## Rebuild FAISS index
	. venv/bin/activate && python3 -c "from memory_server import memory_tree_reindex; print(memory_tree_reindex())"

stats:  ## Show memory stats
	. venv/bin/activate && python3 -c "from memory_server import memory_stats, memory_health; import json; print(json.dumps(memory_stats(), indent=2, ensure_ascii=False)); print('---'); print(json.dumps(memory_health(), indent=2, ensure_ascii=False))"
