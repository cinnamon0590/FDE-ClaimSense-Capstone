"""ClaimSense adjuster console (Streamlit): run the co-pilot on a claim, watch the four agents work,
and confirm or override the draft. Synthetic data only. The user picker stands in for the Cognito
login that M3 adds; entitlement is still enforced by the boundary, not by this page.

Refresh-safe (D-027): the run lives in the URL (?claim=&user=&run=). A refresh, a reopened tab or a console
restart picks the same run up again: a finished run comes back from checkpoints at $0, an unfinished one
resumes, and one still in progress is JOINED, never duplicated.
"""
import hashlib
import json
import os
import uuid

import httpx
import streamlit as st

ORCH = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8003")
BOUNDARY = os.environ.get("BOUNDARY_URL", "http://localhost:8002")
CASES = json.loads(open(os.environ.get("CASES_FILE", "/app/M0/evals/cases.json")).read())["cases"]
M2_CASES = os.environ.get("M2_CASES_FILE", "/app/M2/evals/cases-m2.json")
if os.path.exists(M2_CASES):
    CASES += json.loads(open(M2_CASES).read())["cases"]
CLAUSES = {c["clause_id"]: c for c in json.loads(open(os.environ.get(
    "CLAUSES_FILE", "/app/M1/6-synthetic-data/fixtures/clauses.json")).read())["records"]}
USERS = {"alice": "Alice · adjuster", "bob": "Bob · senior adjuster", "carol": "Carol · fraud investigator",
         "eve": "Eve · total-loss appraiser", "dave": "Dave · customer service"}
BADGE = {"agents": ("🧠 Model verdict", "green"), "guardrail_hold": ("🛡 Guardrail hold → human", "orange"),
         "consistency_hold": ("⚖ Model unsure (two drafts disagreed) → human", "orange"),
         "fallback": ("⚙ Deterministic fallback (not AI)", "gray"), "boundary_refusal": ("⛔ Refused at the boundary", "red")}

st.set_page_config(page_title="ClaimSense · AutoSure", page_icon="🚗", layout="wide")
st.title("ClaimSense AI · first-pass co-pilot")
st.caption("AutoSure Insurance motor claims · SYNTHETIC DATA · a licensed adjuster confirms every outcome")

qp = st.query_params
with st.sidebar:
    users = list(USERS)
    user = st.selectbox("Signed in as (M3: Cognito)", users, format_func=USERS.get,
                        index=users.index(qp["user"]) if qp.get("user") in USERS else 0)
    seen, options = set(), []
    for c in CASES:
        if c["claim"]["claim_id"] not in seen:
            seen.add(c["claim"]["claim_id"]); options.append(c)
    ids = [c["claim"]["claim_id"] for c in options]
    case = st.selectbox("Claim", options, format_func=lambda c: f"{c['claim']['claim_id']} · {c['title']}",
                        index=ids.index(qp["claim"]) if qp.get("claim") in ids else 0)
    try:
        h = httpx.get(f"{ORCH}/healthz", timeout=3).json()
        st.success(f"brain: **{h['brain']}** · retrieval: {h['retrieval']}")
        st.caption(f"fast {h['models']['fast']} · smart {h['models']['smart']}")
    except httpx.HTTPError:
        st.error("orchestrator not reachable")
    run = st.button("Run co-pilot", type="primary", use_container_width=True)

claim_id = case["claim"]["claim_id"]
c1, c2 = st.columns([2, 3])
with c1:
    st.subheader("Claim file (as the systems hold it)")
    st.json({k: case["claim"][k] for k in ("claim_id", "loss_type", "incident_date", "acv", "repair_estimate",
                                           "injury_reported", "fraud_risk_score")}, expanded=False)
    st.write(case["claim"]["narrative"])

# which run to show: a new one (button), or the one in the URL after a refresh / reopened tab / restart
run_id, picked_up = None, False
if run:
    run_id = f"{claim_id}:{uuid.uuid4().hex[:12]}"
    st.query_params.update(claim=claim_id, user=user, run=run_id)
elif qp.get("run") and qp.get("claim") == claim_id and qp.get("user") == user:
    have = st.session_state.get("result")
    if not (have and have.get("run_id") == qp["run"]):
        run_id, picked_up = qp["run"], True

