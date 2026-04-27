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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

PAGE_ID         = os.getenv("FB_PAGE_ID")
PAGE_TOKEN      = os.getenv("FB_PAGE_TOKEN")
PEXELS_KEY      = os.getenv("PEXELS_API_KEY")
IG_USER_ID      = os.getenv("IG_USER_ID")
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")  # separate token from Instagram use case
THREADS_USER_ID = os.getenv("THREADS_USER_ID")
THREADS_TOKEN   = os.getenv("THREADS_TOKEN")
SMTP_USER       = os.getenv("SMTP_USER")
SMTP_PASSWORD   = os.getenv("SMTP_PASSWORD")
REPORT_EMAIL    = os.getenv("REPORT_EMAIL")
SMTP_HOST       = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT       = int(os.getenv("SMTP_PORT", "587"))
POSTS_FILE      = "posts.json"
LOG_FILE        = "log.json"


# ---------------------------------------------------------------------------
# Image fetching — multiple sources
# ---------------------------------------------------------------------------

# Curated official press/promo images per band
# These are direct links to freely available press photos and official images
OFFICIAL_BAND_IMAGES = {
    "Soda Stereo": [
        "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4e/Soda_Stereo_en_el_Me_Ver%C3%A1s_Volver.jpg/1200px-Soda_Stereo_en_el_Me_Ver%C3%A1s_Volver.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e3/Soda_Stereo_en_el_Gran_Rex.jpg/1200px-Soda_Stereo_en_el_Gran_Rex.jpg",
    ],
    "Heroes del Silencio": [
        "https://upload.wikimedia.org/wikipedia/commons/thumb/9/98/Heroes_del_Silencio.jpg/1200px-Heroes_del_Silencio.jpg",
    ],
    "Maná": [
        "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6e/Man%C3%A1_en_el_Palacio_de_los_Deportes.jpg/1200px-Man%C3%A1_en_el_Palacio_de_los_Deportes.jpg",
    ],
    "Café Tacvba": [
        "https://upload.wikimedia.org/wikipedia/commons/thumb/0/06/Cafe_Tacuba_en_el_Vive_Latino_2008.jpg/1200px-Cafe_Tacuba_en_el_Vive_Latino_2008.jpg",
    ],
    "Molotov": [
        "https://upload.wikimedia.org/wikipedia/commons/thumb/5/5e/Molotov_band.jpg/1200px-Molotov_band.jpg",
    ],
    "Los Prisioneros": [
        "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c0/Los_Prisioneros.jpg/1200px-Los_Prisioneros.jpg",
    ],
    "Caifanes": [
        "https://upload.wikimedia.org/wikipedia/commons/thumb/1/1e/Caifanes.jpg/1200px-Caifanes.jpg",
    ],
    "Gustavo Cerati": [
        "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9e/Gustavo_Cerati_2009.jpg/800px-Gustavo_Cerati_2009.jpg",
    ],
    "Divididos": [
        "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d3/Divididos_en_el_Luna_Park.jpg/1200px-Divididos_en_el_Luna_Park.jpg",
    ],
    "Los Fabulosos Cadillacs": [
        "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6b/Los_Fabulosos_Cadillacs.jpg/1200px-Los_Fabulosos_Cadillacs.jpg",
    ],
    "Bunbury": [
        "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b5/Bunbury_en_Madrid.jpg/800px-Bunbury_en_Madrid.jpg",
    ],
    "Fito Páez": [
        "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f3/Fito_Paez.jpg/800px-Fito_Paez.jpg",
    ],
    "Enanitos Verdes": [
        "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e3/Enanitos_Verdes.jpg/1200px-Enanitos_Verdes.jpg",
    ],
    "Aterciopelados": [
        "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a7/Aterciopelados.jpg/1200px-Aterciopelados.jpg",
    ],
}


def get_official_image(band_name):
    """
    Return a curated official image URL for a band if available.
    Verifies the URL is accessible before returning it.
    """
    urls = OFFICIAL_BAND_IMAGES.get(band_name, [])
    for url in urls:
        try:
            r = requests.head(url, timeout=8, allow_redirects=True)
            if r.status_code == 200:
                print("    Official image: " + url[:70] + "...")
                return url
        except Exception:
            continue
    return None


