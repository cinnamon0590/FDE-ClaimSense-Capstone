# ClaimSense M2 · one-command operations (run from M2/)
PY ?= ../.venv/bin/python
.PHONY: up down logs smoke test evals evals-live record replays fixtures

up:            ## build and start the whole stack (console on http://localhost:8510)
	docker compose up --build -d && docker compose ps
down:
	docker compose down
logs:
	docker compose logs -f --tail=100
smoke:         ## one claim per outcome through the running stack
	$(PY) evals/stack_smoke.py
test:          ## unit + integration tests ($0, no key)
	$(PY) -m pytest -q tests
evals:         ## eval gate on the replay brain ($0, deterministic) — what CI runs on every PR
	$(PY) evals/run_evals.py
evals-live:    ## eval gate on the live models (needs OPENAI_API_KEY; ~$0.50)
	MOCK_BRAIN=0 $(PY) evals/run_evals.py --brain live
record:        ## live run that also re-records the replay files (then commit them)
	MOCK_BRAIN=0 $(PY) evals/run_evals.py --brain live --record
replays:       ## regenerate scripted replays (never overwrites recorded ones)
	$(PY) evals/script_replays.py
fixtures:      ## regenerate + validate synthetic fixtures from the eval cases
	cd ../M1/6-synthetic-data && ../../.venv/bin/python -I generate_fixtures.py && ../../.venv/bin/python -I validate_data.py
