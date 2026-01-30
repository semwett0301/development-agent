.PHONY: setup lint test

setup:
	git config core.hooksPath .githooks

lint:
	pylint coding-agent webhook-service reviewer-agent

test:
	pytest