"""Draw the ClaimSense architecture AS BUILT through M3 (stdlib only). The M1 design stays in draw_architecture.py.

    python3 -I draw_architecture_as_built.py      # writes architecture-as-built.svg

Same layered layout and colours as the M1 reference architecture, updated to what is running: the governed MCP
door on API Gateway + Lambda, deny-by-default grants, per-adjuster assignment, delegated (OBO) tokens, the 4th system
(SIU ticketing) with signed webhooks, Slack on-call, the S3 document store, CloudWatch audit lines, and the m2-v10
agents. Solid borders are deployed on AWS; dashed borders run locally in containers.
"""
from html import escape
from pathlib import Path

W, H = 1600, 1215
C = {  # fill, stroke
    "human": ("#E8F5E9", "#2E7D32"), "code": ("#E3F2FD", "#1565C0"), "model": ("#FFF3E0", "#E65100"),
    "store": ("#FAFAFA", "#616161"), "ops": ("#F3E5F5", "#6A1B9A"), "ext": ("#FFFFFF", "#9E9E9E"),
}
out = []


def band(x, y, w, h, kind, label, lx=12, bottom=False):
    fill, stroke = C[kind]
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" fill-opacity="0.45" '
               f'stroke="{stroke}" stroke-width="1.5" stroke-dasharray="6 4"/>')
    ty = y + h - 7 if bottom else y + 17
    out.append(f'<text x="{x + lx}" y="{ty}" font-size="12.5" font-weight="700" fill="{stroke}">{escape(label)}</text>')


def box(x, y, w, h, kind, lines, dashed=False):
    fill, stroke = C[kind]
    dash = ' stroke-dasharray="5 3"' if dashed else ""
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="{fill}" stroke="{stroke}" stroke-width="2"{dash}/>')
    n = len(lines)
    for i, t in enumerate(lines):
        bold = ' font-weight="700"' if i == 0 else ""
        size = 13 if i == 0 else 11
        ty = y + h / 2 + (i - (n - 1) / 2) * 14 + 4
        out.append(f'<text x="{x + w / 2}" y="{ty:.1f}" font-size="{size}" text-anchor="middle"{bold} fill="#212121">{escape(t)}</text>')


