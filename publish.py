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
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def sanitize_token(token):
    if not token or not isinstance(token, str):
        return None
    token = token.strip()
    if (token.startswith('"') and token.endswith('"')) or (token.startswith("'") and token.endswith("'")):
        token = token[1:-1].strip()
    return token

FOLLOW_LINKS = {
    "facebook":  "https://www.facebook.com/mejorrockespanol",
    "instagram": "https://www.instagram.com/mejorrockespanol",
    "threads":   "https://www.threads.net/@mejorrockespanol",
}

def adjust_follow_cta_for_platform(text, platform):
    if not text or platform not in FOLLOW_LINKS:
        return text
    follow_link = FOLLOW_LINKS[platform]
    if "@mejorrockespanol" in text:
        return text.replace("@mejorrockespanol", follow_link)
    if "https://www.instagram.com/mejorrockespanol" in text:
        return text.replace("https://www.instagram.com/mejorrockespanol", follow_link)
    return text

PAGE_ID         = sanitize_token(os.getenv("FB_PAGE_ID"))
PAGE_TOKEN      = sanitize_token(os.getenv("FB_PAGE_TOKEN"))
PEXELS_KEY      = sanitize_token(os.getenv("PEXELS_API_KEY"))
IG_USER_ID      = sanitize_token(os.getenv("IG_USER_ID"))
IG_ACCESS_TOKEN = sanitize_token(os.getenv("IG_ACCESS_TOKEN"))  # separate token from Instagram use case
THREADS_USER_ID = sanitize_token(os.getenv("THREADS_USER_ID"))
THREADS_TOKEN   = sanitize_token(os.getenv("THREADS_TOKEN"))
SMTP_USER       = sanitize_token(os.getenv("SMTP_USER"))
SMTP_PASSWORD   = sanitize_token(os.getenv("SMTP_PASSWORD"))
REPORT_EMAIL    = sanitize_token(os.getenv("REPORT_EMAIL"))
SMTP_HOST       = sanitize_token(os.getenv("SMTP_HOST", "smtp.gmail.com")) or "smtp.gmail.com"
SMTP_PORT       = int(sanitize_token(os.getenv("SMTP_PORT", "587")) or "587")
GRAPH_VERSION   = sanitize_token(os.getenv("META_GRAPH_VERSION", "v25.0"))
GRAPH_BASE      = f"https://graph.facebook.com/{GRAPH_VERSION}"
POSTS_FILE      = "posts.json"
LOG_FILE        = "log.json"

try:
    from band_universe import get_band_universe
except Exception:
    get_band_universe = None


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


