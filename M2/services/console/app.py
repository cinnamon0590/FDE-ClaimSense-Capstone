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
for _extra in (os.environ.get("M2_CASES_FILE", "/app/M2/evals/cases-m2.json"),
               os.environ.get("M4_CASES_FILE", "/app/M4/evals/cases-m4.json")):
    if os.path.exists(_extra):
        CASES += json.loads(open(_extra).read())["cases"]
SIGNIN = os.environ.get("CLAIMSENSE_SIGNIN") == "1"   # deployed console (D-056): each person signs in as themself
CLAUSES = {c["clause_id"]: c for c in json.loads(open(os.environ.get(
    "CLAUSES_FILE", "/app/M1/6-synthetic-data/fixtures/clauses.json")).read())["records"]}
USERS = {u["user_id"]: f'{u["display_name"].replace(" (synthetic)", "")} · {u["groups"][0].replace("-", " ")}'
         for u in json.loads(open(os.environ.get("USERS_FILE", "/app/M1/6-synthetic-data/fixtures/users.json")).read())["records"]}
# the directory decides who can sign in (runbook "Add or remove a user"); the role shown is the directory's group
BADGE = {"agents": ("🧠 Model verdict", "green"), "guardrail_hold": ("🛡 Guardrail hold → human", "orange"),
         "consistency_hold": ("⚖ Model unsure (two drafts disagreed) → human", "orange"),
         "fallback": ("⚙ Deterministic fallback (not AI)", "gray"), "boundary_refusal": ("⛔ Refused at the boundary", "red"),
         "unavailable": ("⏸ Claim systems unavailable: nothing decided, try again", "orange")}

st.set_page_config(page_title="ClaimSense · AutoSure", page_icon="🚗", layout="wide")
st.title("ClaimSense AI · first-pass co-pilot")
st.caption("AutoSure Insurance motor claims · SYNTHETIC DATA · a licensed adjuster confirms every outcome")

qp = st.query_params
with st.sidebar:
    users = list(USERS)
    AUTH, user = {}, None
    if SIGNIN:
        # D-056: who you are comes ONLY from your own username and password, checked by Cognito. There is no user
        # picker: to act as someone else you would need their password. Signing out is the only way to switch.
        if not st.session_state.get("token"):
            with st.form("signin", clear_on_submit=True):          # the password never stays in the page
                st.markdown("**Sign in** with your own AutoSure account")
                f_user = st.text_input("Username")
                f_pw = st.text_input("Password", type="password")
                go = st.form_submit_button("Sign in", type="primary", use_container_width=True)
            if go:
                try:
                    r = httpx.post(f"{ORCH}/signin", json={"username": f_user, "password": f_pw}, timeout=15)
                    body = r.json()
                except (httpx.HTTPError, ValueError):
                    r, body = None, {}
                if r is not None and r.status_code == 200:
                    st.session_state.update(token=body["token"], token_for=body["user_id"],
                                            token_groups=body["groups"])
                    st.rerun()
                st.error((body.get("error") or {}).get("message") or "Sign-in failed: the identity service is not reachable.")
        else:
            user = st.session_state["token_for"]
            AUTH = {"Authorization": f"Bearer {st.session_state['token']}"}
            st.info(f"🔐 Signed in as **{user}** · role **{', '.join(st.session_state['token_groups'])}** "
                    "(from your Cognito token, checked against the directory)")
            if st.button("Sign out", use_container_width=True):
                for k in ("token", "token_for", "token_groups", "result"):
                    st.session_state.pop(k, None)
                st.query_params.clear()
                st.rerun()
    else:                                                         # local stack only: the dev issuer's user picker
        user = st.selectbox("Sign in as (dev login; local stack only)", users, format_func=USERS.get,
                            index=users.index(qp["user"]) if qp.get("user") in USERS else 0)
    seen, options = set(), []
    for c in CASES:
        if c["claim"]["claim_id"] not in seen:
            seen.add(c["claim"]["claim_id"]); options.append(c)
    ids = [c["claim"]["claim_id"] for c in options]
    case = st.selectbox("Claim", options, format_func=lambda c: f"{c['claim']['claim_id']} · {c['title']}",
                        index=ids.index(qp["claim"]) if qp.get("claim") in ids else 0)
    if not SIGNIN:
        # identity (D-030): a signed ID token for the chosen synthetic user from the LOCAL dev issuer. The GROUP is not
        # chosen here: it is in the token, issued from the directory, and re-checked by the boundary on every call
        try:
            if st.session_state.get("token_for") != user:
                t = httpx.post(f"{BOUNDARY}/dev/token", json={"user_id": user}, timeout=5).json()
                st.session_state.update(token_for=user, token=t["token"], token_groups=t["groups"])
            AUTH = {"Authorization": f"Bearer {st.session_state['token']}"}
            st.info(f"🔐 **{user}** · role **{', '.join(st.session_state['token_groups'])}** (from the signed token, "
                    "checked against the directory)")
        except (httpx.HTTPError, KeyError):
            AUTH = {}
            st.session_state.pop("token_for", None)
            st.error("could not obtain a token from the identity issuer")
    try:
        h = httpx.get(f"{ORCH}/healthz", timeout=3).json()
        st.success(f"brain: **{h['brain']}** · retrieval: {h['retrieval']}")
        st.caption(f"fast {h['models']['fast']} · smart {h['models']['smart']}")
    except httpx.HTTPError:
        st.error("orchestrator not reachable")
    run = st.button("Run co-pilot", type="primary", use_container_width=True, disabled=not AUTH,
                    help=None if AUTH else "Sign in first (sidebar)")
    if not AUTH:
        st.warning("Sign in first, with your own username and password (sidebar)." if SIGNIN else "Not signed in.")