def scrape_official_website(band_name):
    """
    Try to find an image from the band's official website by
    scraping the Open Graph image tag (og:image).
    Most modern websites include this for social sharing.
    """
    # Map of band names to their official websites
    official_sites = {
        "Soda Stereo":              "https://www.sodastereo.com",
        "Maná":                     "https://www.mana.com.mx",
        "Café Tacvba":              "https://cafetacvba.com",
        "Heroes del Silencio":      "https://www.heroesdelsilencio.es",
        "Molotov":                  "https://molotov.com.mx",
        "Bunbury":                  "https://www.bunbury.es",
        "Jarabe de Palo":           "https://www.jarabedepalo.com",
        "Fito Páez":                "https://www.fitopaez.com",
        "La Ley":                   "https://www.laley.cl",
        "Babasónicos":              "https://babasónicos.com",
        "Enanitos Verdes":          "https://evanitosverdes.com",
        "Los Fabulosos Cadillacs":  "https://losfabulososcadillacs.com",
        "Rata Blanca":              "https://www.ratablanca.com.ar",
        "Divididos":                "https://www.divididos.com.ar",
        "Caifanes":                 "https://caifanes.com.mx",
        "Aterciopelados":           "https://aterciopelados.com",
        "Intocable":                "https://www.intocable.com",
    }

    url = official_sites.get(band_name)
    if not url:
        return None

    try:
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; RockBot/1.0)"},
            timeout=10,
        )
        if r.status_code != 200:
            return None

        html = r.text

        # Look for og:image meta tag
        import re
        match = re.search(
            r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)["\'][^>]*>',
            html, re.IGNORECASE
        )
        if not match:
            # Try reversed attribute order
            match = re.search(
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image["\'][^>]*>',
                html, re.IGNORECASE
            )

        if match:
            img_url = match.group(1).strip()
            if img_url.startswith("//"):
                img_url = "https:" + img_url
            elif img_url.startswith("/"):
                from urllib.parse import urlparse
                parsed = urlparse(url)
                img_url = parsed.scheme + "://" + parsed.netloc + img_url
            print("    Official site og:image: " + img_url[:70] + "...")
            return img_url

    except Exception as e:
        print("    Official site error (" + band_name + "): " + str(e))
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

    Priority order:
    1. YouTube video thumbnail  — for youtube post type only (always relevant)
    2. Curated official images  — hand-picked press photos per band
    3. Official band website    — og:image from band's own website
    4. Wikipedia                — freely licensed band photo
    5. Pexels                   — generic rock concert (last resort)
    """
    print("  Getting image for: " + band_name)

    # Layer 1 — For YouTube posts use the video's own thumbnail (always relevant)
    if post_type == "youtube" and youtube_url:
        try:
            video_id = youtube_url.split("v=")[-1].split("&")[0]
            thumb    = "https://img.youtube.com/vi/" + video_id + "/maxresdefault.jpg"
            check    = requests.head(thumb, timeout=5)
            if check.status_code == 200:
                print("    Video thumbnail (maxres): " + thumb[:60])
                return thumb
            thumb = "https://img.youtube.com/vi/" + video_id + "/hqdefault.jpg"
            print("    Video thumbnail (hq): " + thumb[:60])
            return thumb
        except Exception as e:
            print("    Video thumbnail error: " + str(e))

    # Layer 2 — Curated official images (best quality, verified)
    img = get_official_image(band_name)
    if img:
        return img

    # Layer 3 — Official band website og:image
    img = scrape_official_website(band_name)
    if img:
        return img

    # Layer 4 — Wikipedia (freely licensed band photos)
    img = get_wikipedia_image(band_name)
    if img:
        return img

    # Layer 5 — Pexels generic (last resort)
    img = get_pexels_fallback(band_name + " rock band")
    if img:
        return img

    print("  No image found for: " + band_name)
    return None


def get_poll_images(poll_options):
    """
    Fetch one image per poll option (band/artist).
    Uses the same priority order as get_best_image:
    curated → official site → Wikipedia → Pexels fallback.
    Returns list of image URLs — one per option.
    """
    images = []
    for option in poll_options:
        print("  Poll image for: " + option)
        img = (
            get_official_image(option)
            or scrape_official_website(option)
            or get_wikipedia_image(option)
            or get_pexels_fallback(option + " rock band")
        )
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
    # Use the Instagram-specific token, fall back to page token if not set
    ig_token = IG_ACCESS_TOKEN or PAGE_TOKEN
    try:
        container_r = requests.post(
            "https://graph.facebook.com/v19.0/" + IG_USER_ID + "/media",
            data={"image_url": image_url, "caption": text, "access_token": ig_token},
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
            data={"creation_id": container_id, "access_token": ig_token},
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
# Social media email notification
# ---------------------------------------------------------------------------

def send_social_email(post):
    """
    Send an email with instructions to manually post on X (Twitter) and TikTok.
    Includes the full post text, hashtags, and platform-specific tips.
    """
    if not all([SMTP_USER, SMTP_PASSWORD, REPORT_EMAIL]):
        print("  Email: not configured (set SMTP_USER, SMTP_PASSWORD, REPORT_EMAIL)")
        return

    ptype   = post.get("post_type", "original")
    topic   = post.get("topic", "")
    text    = post.get("text", "")
    vid_url = post.get("video_url", "")

    # Build X version (280 char limit — trim if needed)
    x_text = text
    # Remove hashtag block for X — X handles hashtags differently
    if "\n\n#" in x_text:
        x_text = x_text.split("\n\n#")[0].strip()
    # Add 2-3 key hashtags back
    x_text += "\n\n#RockEnEspañol #LoMejordelRockenEspañol"
    if vid_url:
        x_text += "\n" + vid_url
    # Trim to 280 chars if needed
    if len(x_text) > 280:
        x_text = x_text[:276] + "..."

    # TikTok caption (150 chars recommended, 2200 max)
    tiktok_text = text
    if "\n\n#" in tiktok_text:
        # Keep hashtags for TikTok — they drive discovery
        pass
    tiktok_caption = tiktok_text[:2200]

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    body = """
=================================================
Lo Mejor del Rock en Español — Post Notification
{now}
=================================================

Topic    : {topic}
Post type: {ptype}

-------------------------------------------------
FULL POST TEXT (Facebook/Instagram/Threads):
-------------------------------------------------
{text}

=================================================
X (TWITTER) — Copy and paste this:
=================================================
{x_text}

INSTRUCTIONS FOR X:
1. Go to x.com or open X app
2. Click the + or compose button
3. Paste the text above
4. If it's a YouTube post, the link will auto-preview
5. Post!

=================================================
TIKTOK — Steps to post:
=================================================
Caption to use:
{tiktok_caption}

INSTRUCTIONS FOR TIKTOK:
1. Open TikTok app
2. Tap the + button
3. Record a 15-60 sec video OR upload a clip
   - For YouTube posts: screen-record the YouTube video
   - For polls: use a trending audio + text overlay with the poll question
   - For original posts: use a relevant rock concert clip from your camera roll
4. Paste the caption above
5. Add relevant sounds/music
6. Post!

=================================================
Post ID: {post_id}
=================================================
""".format(
        now           = now_str,
        topic         = topic,
        ptype         = ptype,
        text          = text,
        x_text        = x_text,
        tiktok_caption = tiktok_caption[:500] + ("..." if len(tiktok_caption) > 500 else ""),
        post_id       = post.get("id", "?"),
    )

    try:
        msg = MIMEMultipart()
        msg["Subject"] = "Rock Bot Post: " + topic + " [" + ptype + "] — " + now_str
        msg["From"]    = SMTP_USER
        msg["To"]      = REPORT_EMAIL
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, REPORT_EMAIL, msg.as_string())

        print("  Email     : Sent to " + REPORT_EMAIL)
    except Exception as e:
        print("  Email     : Failed — " + str(e))


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

    # Send email with X/TikTok posting instructions
    send_social_email(post)


if __name__ == "__main__":
    run()