def get_wikipedia_image(band_name, year=""):
    """
    Fetch the main image for a band from Wikipedia.
    If year is provided, searches for the era-specific page first
    (e.g. "Soda Stereo 1987" might find an 80s-era photo).
    """
    try:
        # Try era-specific search first if year provided
        search_names = []
        if year:
            search_names.append(band_name.replace(" ", "_") + "_" + year)
        search_names.append(band_name.replace(" ", "_"))

        for search_name in search_names:
            r = requests.get(
                "https://en.wikipedia.org/api/rest_v1/page/summary/" + search_name,
                headers={"User-Agent": "MejorRockBot/1.0"},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                img  = data.get("thumbnail", {}).get("source", "")
                if img:
                    full = img.split("/thumb/")
                    if len(full) == 2:
                        parts   = full[1].rsplit("/", 1)
                        full_url = "https://upload.wikimedia.org/wikipedia/commons/" + parts[0]
                        print("    Wikipedia image: " + full_url[:60] + "...")
                        return full_url
                    print("    Wikipedia thumbnail: " + img[:60] + "...")
                    return img

        # Try Spanish Wikipedia
        r2 = requests.get(
            "https://es.wikipedia.org/api/rest_v1/page/summary/" + band_name.replace(" ", "_"),
            headers={"User-Agent": "MejorRockBot/1.0"},
            timeout=10,
        )
        if r2.status_code == 200:
            data = r2.json()
            img  = data.get("thumbnail", {}).get("source", "")
            if img:
                print("    ES Wikipedia image: " + img[:60] + "...")
                return img

        # Original single search kept for compatibility
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


def get_wikidata_image(band_name: str) -> str | None:
    """
    Best-effort: use the cached Wikidata universe (P18) when available.
    This tends to be a more accurate "real artist photo" than generic search.
    """
    if not get_band_universe:
        return None
    try:
        infos = get_band_universe(refresh=False)
        if not infos:
            return None
        # Case-insensitive match
        name_l = band_name.lower().strip()
        for i in infos:
            if i.name.lower() == name_l:
                return i.image or None
    except Exception:
        return None
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


def get_best_image(band_name, post_type="original", youtube_url=None, year=""):
    """
    Get the best available image for a band/topic.

    Priority order:
    1. YouTube video thumbnail  — for youtube post type only
    2. Curated official images  — hand-picked press photos per band
    3. Official band website    — og:image from band's own website
    4. Wikipedia (era-aware)    — passes year hint for historical photos
    5. Pexels                   — generic rock concert (last resort)

    year: if provided (e.g. "1987"), tries to find era-specific photos.
    """
    print("  Getting image for: " + band_name + (" (" + year + ")" if year else ""))

    # Layer 1 — YouTube video thumbnail (relevant for any post with a YouTube video link)
    if youtube_url and ("youtube.com" in youtube_url or "youtu.be" in youtube_url):
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

    # Layer 3 — Wikidata P18 image (often high-quality + correct subject)
    img = get_wikidata_image(band_name)
    if img:
        print("    Wikidata image: " + img[:60] + "...")
        return img

    # Layer 4 — Official band website og:image
    img = scrape_official_website(band_name)
    if img:
        return img

    # Layer 5 — Wikipedia with era hint (freely licensed photos)
    img = get_wikipedia_image(band_name, year=year)
    if img:
        return img

    # Layer 6 — Pexels with a concert-specific search for concert posts,
    # otherwise use a general rock band search.
    if post_type == "concert":
        query = band_name + (" " + year if year else "") + " concert live photo"
    else:
        query = band_name + (" " + year if year else "") + " rock band"
    img   = get_pexels_fallback(query)
    if img:
        return img

    print("  No image found for: " + band_name)
    return None


def get_poll_images(poll_options, topic=""):
    """
    Fetch one image per poll option.
    Smartly maps option text to the best image source:
    - Known band names → official image / Wikipedia
    - Descriptive options → mapped image query → Pexels
    - Unknown options → fallback to topic band
    """
    images = []
    for option in poll_options:
        print("  Poll image for: " + option)
        query = get_option_image_query(option, fallback_band=topic)
        print("    Image query: " + query)

        # If query matches a known band, use full image stack
        is_band = any(band.lower() in query.lower() for band in KNOWN_BANDS)

        if is_band:
            img = (
                get_official_image(query)
                or scrape_official_website(query)
                or get_wikipedia_image(query)
                or get_pexels_fallback(query + " rock band concert")
            )
        else:
            # Descriptive option — just use Pexels with the mapped query
            img = get_pexels_fallback(query)

        if img:
            images.append(img)
            print("    Got image for: " + option)
        else:
            print("    No image for: " + option)
    return images


# Known bands for poll image matching — options that match these get real images
KNOWN_BANDS = [
    "Soda Stereo", "Heroes del Silencio", "Maná", "Café Tacvba",
    "Molotov", "Los Prisioneros", "Caifanes", "La Ley",
    "Los Fabulosos Cadillacs", "Divididos", "Bunbury", "Fito Páez",
    "Rata Blanca", "Intocable", "Jarabe de Palo", "Gustavo Cerati",
    "Enrique Bunbury", "Babasónicos", "Aterciopelados", "Enanitos Verdes",
    "Hombres G", "El Tri", "Maldita Vecindad", "Los Rodríguez",
    "Bersuit Vergarabat", "Panteon Rococo", "Santa Sabina",
]

if get_band_universe:
    try:
        # Expand known bands so poll image matching can use Wikidata/Wikipedia more often.
        # We cap this to keep runtime reasonable.
        _u = get_band_universe(refresh=False)
        if _u:
            KNOWN_BANDS = list(dict.fromkeys(KNOWN_BANDS + [i.name for i in _u[:600]]))
    except Exception:
        pass

# Descriptive poll options → better image search queries
OPTION_IMAGE_MAP = {
    "rock argentino": "rock band argentina concert",
    "rock mexicano":  "rock band mexico concert",
    "rock español":   "rock band spain concert",
    "los 80s":        "rock concert 1980s stage",
    "los 90s":        "rock concert 1990s stage",
    "los 2000s":      "rock concert 2000s stage",
    "letras":         "rock singer microphone concert",
    "sonido":         "electric guitar concert stage",
    "en vivo":        "rock concert live crowd",
    "vive latino":    "music festival mexico crowd",
    "lollapalooza":   "lollapalooza festival crowd",
    "estéreo picnic": "music festival colombia crowd",
    "los dos":        "rock concert latin america",
    "iguales":        "rock concert latin america",
}


def get_option_image_query(option_text, fallback_band=""):
    """
    Convert a poll option text into the best image search query.
    If it matches a known band — use the band name directly.
    If it's a descriptive option — map to a relevant image query.
    Otherwise — use the topic band as fallback.
    """
    option_lower = option_text.lower()

    # Check if it's a known band name
    for band in KNOWN_BANDS:
        if band.lower() in option_lower or option_lower in band.lower():
            return band   # return the actual band name for Wikipedia/official lookup

    # Check descriptive option map
    for key, query in OPTION_IMAGE_MAP.items():
        if key in option_lower:
            return query

    # If it contains " - " it's probably "Song - Band" format
    if " - " in option_text:
        band_part = option_text.split(" - ")[-1].strip()
        for band in KNOWN_BANDS:
            if band.lower() in band_part.lower():
                return band

    # Fall back to the post topic band
    return fallback_band if fallback_band else option_text


def extract_poll_options(text):
    """
    Extract poll options from text (lines with 👍 ❤️ 😮 emojis).
    Returns list of raw option strings.
    """
    options = []
    lines   = text.split("\n")
    for line in lines:
        if "👍" in line or "❤️" in line or "😮" in line:
            clean = line.replace("👍","").replace("❤️","").replace("😮","").strip()
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
            GRAPH_BASE + "/" + PAGE_ID + "/photos",
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
        endpoint = GRAPH_BASE + "/" + PAGE_ID + "/photos"
        payload  = {
            "url":          image_url,
            "caption":      text,
            "access_token": PAGE_TOKEN,
        }
    else:
        endpoint = GRAPH_BASE + "/" + PAGE_ID + "/feed"
        payload  = {
            "message":      text,
            "access_token": PAGE_TOKEN,
        }
    r      = requests.post(endpoint, data=payload, timeout=15)
    result = r.json()
    if "error" in result:
        raise RuntimeError("FB error " + str(result["error"].get("code","?")) + ": " + result["error"].get("message","?"))
    return result.get("post_id") or result.get("id")


def post_to_facebook_link(text, link_url, image_url=None):
    """Post a link preview to Facebook for YouTube-style posts."""
    endpoint = GRAPH_BASE + "/" + PAGE_ID + "/feed"
    payload = {
        "message":      text + "\n\n" + link_url,
        "link":         link_url,
        "access_token": PAGE_TOKEN,
    }
    if image_url:
        payload["picture"] = image_url
    r      = requests.post(endpoint, data=payload, timeout=15)
    result = r.json()
    if "error" in result:
        raise RuntimeError("FB link error " + str(result["error"].get("code","?")) + ": " + result["error"].get("message","?"))
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

    r      = requests.post(GRAPH_BASE + "/" + PAGE_ID + "/feed", data=payload, timeout=30)
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
            GRAPH_BASE + "/" + IG_USER_ID + "/media",
            data={"image_url": image_url, "caption": text, "access_token": ig_token},
            timeout=15,
        )
        container = container_r.json()
        if "error" in container:
            msg = container["error"].get("message", "?")
            code = str(container["error"].get("code", ""))
            print("  Instagram error: " + msg)
            if code == "10":
                print("  Hint: IG publishing requires permissions like instagram_content_publish + a valid IG User ID tied to your Page.")
            return None
        container_id = container.get("id")
        if not container_id:
            return None
        publish_r = requests.post(
            GRAPH_BASE + "/" + IG_USER_ID + "/media_publish",
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
        # Fast sanity check: Threads tokens should be non-empty strings; common misconfig is a JSON blob or quoted object.
        if not isinstance(THREADS_TOKEN, str) or len(THREADS_TOKEN.strip()) < 20:
            print("  Threads error: THREADS_TOKEN looks invalid/empty.")
            return None
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
            msg = container["error"].get("message", "?")
            print("  Threads error: " + msg)
            if "Cannot parse access token" in msg:
                print("  Hint: THREADS_TOKEN is not a valid access token (double-check the secret value, no quotes/newlines).")
            return None
        container_id = container.get("id") or container.get("creation_id")
        if not container_id:
            print("  Threads error: no thread ID returned")
            return None
        # Some Threads endpoints return the published object immediately.
        return container_id
    except Exception as e:
        print("  Threads error: " + str(e))
        return None


def _latest_reel_path():
    reels_dir = Path("reels")
    if not reels_dir.exists() or not reels_dir.is_dir():
        return None
    candidates = sorted(reels_dir.glob("reel_*.mp4"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def upload_youtube_short_from_latest_reel(topic, caption):
    reel_path = _latest_reel_path()
    if not reel_path:
        print("  YouTube automation skipped: no local reel file found in reels/")
        return None
    try:
        from make_reel import upload_youtube_short, _youtube_env_configured
    except Exception as e:
        print("  YouTube automation unavailable: " + str(e))
        return None
    if not _youtube_env_configured():
        print("  YouTube automation not configured (missing YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN)")
        return None
    print("  YouTube automation: uploading latest reel " + str(reel_path.name))
    result = upload_youtube_short(reel_path, {"topic": topic}, caption)
    if not result:
        print("  YouTube automation failed or was skipped.")
    return result


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

    youtube_note = ""
    if ptype == "youtube":
        youtube_note = (
            "NOTE: publish.py does not upload the video to YouTube. "
            "Use make_reel.py or manual upload for actual YouTube publishing.\n\n"
        )

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

{youtube_note}=================================================
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
        youtube_note  = youtube_note,
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

    fb_post_id        = None
    ig_post_id        = None
    threads_post_id   = None
    youtube_post_url  = None
    image_url         = None   # single image used for IG/Threads

    fb_text      = adjust_follow_cta_for_platform(post["text"], "facebook")
    ig_text      = adjust_follow_cta_for_platform(post["text"], "instagram")
    threads_text = adjust_follow_cta_for_platform(post["text"], "threads")

    if ptype == "poll":
        # Multi-photo post: one image per poll option
        options = extract_poll_options(post["text"])
        print("  Poll options found: " + str(options))

        if options:
            poll_images = get_poll_images(options, topic=topic)
            print("  Got " + str(len(poll_images)) + " poll images")
            fb_post_id = post_to_facebook_multi(fb_text, poll_images)
            image_url  = poll_images[0] if poll_images else None
        else:
            # Fallback: single image of the topic band
            image_url  = get_best_image(topic, ptype)
            fb_post_id = post_to_facebook_single(fb_text, image_url)

    else:
        # Single image post
        youtube_url = post.get("video_url")
        post_year   = post.get("post_year", "")
        image_url   = get_best_image(topic, ptype, youtube_url, year=post_year)

        try:
            if youtube_url:
                try:
                    fb_post_id = post_to_facebook_link(fb_text, youtube_url, image_url)
                except RuntimeError as e:
                    print("  Facebook link post failed, falling back to image post: " + str(e))
                    fb_post_id = post_to_facebook_single(fb_text, image_url)
            else:
                fb_post_id = post_to_facebook_single(fb_text, image_url)
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
        ig_post_id = post_to_instagram(ig_text, image_url)
        print("  Instagram : " + ("Published! ID=" + str(ig_post_id) if ig_post_id else "Failed/skipped"))
    else:
        print("  Instagram : Not configured")

    # ── Threads ───────────────────────────────────────────────────────────
    if THREADS_USER_ID and THREADS_TOKEN:
        threads_post_id = post_to_threads(threads_text, image_url)
        print("  Threads   : " + ("Published! ID=" + str(threads_post_id) if threads_post_id else "Failed/skipped"))
    else:
        print("  Threads   : Not configured")

    if ptype == "youtube":
        youtube_post_url = upload_youtube_short_from_latest_reel(topic, post["text"])
        print("  YouTube   : " + ("Uploaded! URL=" + youtube_post_url if youtube_post_url else "Skipped/failed"))
    else:
        print("  YouTube   : Not applicable")

    # ── Mark published ────────────────────────────────────────────────────
    post["status"]          = "published"
    post["fb_post_id"]      = fb_post_id
    post["ig_post_id"]      = ig_post_id
    post["threads_post_id"] = threads_post_id
    post["youtube_post_url"] = youtube_post_url
    post["published_at"]    = now.isoformat()
    post["error"]           = None

    save_queue(posts)
    append_log({
        "post_id":          post["id"],
        "fb_post_id":       fb_post_id,
        "ig_post_id":       ig_post_id,
        "threads_post_id":  threads_post_id,
        "youtube_post_url": youtube_post_url,
        "post_type":        ptype,
        "topic":            topic,
        "image_url":        image_url,
        "status":           "published",
        "executed_at":      now.isoformat(),
    })

    pending_count   = sum(1 for p in posts if p["status"] == "pending")
    published_count = sum(1 for p in posts if p["status"] == "published")
    print("  Queue     : " + str(pending_count) + " pending | " + str(published_count) + " published")

    # Send email with X/TikTok posting instructions
    send_social_email(post)


if __name__ == "__main__":
    run()
