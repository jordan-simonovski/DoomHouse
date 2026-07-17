# DOOMHouse — common tasks.
#
#   make sync           install Python deps (uv)
#   make db-up          start local ClickHouse (docker compose)
#   make db-down        stop it
#   make streaming      run this fork: concurrent render + streaming delivery
#   make polling        run the concurrent render with request/response delivery
#   make non-streaming  run the original engine (sequential materialized views)
#   make test           headless end-to-end test of the streaming pipeline
#
# The three engine targets each use their own ClickHouse database, so you can run
# them side by side. Read the on-screen fps counter to compare on your hardware.

.PHONY: help sync db-up db-down streaming run polling non-streaming test

help:
	@sed -n 's/^# \{0,2\}//p' $(MAKEFILE_LIST) | sed -n '2,10p'

sync:
	uv sync

db-up:
	docker compose up -d

db-down:
	docker compose down

streaming:
	uv run src/DOOMHouse.py

# alias
run: streaming

polling:
	uv run polling/DOOMHouse.py

non-streaming:
	uv run non-streaming/DOOMHouse.py

test:
	uv run test_e2e.py
