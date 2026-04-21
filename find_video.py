"""
find_video.py
-------------
Finds a relevant YouTube video given a topic string (band name, era, etc.)
Returns video metadata for use in generate.py.
"""

import os
import random
import requests
from dotenv import load_dotenv

load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

SKIP_KEYWORDS = [
    "cover", "covers", "reaccion", "reacción", "reaction",
    "compilacion", "compilación", "compilation",
    "karaoke", "tutorial", "how to", "aprende",
]

# Suffixes to add variety — bot picks one randomly per search
VIDEO_SUFFIXES = [
    "video oficial",
    "concierto en vivo",
    "en vivo",
    "unplugged",
    "live performance",
    "documental",
]

# General fallback pool
FALLBACK_TERMS = [
    "Soda Stereo video oficial",
    "Maná concierto en vivo",
    "Heroes del Silencio video oficial",
    "Café Tacvba video oficial",
    "Molotov video oficial",
    "Caifanes video oficial",
    "Bunbury video oficial",
    "Los Fabulosos Cadillacs video",
    "La Ley video oficial",
    "Divididos video oficial",
    "Los Prisioneros video oficial",
    "Intocable en vivo",
    "Jarabe de Palo video",
    "Rata Blanca video oficial",
    "Fito Paez video oficial",
]


def search_youtube(query: str, used_ids: list | None = None) -> dict | None:
    if not YOUTUBE_API_KEY:
        return None
    used_ids = used_ids or []
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "key":               YOUTUBE_API_KEY,
                "q":                 query,
                "part":              "snippet",
                "type":              "video",
                "videoCategoryId":   "10",
                "maxResults":        15,
                "relevanceLanguage": "es",
                "safeSearch":        "none",
            },
            timeout=10,
        )
        r.raise_for_status()
        items = r.json().get("items", [])
        if not items:
            return None
        filtered = [
            i for i in items
            if i["id"]["videoId"] not in used_ids
            and not any(kw in i["snippet"]["title"].lower() for kw in SKIP_KEYWORDS)
        ]
        if not filtered:
            filtered = [i for i in items if i["id"]["videoId"] not in used_ids]
        if not filtered:
            return None
        pick = random.choice(filtered[:8])
        return {
            "video_id":    pick["id"]["videoId"],
            "title":       pick["snippet"]["title"],
            "channel":     pick["snippet"]["channelTitle"],
            "description": pick["snippet"]["description"][:300],
            "url":         f"https://www.youtube.com/watch?v={pick['id']['videoId']}",
        }
    except Exception as e:
        print(f"    YouTube error: {e}")
        return None


def get_video_for_topic(topic: str, used_ids: list | None = None) -> dict | None:
    """
    Find a YouTube video for a specific topic (e.g. 'Soda Stereo', 'Heroes del Silencio').
    Tries topic + suffix first, then fallback pool.
    """
    if not YOUTUBE_API_KEY:
        return None
    used_ids = used_ids or []

    # Try topic-specific search with a random suffix
    suffix = random.choice(VIDEO_SUFFIXES)
    video  = search_youtube(f"{topic} {suffix}", used_ids)

    # Fallback to general pool
    if not video:
        video = search_youtube(random.choice(FALLBACK_TERMS), used_ids)

    return video


if __name__ == "__main__":
    topics = ["Soda Stereo", "Maná", "Heroes del Silencio", "Café Tacvba",
              "Molotov", "Caifanes", "Bunbury"]
    used = []
    for t in topics:
        print(f"\nTopic: {t}")
        v = get_video_for_topic(t, used)
        if v:
            print(f"  {v['title']}")
            print(f"  {v['url']}")
            used.append(v["video_id"])
        else:
            print("  No video found")
