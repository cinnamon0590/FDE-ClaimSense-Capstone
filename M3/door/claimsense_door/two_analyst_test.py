"""THE M3 ACCEPTANCE TEST: two adjusters with different scopes ask the governed door the IDENTICAL question about the
same claim, and get correctly-filtered different answers, with an audit row to match each (D-4, D-5).

    python -m claimsense_door.two_analyst_test                 # offline, in-process, $0
    python -m claimsense_door.two_analyst_test --url http://localhost:8002            # the running stack (dev tokens)
    python -m claimsense_door.two_analyst_test --url https://<api>/ --cognito          # the deployed door (Cognito)
    ... [--claim CLM-2024-1800] [--a alice] [--b carol] [--out evidence/04-two-user-test.txt]
    ... --viewer        the Learning UI Viewer's Week 4 shape (D-042): alice asks first for a claim NOT assigned to
                        her (CLM-2024-5001, in the senior adjuster's queue) -> 403; bob, senior adjuster, asks the
                        same -> 200 with the full claim

Prints both full requests (token redacted), both full responses, both audit rows, and ends with
`RESULT: PASS — scope holds` (exit 0) or FAIL (exit 1). No model is in the loop: the gate is called directly.
"""
import argparse
import json
import sys
import time


def run(client, claim, a, b, deny_first=False):
    lines = [f"ClaimSense M3 · TWO-USER ACCESS TEST · {time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
             f"door: {client.mode}", f"question (identical for both): tools/call get_claim {{\"claim_id\": \"{claim}\"}}",
             ""]
    results = {}
    order = (("B", b), ("A", a)) if deny_first else (("A", a), ("B", b))
    for label, user in order:
        req, res = client.call(user, "get_claim", {"claim_id": claim})
        out = res.get("structuredContent") or {}
        results[label] = (user, req, res, out)
        expect = "expected: ALLOWED, 200 with the full claim" if label == "A" else "expected: 403 DENIED, no claim data"
        lines += [f"=== User {label}: {user} ({expect}) ===", "REQUEST:", json.dumps(req, indent=2), "RESPONSE:",
                  json.dumps({k: v for k, v in res.items() if k != "content"}, indent=2, default=str), ""]
    (ua, _, ra, oa), (ub, _, rb, ob) = results["A"], results["B"]
    a_allowed = not ra.get("isError") and oa.get("claim_id") == claim
    b_denied = rb.get("isError") and (ob.get("error") or {}).get("code") == "not_found_or_forbidden" \
        and "claim_id" not in ob
    lines.append("=== Answers ===")
    lines.append(f"  User A {ua}: " + (f"ALLOWED · {oa.get('claim_id')} · {oa.get('loss_type')} · "
                                       f"assigned_group={oa.get('assigned_group')}" if a_allowed else f"UNEXPECTED {oa}"))
    lines.append(f"  User B {ub}: " + (f"403 DENIED — {ub} may not access {claim} · the caller is told only: "
                                        f"\"{ob['error']['message']}\" (request_id {ob['error']['request_id']})"
                                       if b_denied else f"UNEXPECTED {ob}"))
    # the audit rows: B's comes back on its own error; A's is the matching allow row written for that call
    rows = client.audit()
    row_b = [r for r in rows if r["request_id"] == (ob.get("error") or {}).get("request_id")]
    row_a = [r for r in rows if r["user_id"] == ua and r["action"] == "get_claim" and r["resource"] == claim
             and r["decision"] == "allow"][-1:]
    lines += ["", "=== Append-only audit rows (one per call) ==="]
    for r in row_a + row_b:
        lines.append("  " + json.dumps({k: r.get(k) for k in ("ts", "request_id", "acting_identity", "scope", "action",
                                                                "resource", "decision", "reason", "via",
                                                                "on_behalf_of_agent")}))
    audit_ok = bool(row_a) and bool(row_b) and row_a[0]["decision"] == "allow" and row_b[0]["decision"] == "deny" \
        and all(r.get("acting_identity") and r.get("scope") is not None and r.get("action") and r.get("resource")
                and r.get("decision") for r in row_a + row_b)
    ok = a_allowed and b_denied and audit_ok
    lines += ["", f"checks: A allowed={a_allowed} · B denied with no claim data={b_denied} · "
                  f"matching allow + deny audit rows carrying user, action, resource={audit_ok}",
              f"RESULT: {'PASS — scope holds (different answers + matching audit)' if ok else 'FAIL'}"]
    return ok, "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="the door's base URL; omit for the offline in-process run")
    ap.add_argument("--cognito", action="store_true", help="get tokens from the Cognito user pool (deployed door)")
    ap.add_argument("--claim", default="CLM-2024-1800")
    ap.add_argument("--a", default="alice", help="the user who may see the claim (adjuster)")
    ap.add_argument("--b", default="carol", help="the user who may not (fraud-investigator, before any hand-off)")
    ap.add_argument("--viewer", action="store_true",
                    help="Week 4 viewer shape: alice (denied) first, then bob (allowed), on CLM-2024-5001")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.viewer:
        a.claim, a.a, a.b = "CLM-2024-5001", "bob", "alice"
    if a.url:
        from .clients import Http, dev_tokens
        if a.cognito:
            from .cognito import token_for
        else:
            token_for = dev_tokens(a.url)
        client = Http(a.url, token_for)
    else:
        from .clients import InProcess
        client = InProcess()
    ok, text = run(client, a.claim, a.a, a.b, deny_first=a.viewer)
    print(text)
    if a.out:
        from pathlib import Path
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
