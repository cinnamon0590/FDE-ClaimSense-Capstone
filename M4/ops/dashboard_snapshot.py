"""Render the live CloudWatch dashboard to images (evidence, no browser): one PNG per metric widget via
GetMetricWidgetImage, then a single composite `M4/evidence/dashboard.png` (and an alarm-state line).

    python M4/ops/dashboard_snapshot.py [--hours 3]
"""
import argparse
import io
import json
import os
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "M4" / "evidence"
REGION = os.environ.get("AWS_REGION", "us-east-1")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=3)
    a = ap.parse_args(argv)
    cw = boto3.client("cloudwatch", region_name=REGION)
    body = json.loads(cw.get_dashboard(DashboardName="ClaimSense-Operations")["DashboardBody"])
    tiles = []
    for w in body["widgets"]:
        if w["type"] != "metric":
            continue
        props = dict(w["properties"], width=600, height=300, start=f"-PT{a.hours}H", end="P0D")
        props.pop("region", None)
        png = cw.get_metric_widget_image(MetricWidget=json.dumps(props))["MetricWidgetImage"]
        tiles.append(png)
    from PIL import Image, ImageDraw
    imgs = [Image.open(io.BytesIO(p)).convert("RGB") for p in tiles]
    cols, tw, th = 3, 600, 300
    rows = (len(imgs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, 60 + rows * th), "white")
    d = ImageDraw.Draw(sheet)
    alarm = cw.describe_alarms(AlarmNames=["ClaimSense-door-error-rate"])["MetricAlarms"][0]
    d.text((12, 10), f"ClaimSense-Operations (CloudWatch) · last {a.hours} h · region {REGION}", fill="black")
    d.text((12, 32), f"Alarm ClaimSense-door-error-rate: {alarm['StateValue']} · threshold door 5xx > 5% (2 of 3 min)",
           fill="black")
    for i, im in enumerate(imgs):
        sheet.paste(im.resize((tw, th)), ((i % cols) * tw, 60 + (i // cols) * th))
    OUT.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT / "dashboard.png")
    print(f"wrote {OUT / 'dashboard.png'} ({len(imgs)} widgets) · alarm state {alarm['StateValue']}")


if __name__ == "__main__":
    main()
