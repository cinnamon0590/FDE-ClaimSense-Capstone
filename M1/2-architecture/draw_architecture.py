"""Draw the ClaimSense reference architecture as a layered SVG (stdlib only).

    python3 -I draw_architecture.py      # writes architecture.svg

Bands make the code/model boundary explicit: blue = deterministic code (identity, access, dates,
money), orange = model judgment (always cited), green = human (accountable for every outcome).
Every data flow is an arrow with a numbered badge, F1–F19, explained in the legend.
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
out.append('<text x="20" y="32" font-size="20" font-weight="700" fill="#212121">ClaimSense AI × AutoSure Insurance — reference architecture (M1)</text>')
out.append('<text x="20" y="52" font-size="12" fill="#555">Every arrow is a labelled data flow (F1–F19, legend below). '
           'Blue = deterministic code · Orange = model judgment · Green = human · Grey = systems/data · Purple = operations. Synthetic data only.</text>')

# ── bands ─────────────────────────────────────────────────────────────────────────────────────
band(20, 70, 1255, 90, "human", "HUMAN — a licensed adjuster is accountable for every outcome")
band(20, 270, 1255, 120, "code", "DETERMINISTIC CODE — identity · access · dates · money (never a model)", lx=470)
band(20, 420, 1255, 125, "model", "MODEL JUDGMENT — reads the file, judges, explains; every judgment cites its evidence", lx=175)
band(20, 565, 1255, 110, "code", "DETERMINISTIC CODE — the one governed door to client systems", lx=420)
band(20, 695, 1255, 110, "store", "SYSTEMS OF RECORD (synthetic, Docker mocks in the pilot)  ·  AWS DATA SERVICES", bottom=True)
band(1290, 70, 295, 735, "ops", "OPERATIONS & CHANGE CONTROL")

# ── boxes ─────────────────────────────────────────────────────────────────────────────────────
box(40, 95, 250, 50, "code", ["Amazon Cognito", "user pool + groups → JWT"])
box(430, 95, 200, 50, "human", ["Licensed adjuster", "alice · daily user"])
box(660, 95, 200, 50, "human", ["Senior adjuster", "bob · reviews co-pilot output"])
box(420, 190, 400, 50, "code", ["Adjuster Console", "Streamlit · ECS Fargate · shows computed vs judgment"])

box(40, 300, 260, 75, "code", ["Orchestrator API", "OpenAI Agents SDK runtime", "ECS Fargate · authorize first"])
box(330, 300, 230, 75, "code", ["Deterministic checks", "policy period · net payable", "repair÷ACV · $25K authority"])
box(590, 300, 330, 75, "code", ["Guardrails (code)", "injection scan · provenance quarantine", "citations ⊆ retrieved · PII mask · confirm=true"])
box(950, 300, 290, 75, "code", ["Rule-engine fallback", "labelled deterministic_fallback", "(never counted as a model verdict)"])

box(70, 455, 190, 65, "model", ["① Document Intake", "gpt-4o-mini", "file + missing docs"])
box(285, 455, 190, 65, "model", ["② Coverage Check", "gpt-4o + retrieval", "cites clauses"])
box(500, 455, 190, 65, "model", ["③ Claim Assessment", "gpt-4o-mini", "fraud · TL · injury"])
box(715, 455, 190, 65, "model", ["④ Decision Draft", "gpt-4o · strict output", "typed DecisionCard"])
box(1010, 455, 230, 65, "ext", ["OpenAI API", "external model subprocessor", "PII-masked inputs only"], dashed=True)

box(40, 592, 1200, 70, "code", ["DATA BOUNDARY — MCP server (API Gateway + Lambda)",
    "verify JWT · entitlement IN CODE before data · same error for missing/forbidden · Idempotency-Key on writes · audit EVERY call"])

box(40, 722, 210, 65, "store", ["Claims management", "claims · history · drafts"])
box(270, 722, 230, 65, "store", ["Policy administration", "terms · coverages · wording"])
box(520, 722, 210, 65, "store", ["Document store", "untrusted text + metadata"])
box(760, 722, 150, 65, "store", ["OpenSearch", "clause vectors"])
box(930, 722, 140, 65, "store", ["Amazon S3", "docs + corpus"])
box(1090, 722, 150, 65, "store", ["DynamoDB", "idempotency · audit"])

box(1300, 105, 275, 60, "ops", ["Secrets Manager", "OpenAI key → orchestrator at runtime"])
box(1300, 300, 275, 60, "ops", ["Amazon ECR", "container images (scan on push)"])
box(1300, 455, 275, 60, "ops", ["GitHub Actions", "eval gate: fail → no image push"])
box(1300, 600, 275, 60, "ops", ["CloudWatch", "traces · dashboard · alarm"])
box(1300, 722, 275, 65, "ops", ["Budget alarm + tags", "Project=ClaimSense · cost guardrail"])

# ── flows ─────────────────────────────────────────────────────────────────────────────────────
flow([(430, 120), (290, 120)], "F1")
flow([(165, 145), (165, 215), (420, 215)], "F1")
flow([(530, 145), (530, 190)], "F2")
flow([(460, 240), (460, 272), (280, 272), (280, 300)], "F2")
flow([(55, 375), (55, 592)], "F3")
flow([(560, 337), (590, 337)], None)                 # checks → guardrails (computed overwrite) — part of F12
flow([(300, 337), (330, 337)], "F7", badge_at=0.5)
flow([(165, 375), (165, 455)], "F8")
for x1, x2 in ((260, 285), (475, 500), (690, 715)):
    flow([(x1, 487), (x2, 487)], None)                # agent handoffs
flow([(905, 487), (1010, 487)], "F9")
flow([(380, 520), (380, 592)], "F10")
flow([(810, 455), (810, 375)], "F12")
flow([(920, 337), (950, 337)], None, dashed=True)     # blocked → fallback
flow([(900, 375), (900, 410), (957, 410), (957, 592)], "F13", badge_at=0.82)
flow([(200, 300), (200, 252), (430, 252), (430, 240)], "F14", badge_at=0.45)
flow([(760, 145), (760, 190)], "F15")
flow([(820, 215), (1257, 215), (1257, 627), (1240, 627)], "F15", badge_at=0.5)
flow([(145, 662), (145, 722)], "F4")
flow([(385, 662), (385, 722)], "F6")
flow([(625, 662), (625, 722)], "F5")
flow([(835, 662), (835, 722)], "F11")
flow([(930, 755), (910, 755)], None)
flow([(1165, 662), (1165, 722)], "F16")
flow([(1240, 755), (1270, 755), (1270, 630), (1300, 630)], "F16", badge_at=0.5)
flow([(1437, 455), (1437, 360)], "F18")
badge(1437, 180, "F19")
badge(1437, 290, "F18")
badge(1437, 590, "F17")

# ── legend ────────────────────────────────────────────────────────────────────────────────────
legend = [
    ("F1", "Adjuster signs in at Cognito (OIDC); the JWT carries user + groups to the console."),
    ("F2", "Adjuster opens a claim; console sends claim_id + JWT to the Orchestrator API (HTTPS)."),
    ("F3", "Orchestrator asks the boundary to AUTHORIZE the claim before any agent runs. Deny → refusal, no claim data, audit row."),
    ("F4", "Boundary → claims management: get_claim, get_claim_history (typed, scoped)."),
    ("F5", "Boundary → document store: list_documents, get_document. Text is UNTRUSTED and injection-scanned."),
    ("F6", "Boundary → policy administration: get_policy (feeds the deterministic date and money checks)."),
    ("F7", "Orchestrator → deterministic checks: loss inside policy term, net payable, repair÷ACV, $25K authority."),
    ("F8", "Orchestrator → agents: PII-masked file bundle, untrusted text wrapped as data; fixed handoffs ①→②→③→④."),
    ("F9", "Agents ↔ OpenAI API: prompts out, structured responses back (all four agents; masked inputs only)."),
    ("F10", "Coverage Check calls search_clauses through the boundary; it may cite only clause IDs returned."),
    ("F11", "Boundary → OpenSearch retrieval; chunks failing manifest provenance are quarantined. S3 corpus is indexed."),
    ("F12", "DecisionCard → guardrails: code overwrites computed fields, verifies citations ⊆ retrieved, forces confirmation."),
    ("F13", "post_recommendation with an Idempotency-Key → claims management (a draft, never final). Blocked cards → fallback, flagged."),
    ("F14", "Decision card shown in the console with computed vs judgment fields and verdict_source labelled."),
    ("F15", "Human-only confirm/override via the boundary (agent identities are refused; override needs a reason)."),
    ("F16", "Every boundary call writes an append-only audit record (DynamoDB), streamed to CloudWatch."),
    ("F17", "Orchestrator traces, latency (p95), error rate and call volume → CloudWatch dashboard + alarm."),
    ("F18", "GitHub Actions runs the eval gate; only a passing build pushes an image to ECR, which ECS deploys."),
    ("F19", "Secrets Manager hands the OpenAI key to the orchestrator at runtime (never in code, git or a prompt)."),
]
out.append('<text x="20" y="840" font-size="14" font-weight="700" fill="#212121">Data flows</text>')
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
Path(__file__).with_name("architecture.svg").write_text(svg)
print(f"wrote architecture.svg ({W}x{H})")
