.PHONY: setup lint test

setup:
	git config core.hooksPath .githooks

lint:
	pylint coding-agent indexer-service webhook-service reviewer-agent

test:
	pytest