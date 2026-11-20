# ClaimSense M3: the governed door. All targets run from M3/.
PY ?= ../.venv/bin/python
DOORPATH = PYTHONPATH=../M2:door

.PHONY: test two-user proofs-offline selftest up down proofs viewer-deployed deploy teardown gateway-plan

test: two-user proofs-offline selftest  ## 52 M3 tests + the offline proofs ($0, no containers)
	cd .. && $(PY:../%=%) -m pytest -q M3/tests

two-user:         ## THE acceptance test (exit 0/1): python -m claimsense_door.two_analyst_test
	$(DOORPATH) $(PY) -m claimsense_door.two_analyst_test

proofs-offline:   ## every door proof in-process: lab floor, Builder, Architect, six attacks
	$(DOORPATH) $(PY) -m claimsense_door.proofs

selftest:         ## the MCP protocol self-test (initialize -> list -> call -> dedupe -> deny)
	$(DOORPATH) $(PY) -m claimsense_door.stdio --selftest

up:               ## the M3 stack (door, ticketing, mock systems, OpenSearch, orchestrator, console)
	MOCK_BRAIN=$${MOCK_BRAIN:-1} docker compose up --build -d --wait

down:
	docker compose down -v

proofs:           ## every running-stack check; writes evidence/04..09 and 20
	$(DOORPATH) $(PY) -m claimsense_door.two_analyst_test --url http://localhost:8002 --out evidence/04-two-user-test-stack.txt
	$(PY) evals/route_auth_check.py
	$(PY) evals/refusal_before_agents.py
	$(PY) evals/webhook_check.py
	$(PY) evals/mcp_interop_check.py
	$(PY) evals/audit_check.py
	$(PY) evals/viewer_week4_check.py

viewer-deployed:  ## evidence/21: the Learning UI Viewer's Week 4 checks on AWS, incl. CloudWatch (needs `aws login`)
	$(PY) evals/viewer_week4_check.py --deployed

deploy:           ## AWS (needs `aws login`): API Gateway + Lambda + Cognito; ~$0
	cloud/deploy.sh

teardown:
	cloud/teardown.sh

keycloak-up:      ## OBO at a real IdP: Keycloak does the RFC 8693 exchange (D-041, local, $0)
	$(PY) keycloak/setup.py up

keycloak-proof:   ## evidence/19: the Keycloak-exchanged token's scope drives _authorize
	$(PY) evals/keycloak_obo_check.py

keycloak-down:
	$(PY) keycloak/setup.py down

gateway-plan:     ## the AgentCore Gateway twin's plan ($0, no credentials)
	$(PY) agentcore_gateway/gateway_setup.py plan