claim_id = case["claim"]["claim_id"]


def escalate_panel(claim_id, run_id, card):
    """Manual escalation to SIU (runbook "Escalate a flagged claim manually", M4): a person decides, the door checks
    the grant and the entitlement, the ticket carries a link and the reason, never claim data. Idempotent per run."""
    flagged = card.get("outcome") in ("flag_review", "route") or card.get("guardrails_fired")
    with st.expander("🚩 Escalate to SIU (manual)", expanded=bool(flagged)):
        reason = st.text_area("Why (goes on the ticket; no claim data)", key=f"esc_reason_{run_id}")
        prio = st.selectbox("Priority", ["normal", "high"], key=f"esc_prio_{run_id}")
        if st.button("Escalate to SIU", key=f"esc_go_{run_id}", disabled=not reason.strip()):
            r = httpx.post(f"{BOUNDARY}/claims/{claim_id}/escalations", json={"reason": reason, "priority": prio},
                           headers={**AUTH, "Idempotency-Key": f"manual-{run_id}"}, timeout=20)
            body = r.json()
            if r.status_code == 200:
                st.success(f"Ticket **{body['ticket_id']}** · {body['status']}"
                           + (" (already escalated for this run)" if body.get("idempotent_replay") else ""))
            else:
                err = body.get("error", {})
                st.error(f"{err.get('message', r.text)} · request `{err.get('request_id', '-')}`. If ticketing is down "
                         "or not configured, follow the runbook's manual fallback (page SIU on call).")
        s = httpx.get(f"{BOUNDARY}/claims/{claim_id}/escalation", headers=AUTH, timeout=10)
        if s.status_code == 200:
            e = s.json()
            st.caption(f"Escalation: {e.get('ticket_id') or 'queued'} · {e.get('status')}")


def show_decision(result):
    if result.get("handed_off"):
        h = result["handed_off"]
        st.success(f"↪ {h['claim_id']} handed off: {h['from']} → **{h['to']}** queue. Only that group (and senior "
                   "adjusters) can open it now.")
    st.json(result)


def decide_draft(rec_id, body):
    """Confirm/override through the boundary. Stable key per (draft, user, decision): a resubmit replays the receipt."""
    key = hashlib.sha256(json.dumps([rec_id, user, body], sort_keys=True).encode()).hexdigest()[:32]
    return httpx.post(f"{BOUNDARY}/recommendations/{rec_id}/confirm", json=body,
                      headers=AUTH | {"Idempotency-Key": key}).json()

tab_run, tab_queue = st.tabs(["Co-pilot", "Adjuster queue"])

