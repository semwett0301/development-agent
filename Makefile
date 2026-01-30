.PHONY: setup lint test

setup:
	pip install -e ".[dev]"
	pip install -e coding-agent -e indexer-service -e webhook-service -e reviewer-agent
	git config core.hooksPath .githooks

lint:
	pylint coding-agent indexer-service webhook-service reviewer-agent

test:
	pytest