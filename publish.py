"""
publish.py
----------
Reads posts.json, finds the next post that is due, fetches a Pexels image,
and publishes it to the Facebook Page via the Graph API.

Run manually:  python publish.py
Runs via cron: every day at 15:00 UTC (configured in GitHub Actions)
"""

import json
import os
import random
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PAGE_ID     = os.getenv("FB_PAGE_ID")
PAGE_TOKEN  = os.getenv("FB_PAGE_TOKEN")
PEXELS_KEY  = os.getenv("PEXELS_API_KEY")
POSTS_FILE  = "posts.json"
LOG_FILE    = "log.json"


# ---------------------------------------------------------------------------
# Pexels
# ---------------------------------------------------------------------------

def get_pexels_image(query: str) -> str | None:
    """Return a large image URL from Pexels for the given query, or None on failure."""
    if not PEXELS_KEY:
        print("  No PEXELS_API_KEY set — posting without image.")
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
    Publish a post (with or without image) to the Facebook Page.
    Returns the Facebook post ID string on success, raises on failure.
    """
    if image_url:
        # POST /page-id/photos uploads a photo with a caption
        endpoint = f"https://graph.facebook.com/v19.0/{PAGE_ID}/photos"
        payload  = {
            "url":          image_url,
            "caption":      text,
            "access_token": PAGE_TOKEN,
        }
    else:
        # POST /page-id/feed creates a plain text post
        endpoint = f"https://graph.facebook.com/v19.0/{PAGE_ID}/feed"
        payload  = {
            "message":      text,
            "access_token": PAGE_TOKEN,
        }

    r = requests.post(endpoint, data=payload, timeout=15)
    result = r.json()

    if "error" in result:
        raise RuntimeError(
            f"Facebook API error {result['error'].get('code')}: "
            f"{result['error'].get('message')}"
        )

    # /photos returns {"id": "..."}, /feed returns {"id": "page_post_id"}
    fb_id = result.get("post_id") or result.get("id")
    return fb_id


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
        print("Queue is empty. Run generate.py first.")
        return

    # Find all pending posts whose scheduled time has passed
    due = [
        p for p in posts
        if p["status"] == "pending"
        and datetime.fromisoformat(p["scheduled_at"]) <= now
    ]

    if not due:
        next_up = sorted(
            [p for p in posts if p["status"] == "pending"],
            key=lambda x: x["scheduled_at"],
        )
        if next_up:
            print(f"Nothing due yet. Next post scheduled for {next_up[0]['scheduled_at']} UTC.")
        else:
            print("No pending posts. Run generate.py to create next week's batch.")
        return

    # Publish the oldest due post
    post = sorted(due, key=lambda x: x["scheduled_at"])[0]
    print(f"  Posting [{post['type']}]: {post['text'][:70]}...")

    image_url = get_pexels_image(post["image_query"])
    if image_url:
        print(f"  Image fetched from Pexels for query: '{post['image_query']}'")
    else:
        print("  Posting without image.")

    try:
        fb_post_id = post_to_facebook(post["text"], image_url)

        post["status"]       = "published"
        post["fb_post_id"]   = fb_post_id
        post["published_at"] = now.isoformat()
        post["error"]        = None

        append_log({
            "post_id":    post["id"],
            "fb_post_id": fb_post_id,
            "type":       post["type"],
            "status":     "published",
            "image_used": image_url is not None,
            "executed_at": now.isoformat(),
        })
        print(f"  Published. Facebook post ID: {fb_post_id}")

    except Exception as e:
        post["status"] = "failed"
        post["error"]  = str(e)

        append_log({
            "post_id":    post["id"],
            "fb_post_id": None,
            "type":       post["type"],
            "status":     "failed",
            "error":      str(e),
            "executed_at": now.isoformat(),
        })
        print(f"  FAILED: {e}")

    save_queue(posts)

    # Summary
    pending   = sum(1 for p in posts if p["status"] == "pending")
    published = sum(1 for p in posts if p["status"] == "published")
    failed    = sum(1 for p in posts if p["status"] == "failed")
    print(f"  Queue status — pending: {pending} | published: {published} | failed: {failed}")


if __name__ == "__main__":
    run()