def flow(points, num, color="#37474F", badge_at=0.5, dashed=False):
    pts = " ".join(f"{x},{y}" for x, y in points)
    dash = ' stroke-dasharray="4 3"' if dashed else ""
    out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.8" marker-end="url(#arrow)"{dash}/>')
    if num:
        # badge on the longest segment
        segs = list(zip(points, points[1:]))
        (x1, y1), (x2, y2) = max(segs, key=lambda s: abs(s[1][0] - s[0][0]) + abs(s[1][1] - s[0][1]))
        bx, by = x1 + (x2 - x1) * badge_at, y1 + (y2 - y1) * badge_at
        out.append(f'<circle cx="{bx}" cy="{by}" r="11" fill="#263238"/>'
                   f'<text x="{bx}" y="{by + 4}" font-size="10" font-weight="700" text-anchor="middle" fill="#fff">{num}</text>')


def badge(x, y, num):
    out.append(f'<circle cx="{x}" cy="{y}" r="11" fill="#263238"/>'
               f'<text x="{x}" y="{y + 4}" font-size="10" font-weight="700" text-anchor="middle" fill="#fff">{num}</text>')


# ── title ─────────────────────────────────────────────────────────────────────────────────────
out.append('<text x="20" y="32" font-size="20" font-weight="700" fill="#212121">ClaimSense AI × AutoSure Insurance — architecture AS BUILT (through M4 step 6, prompt m2-v13)</text>')
out.append('<text x="20" y="52" font-size="12" fill="#555">Every arrow is a labelled data flow (B1–B20, legend below). '
           'Blue = deterministic code · Orange = model judgment · Green = human · Grey = systems/data · Purple = operations. '
           'Solid border = deployed on AWS · dashed border = runs locally in containers. Synthetic data only.</text>')

# ── bands ─────────────────────────────────────────────────────────────────────────────────────
band(20, 70, 1255, 90, "human", "HUMAN — a licensed adjuster is accountable for every outcome (confirm is human-only)")
band(20, 270, 1255, 120, "code", "DETERMINISTIC CODE — identity · access · dates · money · risk indicators (never a model)", lx=380)
band(20, 420, 1255, 125, "model", "MODEL JUDGMENT — five typed agents; every judgment cites its evidence", lx=300)
band(20, 565, 1255, 110, "code", "DETERMINISTIC CODE — THE GOVERNED DOOR (MCP 2025-06-18 + REST), the only path to client systems", lx=250)
band(20, 695, 1255, 110, "store", "SYSTEMS OF RECORD (synthetic mocks)  ·  AWS DATA SERVICES", bottom=True)
band(1290, 70, 295, 735, "ops", "OPERATIONS & CHANGE CONTROL")

# ── boxes ─────────────────────────────────────────────────────────────────────────────────────
box(40, 95, 175, 50, "code", ["Amazon Cognito", "users + 5 groups → ID token"])
box(225, 95, 175, 50, "code", ["Keycloak (local)", "RFC 8693 exchange at the IdP"], dashed=True)
box(430, 95, 200, 50, "human", ["Adjuster (alice)", "reads only claims assigned to her"])
box(660, 95, 200, 50, "human", ["Senior adjuster (bob)", "all claims · audit reader"])
box(890, 95, 180, 50, "human", ["Specialists", "carol (fraud) · eve (total loss)"])
box(420, 190, 400, 50, "code", ["Adjuster Console — CloudFront → ALB → ECS Fargate", "Streamlit · own-password Cognito sign-in · queue · Ask"])

box(40, 300, 260, 75, "code", ["Orchestrator (same Fargate task)", "OpenAI Agents SDK · fixed order", "token exchange → 5-min delegated token"])
box(330, 300, 230, 75, "code", ["Deterministic checks", "term · net payable · repair÷ACV · $25K", "checklist · risk indicators (m2-v10)"])
box(590, 300, 330, 75, "code", ["Guardrails G1–G8 (code)", "injection scan + classifier · provenance quarantine", "citations ⊆ retrieved · PII mask · second opinion"])
box(950, 300, 290, 75, "code", ["Rule-engine fallback + holds", "labelled deterministic_fallback", "guardrail / disagreement → senior adjuster"])

box(40, 455, 185, 65, "model", ["① Document Intake", "gpt-4o (m2-v13)", "file · vehicle · damage · estimate"])
box(235, 455, 185, 65, "model", ["② Coverage Check", "gpt-4o + search_clauses", "cites retrieved clauses"])
box(430, 455, 185, 65, "model", ["③ Claim Assessment", "gpt-4o-mini", "indicators · TL · high value · injury"])
box(625, 455, 185, 65, "model", ["④ Decision Draft", "gpt-4o · strict output", "typed DecisionCard"])
box(820, 455, 170, 65, "model", ["Ask ClaimSense", "follow-up chat", "explains, never decides"])
box(1010, 455, 230, 65, "ext", ["OpenAI API", "external model subprocessor", "PII-masked inputs only"], dashed=True)

box(40, 592, 1200, 70, "code", ["THE DOOR — API Gateway (Cognito JWT authorizer; /mcp: door verifies the delegated token) → Lambda (container image) · same image runs locally",
    "auth before routing · grants.json deny-by-default · entitled() = group + assigned adjuster · REST 403 · idempotency · retry/breaker · audit EVERY call"])

box(40, 722, 170, 65, "store", ["Claims management", "claims · assignments", "prior_claims_24m"], dashed=True)
box(220, 722, 150, 65, "store", ["Policy admin", "terms · coverages"])
box(380, 722, 150, 65, "store", ["Document store", "untrusted text"])
box(540, 722, 150, 65, "store", ["Policy & Coverage KB", "OpenSearch (local)", "BM25 at the door"])
box(700, 722, 150, 65, "store", ["SIU ticketing", "4th system · flaky", "signed webhooks"], dashed=True)
box(860, 722, 110, 65, "store", ["Slack", "on-call page", "link, no data"], dashed=True)
box(980, 722, 120, 65, "store", ["Amazon S3", "policies/ · documents/", "door reads"])
box(1110, 722, 130, 65, "store", ["DynamoDB", "append-only audit"])

box(1300, 105, 275, 60, "ops", ["Secrets Manager", "OpenAI key → task role at runtime"])
box(1300, 300, 275, 60, "ops", ["Amazon ECR", "the gated image (immutable tags)"])
box(1300, 455, 275, 60, "ops", ["GitHub Actions", "live gate ≥ 90% · push THE tested build"])
box(1300, 600, 275, 60, "ops", ["CloudWatch", "dashboard · alarm (app + edge 5xx) → SNS"])
box(1300, 722, 275, 65, "ops", ["Budget alarm + tags", "Project=ClaimSense · cost guardrail"])

# ── flows ─────────────────────────────────────────────────────────────────────────────────────
flow([(127, 145), (127, 215), (420, 215)], "B1")
flow([(530, 145), (530, 190)], "B2")
flow([(460, 240), (460, 272), (280, 272), (280, 300)], "B2")
flow([(312, 145), (312, 260), (250, 260), (250, 300)], "B3", badge_at=0.5, dashed=True)
flow([(40, 345), (30, 345), (30, 592)], "B4")
flow([(300, 337), (330, 337)], None)
flow([(560, 337), (590, 337)], None)
flow([(165, 375), (165, 455)], "B6")
for x1, x2 in ((225, 235), (420, 430), (615, 625)):
    flow([(x1, 487), (x2, 487)], None)
flow([(990, 487), (1010, 487)], "B7")
flow([(327, 520), (327, 592)], "B8")
flow([(717, 455), (717, 375)], "B9")
flow([(920, 337), (950, 337)], None, dashed=True)
flow([(1095, 375), (1095, 405), (1000, 405), (1000, 592)], "B10", badge_at=0.6)
flow([(200, 300), (200, 252), (430, 252), (430, 240)], "B11", badge_at=0.45)
flow([(760, 145), (760, 190)], "B12")
flow([(820, 215), (1257, 215), (1257, 627), (1240, 627)], "B12", badge_at=0.5)
flow([(125, 662), (125, 722)], "B5")
flow([(295, 662), (295, 722)], "B5")
flow([(455, 662), (455, 722)], "B5")
flow([(615, 662), (615, 722)], "B8")
flow([(760, 662), (760, 722)], "B13")
flow([(820, 722), (820, 670)], "B14", dashed=True)
flow([(915, 662), (915, 722)], "B15")
flow([(1040, 722), (1040, 662)], "B16")
flow([(1175, 662), (1175, 722)], "B17")
flow([(1240, 645), (1300, 645)], "B18", badge_at=0.5)
flow([(1437, 455), (1437, 360)], "B19")
badge(1437, 180, "B20")

# ── legend ────────────────────────────────────────────────────────────────────────────────────
legend = [
    ("B1", "Adjuster signs in at Cognito (local: dev issuer); the ID token carries user + groups to the console."),
    ("B2", "Console sends claim_id + token to the orchestrator; the door re-checks the token on every call."),
    ("B3", "Locally, Keycloak performs the RFC 8693 exchange (D-041); on AWS the door's /oauth/token does it (D-039)."),
    ("B4", "Before any agent: the door checks the grant and entitlement. Refused → no agent runs, $0, audit row."),
    ("B5", "Door → systems of record: get_claim, list/get documents, get_policy (typed, granted, audited)."),
    ("B6", "Orchestrator → agents in a fixed order ①→②→③→④; inputs PII-masked, untrusted text wrapped as data."),
    ("B7", "Agents ↔ OpenAI API: masked prompts out, strict structured outputs back (pinned model snapshots)."),
    ("B8", "Coverage's search_clauses → the door → the KB; unprovenanced chunks are quarantined (G2) at the door."),
    ("B9", "DecisionCard → guardrails: code overwrites computed fields, checks citations, forces confirmation."),
    ("B10", "create_recommendation (Idempotency-Key) → a draft; escalations → SIU ticket / Slack via the door."),
    ("B11", "The card appears in the console: computed vs judgment, fraud indicators, verdict_source labelled."),
    ("B12", "Human-only confirm/override at the door; agent identities can never confirm (NEVER_DELEGATED)."),
    ("B13", "Door → SIU ticketing: create_escalation_ticket (idempotent, retried with backoff, breaker)."),
    ("B14", "Ticketing → door: HMAC-signed webhooks (5-min window, deduped by event_id, ordered by seq)."),
    ("B15", "notify_oncall: a Slack page with a link, never claim data (granted, idempotent, audited)."),
    ("B16", "On AWS the door reads the KB corpus, policies and documents from S3 (read-only role); manifest stays in the image (D-044)."),
    ("B17", "Every call, granted or refused, writes one append-only audit row (DynamoDB on AWS; /state locally)."),
    ("B18", "The same rows as AUDIT lines in CloudWatch Logs, plus the API Gateway access log for edge 401s (D-042)."),
    ("B19", "GitHub Actions: build once, live LLM gate ≥ 90% inside that image, then push THE tested build to ECR."),
    ("B20", "Secrets Manager / env: the OpenAI key reaches the orchestrator only; the door never holds a model key."),
]
out.append('<text x="20" y="840" font-size="14" font-weight="700" fill="#212121">Data flows (as built)</text>')
for i, (k, t) in enumerate(legend):
    col, row = divmod(i, 10)
    x, y = 20 + col * 790, 865 + row * 34
    out.append(f'<circle cx="{x + 11}" cy="{y - 4}" r="11" fill="#263238"/><text x="{x + 11}" y="{y}" font-size="10" font-weight="700" text-anchor="middle" fill="#fff">{k}</text>')
    words, line, lines = t.split(), "", []
    for wd in words:
        if len(line) + len(wd) > 105:
            lines.append(line); line = wd
        else:
            line = (line + " " + wd).strip()
    lines.append(line)
    for j, ln in enumerate(lines[:2]):
        out.append(f'<text x="{x + 30}" y="{y + j * 14}" font-size="11.5" fill="#263238">{escape(ln)}</text>')

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Helvetica, Arial, sans-serif">'
       '<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0,0 L9,4.5 L0,9 z" fill="#37474F"/></marker></defs>'
       f'<rect width="{W}" height="{H}" fill="#ffffff"/>' + "".join(out) + "</svg>")
Path(__file__).with_name("architecture-as-built.svg").write_text(svg)
print(f"wrote architecture-as-built.svg ({W}x{H})")