with tab_run:
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
                              json={"run_id": run_id}, headers=AUTH, timeout=180) as r:
                if r.status_code != 200:                 # refused (e.g. signed out): say so, never crash
                    r.read()
                    try:
                        msg = r.json().get("error", {}).get("message", r.text)
                    except ValueError:
                        msg = r.text
                    status.update(label=f"Refused ({r.status_code})", state="error")
                    if r.status_code == 401 and SIGNIN:         # expired or revoked token: sign in again
                        for k in ("token", "token_for", "token_groups"):
                            st.session_state.pop(k, None)
                    st.error(f"{msg} Sign in again in the sidebar." if r.status_code == 401 else msg)
                    st.stop()
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
            elif card.get("outcome") == "unavailable":           # the door is down (D-050): nothing was decided
                st.warning(card.get("message", "The claim systems are unavailable. Nothing was decided; try again."))
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
                        return decide_draft(rec["recommendation_id"], body)
                    if col1.button("Confirm as drafted"):
                        show_decision(decide({"action": "confirm"}))
                    if col2.button("Override"):
                        show_decision(decide({"action": "override", "final_outcome": final, "override_reason": reason}))
                escalate_panel(claim_id, res.get("run_id", ""), card)
            with st.expander("Agent outputs (typed)"):
                for ev in res["events"]:
                    if ev["kind"] == "agent_end":
                        st.markdown(f"**{ev['name']}**")
                        st.json(ev["output"], expanded=False)

    # ── Ask ClaimSense: follow-up questions (SDK handoff + SQLiteSession + run_streamed, D-028) ──────────────
    if res and res["claim_id"] == claim_id and res["response"].get("outcome") != "refused":
        try:
            hist = httpx.get(f"{ORCH}/claims/{claim_id}/ask/history", headers=AUTH, timeout=10).json()
        except httpx.HTTPError:
            hist = {"messages": None}
        # stays open once a conversation exists (a submit reruns the page; a closed panel would hide the answer)
        with c2, st.expander("💬 Ask ClaimSense about this claim", expanded=bool(hist.get("messages"))):
            st.caption("Explains the draft and the policy wording; never decides. Policy questions are handed off to "
                       "the Coverage specialist. Your conversation is kept per claim and survives restarts.")
            if hist.get("messages") is None:
                st.caption("conversation history unavailable")
            for m in hist.get("messages") or []:
                st.chat_message(m["role"]).write(m["text"])
            question = st.chat_input("Ask about this claim, e.g. 'Why is the net payable $2,700?'")
            if question:
                st.chat_message("user").write(question)
                box, trail, text = st.chat_message("assistant"), [], ""
                with box:
                    status_line, answer_area = st.empty(), st.empty()
                    with httpx.stream("POST", f"{ORCH}/claims/{claim_id}/ask",
                                      json={"question": question}, headers=AUTH, timeout=120) as r:
                        for line in r.iter_lines():
                            ev = json.loads(line)
                            if ev["kind"] == "delta":
                                text += ev["text"]
                                answer_area.markdown(text)
                            elif ev["kind"] in ("agent", "tool", "handoff"):
                                trail.append({"agent": "🤖", "tool": "⛁", "handoff": "➜"}[ev["kind"]] + " " + ev["name"])
                                status_line.caption(" · ".join(trail))
                            elif ev["kind"] == "guardrail":
                                st.warning("🛡 Answer withheld by the grounding guardrail: " + "; ".join(ev.get("problems", [])))
                            elif ev["kind"] == "answer":
                                answer_area.markdown(ev["answer"])
                                st.caption(f"{' → '.join(ev['agents'])} · ${ev['cost_usd']:.4f} · {ev['latency_s']}s")
                            elif ev["kind"] in ("refusal", "error"):
                                st.error(ev.get("code") or ev.get("error"))

with tab_queue:
    st.subheader(f"Adjuster queue · {USERS.get(user, 'not signed in')}")
    st.caption("Undecided drafts on claims you are entitled to, newest first (from the boundary; every view is audited).")
    queue = None
    if not AUTH:
        st.info("Sign in to see your queue.")
    else:
        try:
            queue = httpx.get(f"{BOUNDARY}/recommendations", params={"status": "pending"},
                              headers=AUTH, timeout=10).json().get("pending", [])
        except httpx.HTTPError:
            st.error("boundary not reachable")
    if queue == []:
        st.info("Nothing waiting. Run the co-pilot on a claim and its draft lands here.")
    for item in queue or []:
        route = f" → {item['route_to']}" if item.get("route_to") else ""
        net = item.get("net_payable")
        with st.container(border=True):
            a, b, c = st.columns([3, 2, 2])
            a.markdown(f"**{item['claim_id']}** · {(item.get('outcome') or '?').upper()}{route}")
            a.caption(f"draft {item['recommendation_id']} v{item.get('version') or '?'} · "
                      f"{(item.get('created_at') or 'drafted before queue metadata')[:19]}")
            b.markdown(f"net payable: **{'$' + format(net, ',') if net is not None else '—'}**")
            b.caption("model verdict" if item.get("verdict_source") == "model" else "deterministic fallback")
            if item.get("guardrails_fired"):
                c.warning(", ".join(item["guardrails_fired"]))
            if c.button("Confirm as drafted", key=f"q-{item['recommendation_id']}"):
                show_decision(decide_draft(item["recommendation_id"], {"action": "confirm"}))
            c.link_button("Open claim", f"?claim={item['claim_id']}&user={user}")
