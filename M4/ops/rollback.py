"""Roll back (or forward) a deployed component to an image that already passed the gate (runbook "Roll back a
deployment", M4). Images are tagged with the commit and tags are immutable, so this never rebuilds anything.

    python M4/ops/rollback.py list                       # images per component, newest first; * = live now
    python M4/ops/rollback.py door --to 220090f          # the door (Lambda), then the post-deploy smoke
    python M4/ops/rollback.py frontend --to 1bd5973      # console + orchestrator (ECS), then a health check

The door keeps its current configuration (environment) unless --previous-config is given, which restores the one
saved by the last `M3/cloud/deploy.sh` (~/.claimsense/door-previous.json). Exit 1 if the rolled-to release fails
its check; every step is timed so the runbook can quote real durations.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import boto3
import httpx

ROOT = Path(__file__).resolve().parents[2]
CONF = Path.home() / ".claimsense"
REGION = "us-east-1"
FN, CLUSTER, SERVICE = "claimsense-door", "claimsense", "claimsense-frontend"
aws = lambda s: boto3.client(s, region_name=REGION)


def tags(repo):
    imgs = aws("ecr").describe_images(repositoryName=repo, filter={"tagStatus": "TAGGED"})["imageDetails"]
    # an image can carry several tags (CI's full SHA and a deploy's short one): every tag is a valid target
    return [t for i in sorted(imgs, key=lambda i: i["imagePushedAt"], reverse=True)
            for t in sorted(i["imageTags"], key=len)]


def registry():
    return f"{aws('sts').get_caller_identity()['Account']}.dkr.ecr.{REGION}.amazonaws.com"


def live_door():
    return aws("lambda").get_function(FunctionName=FN)["Code"]["ImageUri"].rsplit(":", 1)[1]


def live_frontend():
    ecs = aws("ecs")
    td = ecs.describe_services(cluster=CLUSTER, services=[SERVICE])["services"][0]["taskDefinition"]
    defs = ecs.describe_task_definition(taskDefinition=td)["taskDefinition"]
    return td, defs, {c["name"]: c["image"].rsplit(":", 1)[1] for c in defs["containerDefinitions"]}


def door(to, previous_config=False):
    if to not in tags("claimsense/door"):
        sys.exit(f"no door image {to} in ECR")
    lam, t0 = aws("lambda"), time.time()
    print(f"door: {live_door()} -> {to}")
    lam.update_function_code(FunctionName=FN, ImageUri=f"{registry()}/claimsense/door:{to}")
    lam.get_waiter("function_updated_v2").wait(FunctionName=FN)
    if previous_config:
        env = json.loads((CONF / "door-previous.json").read_text())["env"]
        lam.update_function_configuration(FunctionName=FN, Environment=env)
        lam.get_waiter("function_updated_v2").wait(FunctionName=FN)
    print(f"door live on {to} after {time.time() - t0:.0f} s; smoke:")
    sys.stdout.flush()
    ok = subprocess.run([sys.executable, str(ROOT / "M4/ops/door_smoke.py")]).returncode == 0
    print(f"door rollback to {to}: {'OK' if ok else 'FAILED its smoke'} ({time.time() - t0:.0f} s)")
    return 0 if ok else 1


def frontend(to):
    for repo in ("claimsense/orchestrator", "claimsense/console"):
        if to not in tags(repo):
            sys.exit(f"no {repo} image {to} in ECR")
    ecs, t0 = aws("ecs"), time.time()
    _, d, live = live_frontend()
    print(f"frontend: {live} -> {to}")
    keep = ("family", "taskRoleArn", "executionRoleArn", "networkMode", "requiresCompatibilities", "cpu", "memory",
            "runtimePlatform")
    containers = [dict(c, image=f"{c['image'].rsplit(':', 1)[0]}:{to}") for c in d["containerDefinitions"]]
    new = ecs.register_task_definition(**{k: d[k] for k in keep if k in d}, containerDefinitions=containers,
                                       tags=[{"key": "Project", "value": "ClaimSense"}])["taskDefinition"]["taskDefinitionArn"]
    ecs.update_service(cluster=CLUSTER, service=SERVICE, taskDefinition=new)
    ecs.get_waiter("services_stable").wait(cluster=CLUSTER, services=[SERVICE], WaiterConfig={"Delay": 10, "MaxAttempts": 90})
    f = CONF / "frontend.json"
    meta = json.loads(f.read_text())
    url = meta["url"]
    health = httpx.get(f"{url}/_stcore/health", timeout=20).text.strip()
    meta.update(image_tag=to, task_definition=new.rsplit("/", 1)[1])
    f.write_text(json.dumps(meta, indent=1))
    ok = health == "ok" and live_frontend()[2] == {"orchestrator": to, "console": to}
    print(f"frontend rollback to {to}: {'OK' if ok else 'FAILED'} · console health '{health}' · {time.time() - t0:.0f} s")
    return 0 if ok else 1


def listing():
    cur_door, (_, _, cur_fe) = live_door(), live_frontend()
    for name, repo, cur in (("door", "claimsense/door", cur_door), ("orchestrator", "claimsense/orchestrator", cur_fe["orchestrator"]),
                            ("console", "claimsense/console", cur_fe["console"])):
        short = [t for t in tags(repo) if len(t) <= 8][:6]
        print(f"{name:13}" + "  ".join(("*" if t == cur else " ") + t for t in short))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["list", "door", "frontend"])
    ap.add_argument("--to")
    ap.add_argument("--previous-config", action="store_true")
    a = ap.parse_args()
    if a.what != "list" and not a.to:
        sys.exit("--to <tag> is required (see: rollback.py list)")
    sys.exit(listing() if a.what == "list" else door(a.to, a.previous_config) if a.what == "door" else frontend(a.to))
