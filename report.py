"""
report.py
---------
Reads log.json and posts.json and prints a weekly performance summary.
Optionally sends it by email if REPORT_EMAIL and SMTP vars are set.

Run manually:  python report.py
Runs via cron: every Sunday at 8:30 UTC (configured in GitHub Actions)
"""

import json
import os
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

REPORT_EMAIL  = os.getenv("REPORT_EMAIL")
SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com") or "smtp.gmail.com"
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587") or "587")
SMTP_USER     = os.getenv("SMTP_USER")       # your email address
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")   # email account password or app password


def load_json(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


def build_report() -> str:
    log   = load_json("log.json")
    queue = load_json("posts.json")

    # Limit to last 7 days
    cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
    recent = [e for e in log if e.get("executed_at", "") >= cutoff]

    published = [e for e in recent if e["status"] == "published"]
    failed    = [e for e in recent if e["status"] == "failed"]
    pending   = [p for p in queue if p["status"] == "pending"]

    lines = [
        "=" * 48,
        "  MEJOR ROCK EN ESPAÑOL — Weekly Report",
        f"  Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC",
        "=" * 48,
        "",
        f"Posts published this week : {len(published)}",
        f"Posts failed              : {len(failed)}",
        f"Posts still in queue      : {len(pending)}",
        "",
    ]

    if published:
        lines.append("Published posts:")
        for e in published:
            lines.append(
                f"  [{e.get('type','?'):16s}] "
                f"FB ID: {e.get('fb_post_id','?'):<20s} "
                f"at {e.get('executed_at','?')[:16]}"
            )
        lines.append("")

    if failed:
        lines.append("Failed posts (check tokens / API limits):")
        for e in failed:
            lines.append(
                f"  [{e.get('type','?'):16s}] "
                f"Error: {e.get('error','unknown')[:60]}"
            )
        lines.append("")

    if pending:
        lines.append("Upcoming scheduled posts:")
        for p in sorted(pending, key=lambda x: x["scheduled_at"])[:7]:
            lines.append(
                f"  [{p['type']:16s}] "
                f"scheduled {p['scheduled_at'][:16]} UTC"
            )
        lines.append("")

    lines += [
        "Action items:",
        "  - Check page insights at facebook.com/mejorrockespanol/insights",
        "  - If any failures, verify FB_PAGE_TOKEN hasn't expired (refresh every 60 days)",
        "  - Run generate.py manually if queue drops below 3 posts",
        "",
        "=" * 48,
    ]

    return "\n".join(lines)


def send_email(body: str):
    if not all([SMTP_USER, SMTP_PASSWORD, REPORT_EMAIL]):
        print("Email not configured — skipping send. Set SMTP_USER, SMTP_PASSWORD, REPORT_EMAIL.")
        return

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"Rock Bot Weekly Report — {datetime.utcnow().strftime('%b %d, %Y')}"
    msg["From"]    = SMTP_USER
    msg["To"]      = REPORT_EMAIL

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, REPORT_EMAIL, msg.as_string())
        print(f"Report emailed to {REPORT_EMAIL}")
    except Exception as e:
        print(f"Email send failed: {e}")


if __name__ == "__main__":
    report = build_report()
    print(report)
    send_email(report)
