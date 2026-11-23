"""Build the ≤10-minute demo video of the DEPLOYED system (Submission 2), from demo-script.md's storyline.

    python M4/presentation/make_demo.py tts        # narration per scene (OpenAI TTS, ≈ $0.05), durations measured
    python M4/presentation/make_demo.py record     # headed browser on the deployed console; YOU type the passcode
    python M4/presentation/make_demo.py stills     # title cards + real command output rendered as stills
    python M4/presentation/make_demo.py assemble   # one MP4 (H.264 + AAC) with soft captions, plus an .srt

Nothing is staged: console scenes are a screen recording of the deployed console answering live; the other scenes
are the deck's own slides and real output (the audit trail, CI's log, the CloudWatch dashboard, the rollback
listing), captured after the recording so they show the same calls. The demo passcode is typed by a person in the
browser window, never by this script, and the footage before sign-in is cut. Output: M4/presentation/out/ (not in git).
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "M4" / "presentation"
OUT = HERE / "out"
SCENES = json.loads((HERE / "narration.json").read_text())["scenes"]
CONF = Path.home() / ".claimsense"
PAD = 1.2                                       # seconds of picture after each narration line


def sh(*a, **k):
    return subprocess.run(a, check=True, capture_output=True, text=True, **k).stdout


def dur(path):
    return float(sh("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)).strip())


# ── 1 · narration ──────────────────────────────────────────────────────────────────────────────
def tts():
    from openai import OpenAI
    if "OPENAI_API_KEY" not in os.environ:                      # read from M2/.env, never printed
        for line in (ROOT / "M2" / ".env").read_text().splitlines():
            if line.startswith("OPENAI_API_KEY="):
                os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip()
    (OUT / "audio").mkdir(parents=True, exist_ok=True)
    client = OpenAI()
    meta = {}
    for s in SCENES:
        f = OUT / "audio" / f"{s['id']}.mp3"
        with client.audio.speech.with_streaming_response.create(
                model="gpt-4o-mini-tts", voice="alloy", input=s["text"], response_format="mp3",
                instructions="A calm, clear, confident presenter at a client steering committee. Measured pace, "
                             "natural pauses at full stops, no hype.") as r:
            r.stream_to_file(f)
        meta[s["id"]] = round(dur(f), 2)
        print(f"{s['id']:10} {meta[s['id']]:6.2f}s")
    (OUT / "audio" / "durations.json").write_text(json.dumps(meta, indent=1))
    print(f"total narration {sum(meta.values()):.0f}s")


def durations():
    return json.loads((OUT / "audio" / "durations.json").read_text())


# ── 2 · screen recording of the deployed console ───────────────────────────────────────────────
def record(only=None):
    from playwright.sync_api import sync_playwright
    url = json.loads((CONF / "frontend.json").read_text())["url"]
    need = {k: v + PAD for k, v in durations().items()}
    (OUT / "video").mkdir(parents=True, exist_ok=True)
    marks = {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=False)
        ctx = b.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=1,     # fits a laptop screen;
                            record_video_dir=str(OUT / "video"), record_video_size={"width": 1280, "height": 720})  # upscaled at assembly
        pg = ctx.new_page()
        t0 = time.monotonic()
        now = lambda: round(time.monotonic() - t0, 2)
        pg.goto(url)
        pg.get_by_label("Demo passcode", exact=True).wait_for(timeout=60_000)
        print("\n>>> In the browser window: paste the demo passcode into 'Demo passcode' and press Enter. <<<\n", flush=True)
        pg.get_by_text("role adjuster").first.wait_for(timeout=600_000)      # signed in as alice (blue box)
        pg.mouse.move(800, 300)
        time.sleep(1.5)

        def scene(sid, act):
            if only and sid not in only:
                return
            start = now()
            try:
                act()
            except Exception as e:                            # keep recording; this scene is redone, not the take
                print(f"{sid}: FAILED ({type(e).__name__}: {str(e).splitlines()[0][:120]})", flush=True)
            left = need[sid] - (now() - start)
            if left > 0:
                time.sleep(left)
            marks[sid] = (start, now())
            print(f"{sid:10} {start:7.2f} → {marks[sid][1]:7.2f}", flush=True)

        def pick(label, text):                     # Streamlit's combobox: type to filter, click the option, verify
            cb = pg.get_by_role("combobox", name=label)
            shown = lambda: pg.evaluate("document.body.innerText")   # the selected value is rendered text
            for _ in range(3):
                cb.click()
                cb.fill(text)
                opt = pg.get_by_role("option").filter(has_text=text).first
                opt.wait_for(timeout=10_000)
                time.sleep(0.5)
                opt.click()
                time.sleep(3)
                if text.split()[0] in shown():
                    return
                pg.keyboard.press("Escape")
            raise RuntimeError(f"could not select {text!r} in {label!r}")

        def run_and_wait(done_text, heading=False):
            pg.get_by_role("button", name="Run co-pilot").click()
            pg.get_by_text("Running Intake").first.wait_for(timeout=30_000)     # the old card is gone
            target = (pg.get_by_role("heading", name=re.compile("^" + done_text)) if heading
                      else pg.get_by_text(done_text, exact=False))
            target.first.wait_for(timeout=180_000)
            time.sleep(1.0)
            pg.mouse.move(800, 420)
            for _ in range(4):
                pg.mouse.wheel(0, 180)
                time.sleep(0.6)

        def to_top():
            pg.mouse.move(800, 300)
            pg.mouse.wheel(0, -4000)
            time.sleep(0.8)

        scene("signin", lambda: None)
        scene("approve", lambda: run_and_wait("APPROVE", heading=True))
        scene("agents", lambda: (pg.get_by_text("Agent outputs (typed)").first.click(), time.sleep(1.5),
                                 [(pg.mouse.wheel(0, 220), time.sleep(0.8)) for _ in range(4)]))
        def open_chat():
            box = pg.get_by_placeholder(re.compile("Ask about this claim"))
            if not box.is_visible():                        # the panel starts open once a conversation exists
                pg.get_by_text("Ask ClaimSense about this claim").first.click()
                time.sleep(1)
            box.scroll_into_view_if_needed()
            return box

        scene("askcs", lambda: (to_top(), open_chat().click(),
                                pg.keyboard.type("Why is the net payable $2,700, and what would change the outcome?", delay=30),
                                pg.keyboard.press("Enter"),
                                pg.get_by_text(re.compile(r"\$0\.\d{4} · ")).first.wait_for(timeout=120_000), time.sleep(1)))
        scene("confirm", lambda: (to_top(), [(pg.mouse.wheel(0, 350), time.sleep(0.3)) for _ in range(2)],
                                  pg.get_by_role("button", name="Confirm as drafted").click(), time.sleep(3),
                                  to_top(), pg.get_by_role("tab", name="Adjuster queue").click(), time.sleep(2)))
        scene("totalloss", lambda: (pg.get_by_role("tab", name="Co-pilot").click(), to_top(),
                                    pick("Claim", "CLM-2024-1946"), run_and_wait("ROUTE", heading=True)))
        scene("fraud", lambda: (to_top(), pick("Claim", "CLM-2024-1873"), run_and_wait("ROUTE", heading=True)))
        scene("injection", lambda: (to_top(), pick("Claim", "CLM-2024-3602"), run_and_wait("Guardrails fired")))
        scene("refused", lambda: (to_top(), pick("Sign in as (synthetic user, real Cognito sign-in)", "Carol"),
                                  pg.get_by_text("role fraud-investigator").first.wait_for(timeout=60_000),
                                  pick("Claim", "CLM-2024-1800"), run_and_wait("No claim data returned")))
        video = pg.video.path()
        ctx.close()
        b.close()
    name = "console.webm" if not only else f"console-{'-'.join(only)}.webm"
    Path(video).rename(OUT / "video" / name)
    old = json.loads((OUT / "video" / "marks.json").read_text()) if only and (OUT / "video" / "marks.json").exists() else {}
    for k, v in marks.items():                    # a re-take of some scenes replaces only those, from its own file
        old[k] = [*v, name]
    (OUT / "video" / "marks.json").write_text(json.dumps(old, indent=1))
    print("recorded", OUT / "video" / "console.webm")


# ── 3 · stills: the deck's slides and real command output ───────────────────────────────────────
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def slide_png(slide_id, deck_dir):
    css = (deck_dir / "project" / "deck.css").read_text()
    sec = (deck_dir / "project" / "slides" / f"{slide_id}.html").read_text()
    html = OUT / "stills" / f"{slide_id}.html"
    html.write_text('<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="https://fonts.googleapis.com/'
                    'css2?family=Space+Grotesk:wght@300..700&family=Inter:wght@400;600&display=swap"><style>*{margin:0;'
                    'animation:none!important} body>section{width:1920px;height:1080px;overflow:hidden;position:relative;'
                    'box-sizing:border-box} aside{display:none} x-shape{display:block}</style><style>' + css +
                    '</style></head><body>' + sec + '</body></html>')
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--screenshot={OUT / 'stills' / (slide_id + '.png')}",
                    "--window-size=1920,1080", f"file://{html}"], capture_output=True, check=True)


def terminal_png(name, title, lines):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1920, 1080), "#14213D")
    d = ImageDraw.Draw(img)
    mono = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 26)
    head = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 30)
    d.rectangle([0, 0, 1920, 64], fill="#0E1830")
    d.text((40, 16), title, font=head, fill="#E9A23B")
    y = 104
    for ln in lines[:30]:
        col = "#9BE7C4" if ("PASS" in ln or " allow" in ln or "OK" in ln) else "#F2B8A0" if (" deny" in ln or "FAIL" in ln) else "#E6EBF2"
        d.text((40, y), ln[:118], font=mono, fill=col)
        y += 32
    img.save(OUT / "stills" / f"{name}.png")


def stills(deck_dir):
    (OUT / "stills").mkdir(parents=True, exist_ok=True)
    for sid in ("cover", "outcomes", "scorecard", "safety", "how", "ask"):
        slide_png(sid, Path(deck_dir))
    ho = (ROOT / "M4/evidence/holdout-live.txt").read_text().splitlines()
    keep = [l for l in ho if re.match(r"^  (PASS|FAIL)  HO-|^SC-|^pass rate|^  (clear|edge|adversarial) ", l)]
    terminal_png("holdout", "Held-out set: 20 claims never tuned against · labels committed before the run (b488ebf)",
                 [l[:116] for l in keep][:30])
    hand = ["M4/handover/  (start here: README.md)", ""] + [
        f"  {f:22} {d}" for f, d in [("README.md", "a one-hour first day; secrets (where, never what); costs; limits"),
                                     ("artefact-index.md", "every engagement document, M0 to M4"),
                                     ("eval-contract.md", "both graders, commands, cadence, who may change labels"),
                                     ("escalation-map.md", "where each card goes; SEV-1..4 owners and targets"),
                                     ("watch-monthly.md", "10 signals: where, healthy, trigger, action"),
                                     ("rca-template.md", "one-page RCA template + incident archive")]] + [
        "", "M4/RUNBOOK.md  (each procedure executed on the live system first)", ""] + [
        f"  {n}" for n in ["1 Add or remove a user            ~4 min    tested on AWS",
                           "2 Roll back a deployment          15 s door · 2.5 min frontend",
                           "3 Escalate a flagged claim        SIU ticket, idempotent, queued if down",
                           "4 Update the policy corpus        gate 150/150, live 10/10, 0 quarantined",
                           "5 Door error rate alarm           drill: verified recovery in 279 s",
                           "6 Eval pass rate below SLO        continuous eval, full live gate"]]
    terminal_png("handover", "The handover pack: what AutoSure's team runs from", hand)
    # the audit trail for the calls just recorded (DynamoDB), alice and carol
    import boto3
    since = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(time.time() - 3 * 3600))
    t, rows, kw = boto3.client("dynamodb", region_name="us-east-1"), [], {"TableName": "claimsense-audit"}
    while True:
        r = t.scan(**kw)
        rows += r["Items"]
        if "LastEvaluatedKey" not in r:
            break
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    g = lambda r, k: r.get(k, {}).get("S", "")
    pick = [r for r in rows if g(r, "ts") >= since and g(r, "resource") == "CLM-2024-1800"
            and g(r, "action") in ("get_claim", "run_recommendation", "post_recommendation", "confirm_recommendation")]
    pick = sorted(pick, key=lambda r: g(r, "ts"))[-14:]
    terminal_png("audit", "Audit trail · DynamoDB claimsense-audit · claim CLM-2024-1800 (the calls just shown)",
                 ["time      via           user   action                  decision       reason"] +
                 [f"{g(r,'ts')[11:19]}  {g(r,'via'):12}  {g(r,'user_id'):6} {g(r,'action'):23} {g(r,'decision'):13}  {g(r,'reason')[:40]}" for r in pick])
    # CI: the latest main run's gate and second-grader summary, from GitHub's own log
    rid = sh("gh", "run", "list", "--repo", "cinnamon0590/FDE-ClaimSense-Capstone", "--branch", "main", "--limit", "1",
             "--json", "databaseId,headSha", "--jq", '.[0]|"\\(.databaseId) \\(.headSha[0:7])"', cwd=ROOT).split()
    log = sh("gh", "run", "view", rid[0], "--repo", "cinnamon0590/FDE-ClaimSense-Capstone", "--log", cwd=ROOT)
    keep = []
    for ln in log.splitlines():
        job, _, rest = ln.partition("\t")
        msg = re.sub(r"^.*?\d{4}-\d\d-\d\dT[\d:.]+Z ", "", ln.split("\t")[-1])
        if job == "live-eval" and re.search(r"golden suite|^  (clear|edge|adversarial) |pass rate|adversarial failures|engine check|DEPLOY GATE", msg):
            keep.append("live gate     " + msg.strip()[:100])
        if job == "second-grader" and re.search(r"✓ \d+ passed|\d+ failed", msg):
            keep.append("second grader " + msg.strip())
    jobs = sh("gh", "run", "view", rid[0], "--repo", "cinnamon0590/FDE-ClaimSense-Capstone", "--json", "jobs", "--jq",
              '.jobs[]|"\\(.conclusion) \\(.name)"', cwd=ROOT).splitlines()
    terminal_png("ci", f"GitHub Actions · eval-gate on main @ {rid[1]} · run {rid[0]}",
                 [f"{'PASS' if j.startswith('success') else j.split()[0].upper():8} {j.split(' ', 1)[1]}" for j in jobs] + [""] + keep[:14])
    subprocess.run([sys.executable, str(ROOT / "M4/ops/dashboard_snapshot.py"), "--hours", "3", "--name", "demo-dashboard.png"],
                   check=True, capture_output=True)
    from PIL import Image
    Image.open(ROOT / "M4/evidence/demo-dashboard.png").convert("RGB").resize((1920, 1080)).save(OUT / "stills" / "dashboard.png")
    (ROOT / "M4/evidence/demo-dashboard.png").unlink()
    listing = sh(sys.executable, str(ROOT / "M4/ops/rollback.py"), "list")
    drill = (ROOT / "M4/evidence/incident-drill-2.txt").read_text().splitlines()
    tl = [l for l in drill if re.match(r"^\d\d:\d\d:\d\d ", l) or l.startswith("time to")]
    terminal_png("drill", "Recover: python M4/ops/rollback.py list  ·  incident drill 2 timeline (UTC)",
                 ["$ python M4/ops/rollback.py list"] + listing.splitlines() + [""] + [re.sub(r"\d{12}", "<acct>", l)[:116] for l in tl])
    print("stills:", sorted(p.name for p in (OUT / "stills").glob("*.png")))


# ── 4 · assemble ────────────────────────────────────────────────────────────────────────────────
def assemble():
    d, marks = durations(), json.loads((OUT / "video" / "marks.json").read_text())
    parts, srt, t = [], [], 0.0
    clips = OUT / "clips"
    clips.mkdir(exist_ok=True)
    fmt = lambda s: f"{int(s // 3600):02d}:{int(s % 3600 // 60):02d}:{int(s % 60):02d},{int(s * 1000 % 1000):03d}"
    for i, s in enumerate(SCENES):
        a = OUT / "audio" / f"{s['id']}.mp3"
        out = clips / f"{i:02d}-{s['id']}.mp4"
        if s["kind"] == "console":
            st, en, *f = marks[s["id"]]
            length = en - st
            src = ["-ss", f"{st:.2f}", "-t", f"{length:.2f}", "-i", str(OUT / "video" / (f[0] if f else "console.webm"))]
        else:
            length = d[s["id"]] + PAD
            src = ["-loop", "1", "-t", f"{length:.2f}", "-i", str(OUT / "stills" / f"{s['id']}.png")]
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *src, "-i", str(a), "-filter_complex",
                        f"[0:v]scale=1920:1080:flags=lanczos,fps=30,format=yuv420p[v];[1:a]apad,atrim=0:{length:.2f}[a]",
                        "-map", "[v]", "-map", "[a]", "-t", f"{length:.2f}", "-c:v", "libx264", "-preset", "medium",
                        "-crf", "20", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(out)], check=True)
        parts.append(out)
        srt.append(f"{i + 1}\n{fmt(t + 0.2)} --> {fmt(t + d[s['id']] + 0.2)}\n{s['text']}\n")
        t += length
    (OUT / "list.txt").write_text("".join(f"file '{p}'\n" for p in parts))
    (OUT / "ClaimSense-demo.srt").write_text("\n".join(srt))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(OUT / "list.txt"),
                    "-i", str(OUT / "ClaimSense-demo.srt"), "-map", "0:v", "-map", "0:a", "-map", "1", "-c:v", "copy",
                    "-c:a", "copy", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng",
                    "-movflags", "+faststart", str(OUT / "ClaimSense-demo.mp4")], check=True)
    print(f"ClaimSense-demo.mp4 · {dur(OUT / 'ClaimSense-demo.mp4'):.0f}s · {(OUT / 'ClaimSense-demo.mp4').stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    cmd = (sys.argv[1:] or [""])[0]
    if cmd == "stills":
        stills(sys.argv[2] if len(sys.argv) > 2 else "")    # the deck folder (project/deck.css, project/slides/)
    else:
        if cmd == "record" and len(sys.argv) > 2:
            record(only=sys.argv[2].split(","))   # re-take named scenes only, e.g. `record fraud`
        else:
            {"tts": tts, "record": record, "assemble": assemble}[cmd]()
