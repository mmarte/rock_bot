"""
publish.py
----------
Reads posts.json, finds the next post that is due, and publishes it
to the Facebook Page via the Graph API.

  Morning posts  — original/poll/concert — get a topic-matched Pexels image
  Evening posts  — YouTube commentary   — text only (link already in text)

Run manually:  python publish.py
Runs via cron: 16:00 UTC (morning) and 00:00 UTC (evening) daily
"""

import json
import os
import random
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

PAGE_ID     = os.getenv("FB_PAGE_ID")
PAGE_TOKEN  = os.getenv("FB_PAGE_TOKEN")
PEXELS_KEY  = os.getenv("PEXELS_API_KEY")
POSTS_FILE  = "posts.json"
LOG_FILE    = "log.json"


# ---------------------------------------------------------------------------
# Pexels — topic-matched image
# ---------------------------------------------------------------------------

def get_pexels_image(query: str) -> str | None:
    """Fetch a relevant image from Pexels using a specific query."""
    if not PEXELS_KEY or not query:
        return None
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_KEY},
            params={"query": query, "per_page": 10, "orientation": "landscape"},
            timeout=10,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        if photos:
            return random.choice(photos)["src"]["large2x"]
    except Exception as e:
        print(f"  Pexels error: {e}")
    return None


# ---------------------------------------------------------------------------
# Facebook Graph API
# ---------------------------------------------------------------------------

def post_to_facebook(text: str, image_url: str | None) -> str:
    """
    Post text (with optional image) to the Facebook Page.
    Returns the Facebook post ID on success, raises on error.
    """
    if image_url:
        endpoint = f"https://graph.facebook.com/v19.0/{PAGE_ID}/photos"
        payload  = {
            "url":          image_url,
            "caption":      text,
            "access_token": PAGE_TOKEN,
        }
    else:
        endpoint = f"https://graph.facebook.com/v19.0/{PAGE_ID}/feed"
        payload  = {
            "message":      text,
            "access_token": PAGE_TOKEN,
        }

    r      = requests.post(endpoint, data=payload, timeout=15)
    result = r.json()

    if "error" in result:
        raise RuntimeError(
            f"Facebook API error {result['error'].get('code')}: "
            f"{result['error'].get('message')}"
        )

    return result.get("post_id") or result.get("id")


# ---------------------------------------------------------------------------
# Queue helpers
# ---------------------------------------------------------------------------

def load_queue() -> list:
    if os.path.exists(POSTS_FILE):
        with open(POSTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_queue(posts: list):
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def append_log(entry: dict):
    log = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, encoding="utf-8") as f:
            log = json.load(f)
    log.append(entry)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    now = datetime.now(timezone.utc)
    print(f"[{now.isoformat()}] Publisher starting...")

    posts = load_queue()
    if not posts:
        print("Queue is empty — run generate.py first.")
        return

    # Find all pending posts that are due
    due = [
        p for p in posts
        if p["status"] == "pending"
        and datetime.fromisoformat(p["scheduled_at"]) <= now
    ]

    if not due:
        pending = sorted(
            [p for p in posts if p["status"] == "pending"],
            key=lambda x: x["scheduled_at"],
        )
        if pending:
            nxt = pending[0]
            print(
                f"Nothing due yet. Next: [{nxt.get('slot','?')}] "
                f"[{nxt.get('type','?')}] at {nxt['scheduled_at'][:16]} UTC"
            )
        else:
            print("No pending posts — run generate.py to create next week's batch.")
        return

    # Publish the oldest due post
    post  = sorted(due, key=lambda x: x["scheduled_at"])[0]
    slot  = post.get("slot", "morning")
    ptype = post.get("type", "")
    topic = post.get("topic", "")

    print(f"  [{slot.upper()}] [{ptype}] topic='{topic}'")
    print(f"  Text: {post['text'][:80]}...")

    # Evening (YouTube) posts are text-only — the link is already in the text
    is_youtube = ptype == "video_youtube"

    if is_youtube:
        image_url = None
        print("  Evening YouTube post — no image (link in text).")
    else:
        # Morning posts: use topic-specific Pexels query for matched image
        image_query = post.get("image_query", topic)
        image_url   = get_pexels_image(image_query)
        if image_url:
            print(f"  Image: Pexels query '{image_query}'")
        else:
            print("  No Pexels image found — posting text only.")

    try:
        fb_post_id = post_to_facebook(post["text"], image_url)

        post["status"]       = "published"
        post["fb_post_id"]   = fb_post_id
        post["published_at"] = now.isoformat()
        post["error"]        = None

        append_log({
            "post_id":     post["id"],
            "fb_post_id":  fb_post_id,
            "slot":        slot,
            "type":        ptype,
            "topic":       topic,
            "image_used":  image_url is not None,
            "status":      "published",
            "executed_at": now.isoformat(),
        })
        print(f"  Published. FB post ID: {fb_post_id}")

    except Exception as e:
        post["status"] = "failed"
        post["error"]  = str(e)

        append_log({
            "post_id":     post["id"],
            "fb_post_id":  None,
            "slot":        slot,
            "type":        ptype,
            "topic":       topic,
            "status":      "failed",
            "error":       str(e),
            "executed_at": now.isoformat(),
        })
        print(f"  FAILED: {e}")

    save_queue(posts)

    pending   = sum(1 for p in posts if p["status"] == "pending")
    published = sum(1 for p in posts if p["status"] == "published")
    failed    = sum(1 for p in posts if p["status"] == "failed")
    print(f"  Queue: {pending} pending | {published} published | {failed} failed")


if __name__ == "__main__":
    run()
