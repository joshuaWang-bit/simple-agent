.PHONY: install test lint gen-proto

install:
	uv sync

test:
	uv run pytest tests/

gen-proto:
	uv run python scripts/gen_protocol_doc.py
