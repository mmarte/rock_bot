"""
publish.py
----------
Publishes the latest PENDING post from posts.json.

Image strategy (in order of preference):
  1. YouTube thumbnail  — for YouTube posts, uses the video's own thumbnail
  2. Wikipedia image    — searches Wikimedia Commons for band photos (freely licensed)
  3. YouTube search     — searches YouTube for band name, uses video thumbnail
  4. Pexels fallback    — generic rock concert image as last resort

For polls: fetches one image per band option → posts as multi-photo Facebook post.
"""

import json
import os
import random
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

PAGE_ID         = os.getenv("FB_PAGE_ID")
PAGE_TOKEN      = os.getenv("FB_PAGE_TOKEN")
PEXELS_KEY      = os.getenv("PEXELS_API_KEY")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
IG_USER_ID      = os.getenv("IG_USER_ID")
THREADS_USER_ID = os.getenv("THREADS_USER_ID")
THREADS_TOKEN   = os.getenv("THREADS_TOKEN")
POSTS_FILE      = "posts.json"
LOG_FILE        = "log.json"


# ---------------------------------------------------------------------------
# Image fetching — multiple sources
# ---------------------------------------------------------------------------

def get_youtube_thumbnail(band_or_query):
    """
    Search YouTube for a band name and return the thumbnail of the top result.
    This gives real band/artist images since official videos use band photos.
    """
    if not YOUTUBE_API_KEY:
        return None
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "key":     YOUTUBE_API_KEY,
                "q":       band_or_query + " official video",
                "part":    "snippet",
                "type":    "video",
                "maxResults": 5,
            },
            timeout=10,
        )
        r.raise_for_status()
        items = r.json().get("items", [])
        if items:
            # Pick from top results, prefer high-res thumbnail
            item = items[0]
            thumbs = item["snippet"]["thumbnails"]
            # maxres > high > medium > default
            for quality in ["maxres", "high", "medium", "default"]:
                if quality in thumbs:
                    url = thumbs[quality]["url"]
                    print("    YouTube thumbnail: " + url[:60] + "...")
                    return url
    except Exception as e:
        print("    YouTube thumbnail error: " + str(e))
    return None