if run_id:
    st.session_state.pop("result", None)
    label = "Picking up run after a refresh" if picked_up else "Running Intake → Coverage → Assessment → Decision Draft"
    with c2, st.status(label, expanded=True) as status:
        with httpx.stream("POST", f"{ORCH}/claims/{claim_id}/recommend/stream",
                          json={"user_id": user, "run_id": run_id}, timeout=180) as r:
            for line in r.iter_lines():
                ev = json.loads(line)
                k = ev["kind"]
                if k == "joined":
                    st.write("↻ **Joined the run already in progress** (nothing is run twice)")
                elif k == "run" and ev.get("resumed"):
                    st.write("↻ **Resuming from checkpoints**: finished agents are restored, not re-run or re-billed")
                elif k == "checkpoint":
                    st.write(f"　↺ {ev['name']}")
                elif k == "result":
                    st.session_state["result"] = ev["result"]
                elif k == "error":
                    st.error(ev["error"])
                elif k == "agent_start":
                    st.write(f"◆ **{ev['name']}** · `{ev['model']}`")
                elif k == "agent_end":
                    st.write(f"　✓ {ev['name']} done in {ev['seconds']}s")
                elif k == "tool":
                    detail = {x: ev[x] for x in ev if x not in ("t", "kind", "name")}
                    st.write(f"　⛁ `{ev['name']}` {detail}")
                elif k == "guardrail" and ev.get("tripped"):
                    st.write(f"　🛡 **TRIPPED** `{ev['name']}`")
                elif k == "handoff":
                    st.write(f"　➜ {ev['name']}")
                elif k == "refusal":
                    st.write(f"⛔ boundary refused: `{ev['code']}`")
                elif k == "fallback":
                    st.write(f"⚙ fallback: {ev['name']}")
                elif k == "computed":
                    st.write(f"　∑ code computed: net payable {ev['net_payable']}, ratio {ev['repair_to_acv_ratio']}")
        status.update(label="Done", state="complete")

res = st.session_state.get("result")
if res and res["claim_id"] == claim_id:
    card = res["response"]
    label, colour = BADGE[res["decided_by"]]
    with c2:
        st.subheader("Draft recommendation")
        st.markdown(f":{colour}-background[{label}] · verdict_source=`{card.get('verdict_source')}` · "
                    f"${res['cost_usd']:.4f} · {res['latency_s']}s · trace `{res.get('trace_id', '')}`")
        how = "joined in progress" if res.get("joined") else ("resumed from checkpoints" if res.get("resumed") else "new run")
        st.caption(f"run `{res.get('run_id')}` · {how} · refresh-safe: this page's URL picks it up again")
        if card.get("outcome") == "refused":
            st.error("No claim data returned. The caller isn't entitled to this claim (the reason is in the audit log only).")
        else:
            route = f" → {card['route_to']}" if card.get("route_to") else ""
            st.markdown(f"## {card['outcome'].upper()}{route}")
            st.write(card["reasoning"])
            a, b = st.columns(2)
            a.markdown("**Computed by code** (never the model)")
            a.json(card["computed"])
            b.markdown("**Model judgment**")
            b.json(card["judgment"])
            st.markdown("**Citations** (retrieved for this request only)")
            for cit in card["citations"]:
                cl = CLAUSES.get(cit["source_id"], {})
                st.markdown(f"- `{cit['source_id']}` {cl.get('title', '')}: *{cl.get('text', cit.get('quote', ''))[:220]}*")
            if card["guardrails_fired"]:
                st.warning("Guardrails fired: " + ", ".join(card["guardrails_fired"]))
            rec = res.get("receipt") or {}
            if rec.get("recommendation_id"):
                st.caption(f"Draft {rec['recommendation_id']} v{rec.get('version')} · {rec.get('status')}")
                col1, col2 = st.columns(2)
                reason = col2.text_input("Override reason (required to override)")
                final = col2.selectbox("Override to", ["approve", "flag_review", "route", "deny"])
                def decide(body):
                    # stable key per (draft, user, decision): a resubmit or double-click replays the receipt
                    key = hashlib.sha256(json.dumps([rec["recommendation_id"], user, body], sort_keys=True).encode()).hexdigest()[:32]
                    return httpx.post(f"{BOUNDARY}/recommendations/{rec['recommendation_id']}/confirm", json=body,
                                      headers={"X-User-Id": user, "Idempotency-Key": key}).json()
                if col1.button("Confirm as drafted"):
                    st.json(decide({"action": "confirm"}))
                if col2.button("Override"):
                    st.json(decide({"action": "override", "final_outcome": final, "override_reason": reason}))
        with st.expander("Agent outputs (typed)"):
            for ev in res["events"]:
                if ev["kind"] == "agent_end":
                    st.markdown(f"**{ev['name']}**")
                    st.json(ev["output"], expanded=False)