def get_wikipedia_image(band_name):
    """
    Fetch the main image for a band from Wikipedia.
    Wikipedia band pages almost always have a band photo.
    """
    try:
        # First get the page summary which includes the main image
        search_name = band_name.replace(" ", "_")
        r = requests.get(
            "https://en.wikipedia.org/api/rest_v1/page/summary/" + search_name,
            headers={"User-Agent": "MejorRockBot/1.0"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            img  = data.get("thumbnail", {}).get("source", "")
            if img:
                # Get full-size version by removing size constraint
                # Wikipedia thumbnails look like: .../320px-Band.jpg
                # Full size: .../Band.jpg
                full = img.split("/thumb/")
                if len(full) == 2:
                    parts = full[1].rsplit("/", 1)
                    full_url = "https://upload.wikimedia.org/wikipedia/commons/" + parts[0]
                    print("    Wikipedia image: " + full_url[:60] + "...")
                    return full_url
                print("    Wikipedia thumbnail: " + img[:60] + "...")
                return img

        # Try Spanish Wikipedia if English fails
        r2 = requests.get(
            "https://es.wikipedia.org/api/rest_v1/page/summary/" + search_name,
            headers={"User-Agent": "MejorRockBot/1.0"},
            timeout=10,
        )
        if r2.status_code == 200:
            data = r2.json()
            img  = data.get("thumbnail", {}).get("source", "")
            if img:
                print("    ES Wikipedia image: " + img[:60] + "...")
                return img

    except Exception as e:
        print("    Wikipedia error: " + str(e))
    return None


def get_pexels_fallback(query):
    """Last resort — Pexels with a rock concert query."""
    if not PEXELS_KEY:
        return None
    queries = [
        query,
        "rock concert band stage",
        "live music concert",
        "rock concert lights",
    ]
    for q in queries:
        try:
            r = requests.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": PEXELS_KEY},
                params={"query": q, "per_page": 10, "orientation": "landscape"},
                timeout=10,
            )
            r.raise_for_status()
            photos = r.json().get("photos", [])
            if photos:
                url = random.choice(photos)["src"]["large2x"]
                print("    Pexels fallback: " + q)
                return url
        except Exception as e:
            print("    Pexels error: " + str(e))
    return None


def get_best_image(band_name, post_type="original", youtube_url=None):
    """
    Get the best available image for a band/topic.
    Tries sources in order: YouTube thumbnail → Wikipedia → Pexels fallback.
    """
    print("  Getting image for: " + band_name)

    # For YouTube posts — use the video's own thumbnail
    if post_type == "youtube" and youtube_url:
        try:
            video_id = youtube_url.split("v=")[-1].split("&")[0]
            thumb    = "https://img.youtube.com/vi/" + video_id + "/maxresdefault.jpg"
            # Verify it exists (maxresdefault sometimes 404s)
            check = requests.head(thumb, timeout=5)
            if check.status_code == 200:
                print("    Video thumbnail: " + thumb[:60])
                return thumb
            # Fall back to hqdefault which always exists
            thumb = "https://img.youtube.com/vi/" + video_id + "/hqdefault.jpg"
            print("    Video thumbnail (hq): " + thumb[:60])
            return thumb
        except Exception as e:
            print("    Video thumbnail error: " + str(e))

    # Try Wikipedia first — best quality band photos
    img = get_wikipedia_image(band_name)
    if img:
        return img

    # Try YouTube search thumbnail — real band images from official videos
    img = get_youtube_thumbnail(band_name)
    if img:
        return img

    # Pexels as last resort
    img = get_pexels_fallback(band_name + " rock band")
    if img:
        return img

    print("  No image found for: " + band_name)
    return None


def get_poll_images(poll_options):
    """
    Fetch one image per poll option (band/artist).
    Returns list of image URLs — one per option, skipping None values.
    """
    images = []
    for option in poll_options:
        print("  Poll image for option: " + option)
        # Try Wikipedia first for real band photos
        img = get_wikipedia_image(option)
        if not img:
            img = get_youtube_thumbnail(option)
        if not img:
            img = get_pexels_fallback(option + " rock band")
        if img:
            images.append(img)
            print("    Got image for: " + option)
        else:
            print("    No image for: " + option)
    return images


def extract_poll_options(text):
    """
    Extract band/artist names from poll post text.
    Poll options follow 👍 ❤️ 😮 emojis.
    """
    options = []
    lines   = text.split("\n")
    for line in lines:
        if "👍" in line or "❤️" in line or "😮" in line:
            clean = line.replace("👍","").replace("❤️","").replace("😮","").strip()
            # Format is often "Option Name - Band Name" or just "Band Name"
            if " - " in clean:
                clean = clean.split(" - ")[-1].strip()
            if clean and len(clean) > 1:
                options.append(clean)
    return options[:3]


# ---------------------------------------------------------------------------
# Facebook Graph API
# ---------------------------------------------------------------------------

def upload_photo_unpublished(image_url):
    """
    Upload a photo to Facebook without publishing it.
    Used for building multi-photo posts (polls).
    Returns the media_fbid needed for multi-photo posts.
    """
    try:
        r = requests.post(
            "https://graph.facebook.com/v19.0/" + PAGE_ID + "/photos",
            data={
                "url":          image_url,
                "published":    "false",
                "access_token": PAGE_TOKEN,
            },
            timeout=30,
        )
        result = r.json()
        if "error" in result:
            print("    Upload error: " + result["error"].get("message", "?"))
            return None
        return result.get("id")
    except Exception as e:
        print("    Upload error: " + str(e))
        return None


def post_to_facebook_single(text, image_url):
    """Post with a single image."""
    if image_url:
        endpoint = "https://graph.facebook.com/v19.0/" + PAGE_ID + "/photos"
        payload  = {
            "url":          image_url,
            "caption":      text,
            "access_token": PAGE_TOKEN,
        }
    else:
        endpoint = "https://graph.facebook.com/v19.0/" + PAGE_ID + "/feed"
        payload  = {
            "message":      text,
            "access_token": PAGE_TOKEN,
        }
    r      = requests.post(endpoint, data=payload, timeout=15)
    result = r.json()
    if "error" in result:
        raise RuntimeError("FB error " + str(result["error"].get("code","?")) + ": " + result["error"].get("message","?"))
    return result.get("post_id") or result.get("id")


def post_to_facebook_multi(text, image_urls):
    """
    Post with multiple images (for polls — one image per band option).
    Uploads each image as unpublished, then creates a multi-photo post.
    Falls back to single image if multi-photo fails.
    """
    if not image_urls:
        return post_to_facebook_single(text, None)

    if len(image_urls) == 1:
        return post_to_facebook_single(text, image_urls[0])

    # Upload each image as unpublished
    print("  Uploading " + str(len(image_urls)) + " photos for multi-photo post...")
    media_ids = []
    for i, url in enumerate(image_urls):
        media_id = upload_photo_unpublished(url)
        if media_id:
            media_ids.append(media_id)
            print("    Photo " + str(i+1) + " uploaded: " + media_id)

    if not media_ids:
        print("  No photos uploaded — falling back to single image")
        return post_to_facebook_single(text, image_urls[0] if image_urls else None)

    # Build multi-photo post payload
    payload = {
        "message":      text,
        "access_token": PAGE_TOKEN,
    }
    for i, media_id in enumerate(media_ids):
        payload["attached_media[" + str(i) + "]"] = '{"media_fbid":"' + media_id + '"}'

    r      = requests.post("https://graph.facebook.com/v19.0/" + PAGE_ID + "/feed", data=payload, timeout=30)
    result = r.json()

    if "error" in result:
        print("  Multi-photo error: " + result["error"].get("message","?") + " — falling back to single")
        return post_to_facebook_single(text, image_urls[0])

    return result.get("id")


# ---------------------------------------------------------------------------
# Instagram
# ---------------------------------------------------------------------------

def post_to_instagram(text, image_url):
    if not IG_USER_ID or not image_url:
        return None
    try:
        container_r = requests.post(
            "https://graph.facebook.com/v19.0/" + IG_USER_ID + "/media",
            data={"image_url": image_url, "caption": text, "access_token": PAGE_TOKEN},
            timeout=15,
        )
        container = container_r.json()
        if "error" in container:
            print("  Instagram error: " + container["error"].get("message","?"))
            return None
        container_id = container.get("id")
        if not container_id:
            return None
        publish_r = requests.post(
            "https://graph.facebook.com/v19.0/" + IG_USER_ID + "/media_publish",
            data={"creation_id": container_id, "access_token": PAGE_TOKEN},
            timeout=15,
        )
        result = publish_r.json()
        if "error" in result:
            print("  Instagram publish error: " + result["error"].get("message","?"))
            return None
        return result.get("id")
    except Exception as e:
        print("  Instagram error: " + str(e))
        return None


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------

def post_to_threads(text, image_url):
    if not THREADS_USER_ID or not THREADS_TOKEN:
        return None
    try:
        params = {"text": text[:500], "access_token": THREADS_TOKEN}
        if image_url:
            params["media_type"] = "IMAGE"
            params["image_url"]  = image_url
        else:
            params["media_type"] = "TEXT"
        container_r = requests.post(
            "https://graph.threads.net/v1.0/" + THREADS_USER_ID + "/threads",
            data=params, timeout=15,
        )
        container = container_r.json()
        if "error" in container:
            print("  Threads error: " + container["error"].get("message","?"))
            return None
        container_id = container.get("id")
        if not container_id:
            return None
        publish_r = requests.post(
            "https://graph.threads.net/v1.0/" + THREADS_USER_ID + "/threads_publish",
            data={"creation_id": container_id, "access_token": THREADS_TOKEN},
            timeout=15,
        )
        result = publish_r.json()
        if "error" in result:
            print("  Threads publish error: " + result["error"].get("message","?"))
            return None
        return result.get("id")
    except Exception as e:
        print("  Threads error: " + str(e))
        return None


# ---------------------------------------------------------------------------
# Queue helpers
# ---------------------------------------------------------------------------

def load_queue():
    if os.path.exists(POSTS_FILE):
        with open(POSTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_queue(posts):
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def append_log(entry):
    log = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, encoding="utf-8") as f:
            log = json.load(f)
    log.append(entry)
    log = log[-200:]
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    now = datetime.now(timezone.utc)
    print("[" + now.isoformat() + "] Publisher starting...")

    posts = load_queue()
    if not posts:
        print("Queue is empty — run generate.py first.")
        return

    pending = [p for p in posts if p["status"] == "pending"]
    if not pending:
        print("No pending posts — run generate.py first.")
        return

    post  = pending[-1]
    ptype = post.get("post_type", "original")
    topic = post.get("topic", "")

    print("  Post type : " + ptype)
    print("  Topic     : " + topic)
    print("  Text      : " + post["text"][:80] + "...")

    # ── Get images based on post type ────────────────────────────────────

    fb_post_id      = None
    ig_post_id      = None
    threads_post_id = None
    image_url       = None   # single image used for IG/Threads

    if ptype == "poll":
        # Multi-photo post: one image per poll option
        options = extract_poll_options(post["text"])
        print("  Poll options found: " + str(options))

        if options:
            poll_images = get_poll_images(options)
            print("  Got " + str(len(poll_images)) + " poll images")
            fb_post_id = post_to_facebook_multi(post["text"], poll_images)
            image_url  = poll_images[0] if poll_images else None
        else:
            # Fallback: single image of the topic band
            image_url  = get_best_image(topic, ptype)
            fb_post_id = post_to_facebook_single(post["text"], image_url)

    else:
        # Single image post
        youtube_url = post.get("video_url")
        image_url   = get_best_image(topic, ptype, youtube_url)

        try:
            fb_post_id = post_to_facebook_single(post["text"], image_url)
        except RuntimeError as e:
            post["status"] = "failed"
            post["error"]  = str(e)
            save_queue(posts)
            append_log({"post_id": post["id"], "status": "failed", "error": str(e), "executed_at": now.isoformat()})
            print("  Facebook FAILED: " + str(e))
            return

    if fb_post_id:
        print("  Facebook  : Published! ID=" + str(fb_post_id))
    else:
        print("  Facebook  : FAILED — no post ID returned")

    # ── Instagram ─────────────────────────────────────────────────────────
    if IG_USER_ID:
        ig_post_id = post_to_instagram(post["text"], image_url)
        print("  Instagram : " + ("Published! ID=" + str(ig_post_id) if ig_post_id else "Failed/skipped"))
    else:
        print("  Instagram : Not configured")

    # ── Threads ───────────────────────────────────────────────────────────
    if THREADS_USER_ID and THREADS_TOKEN:
        threads_post_id = post_to_threads(post["text"], image_url)
        print("  Threads   : " + ("Published! ID=" + str(threads_post_id) if threads_post_id else "Failed/skipped"))
    else:
        print("  Threads   : Not configured")

    # ── Mark published ────────────────────────────────────────────────────
    post["status"]          = "published"
    post["fb_post_id"]      = fb_post_id
    post["ig_post_id"]      = ig_post_id
    post["threads_post_id"] = threads_post_id
    post["published_at"]    = now.isoformat()
    post["error"]           = None

    save_queue(posts)
    append_log({
        "post_id":         post["id"],
        "fb_post_id":      fb_post_id,
        "ig_post_id":      ig_post_id,
        "threads_post_id": threads_post_id,
        "post_type":       ptype,
        "topic":           topic,
        "image_url":       image_url,
        "status":          "published",
        "executed_at":     now.isoformat(),
    })

    pending_count   = sum(1 for p in posts if p["status"] == "pending")
    published_count = sum(1 for p in posts if p["status"] == "published")
    print("  Queue     : " + str(pending_count) + " pending | " + str(published_count) + " published")


if __name__ == "__main__":
    run()
