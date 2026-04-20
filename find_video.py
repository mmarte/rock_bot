"""
find_video.py
-------------
Searches YouTube for a rock en español video (music video or live performance),
then uses Groq to write an original commentary post around it.

Returns a single post dict ready to be inserted into the queue.
Called automatically by generate.py once per week.
"""

import os
import random
import requests
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY")

# ---------------------------------------------------------------------------
# Search terms — bot picks one randomly each week for variety
# ---------------------------------------------------------------------------

SEARCH_TERMS = [
    "Soda Stereo video oficial",
    "Soda Stereo concierto en vivo",
    "Maná video oficial",
    "Maná concierto en vivo",
    "Heroes del Silencio video",
    "Heroes del Silencio concierto",
    "Café Tacvba video oficial",
    "Café Tacvba en vivo",
    "Molotov video oficial",
    "Los Prisioneros video",
    "Fito Paez rock en español",
    "Caifanes video oficial",
    "La Ley concierto en vivo",
    "Los Fabulosos Cadillacs video",
    "Divididos rock argentino",
    "Bunbury video oficial",
    "Bunbury concierto",
    "Jarabe de Palo video",
    "Intocable en vivo",
    "Rata Blanca video oficial",
    "Gustavo Cerati solo en vivo",
    "Fito y Fitipaldis video",
    "rock en español clasicos 90s",
    "rock en español en vivo clasico",
    "rock argentino clasico video",
    "rock mexicano clasico video",
    "rock español clasico video",
]

# ---------------------------------------------------------------------------
# YouTube search
# ---------------------------------------------------------------------------

def search_youtube(search_term: str) -> dict | None:
    """
    Search YouTube for a video matching the search term.
    Returns a dict with video details or None on failure.
    Filters to only music videos and live performances (excludes covers,
    compilations, and reaction videos).
    """
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "key":        YOUTUBE_API_KEY,
                "q":          search_term,
                "part":       "snippet",
                "type":       "video",
                "videoCategoryId": "10",  # Music category
                "maxResults": 10,
                "relevanceLanguage": "es",
                "safeSearch": "none",
            },
            timeout=10,
        )
        r.raise_for_status()
        items = r.json().get("items", [])

        if not items:
            return None

        # Filter out covers, reactions, and compilations
        skip_keywords = ["cover", "reaccion", "reacción", "compilacion",
                         "compilación", "karaoke", "tutorial", "reaction"]

        filtered = [
            item for item in items
            if not any(
                kw in item["snippet"]["title"].lower()
                for kw in skip_keywords
            )
        ]

        if not filtered:
            filtered = items  # fallback to unfiltered if all got excluded

        # Pick randomly from top 5 to add variety across weeks
        pick = random.choice(filtered[:5])

        video_id    = pick["id"]["videoId"]
        title       = pick["snippet"]["title"]
        channel     = pick["snippet"]["channelTitle"]
        description = pick["snippet"]["description"][:300]
        url         = f"https://www.youtube.com/watch?v={video_id}"

        return {
            "video_id":    video_id,
            "title":       title,
            "channel":     channel,
            "description": description,
            "url":         url,
            "search_term": search_term,
        }

    except Exception as e:
        print(f"  YouTube search error: {e}")
        return None


# ---------------------------------------------------------------------------
# Groq commentary generation
# ---------------------------------------------------------------------------

COMMENTARY_SYSTEM = """Eres el creador de contenido de "Mejor Rock en Español",
una página de Facebook apasionada por el rock en español.
Tu misión es escribir un comentario original y apasionado sobre un video de YouTube
que vas a compartir con tus fans.

REGLAS:
- Escribe en español, tono conversacional y apasionado, como un fan experto
- NO copies descripción del video — escribe tu propia opinión y contexto
- Menciona algo específico sobre la banda, el álbum, la era, o el estilo musical
- Termina siempre con una pregunta que invite a comentar
- NUNCA copies letras de canciones
- Entre 120 y 200 palabras exactamente
- No incluyas el link en el texto — se agrega automáticamente al final"""


def generate_commentary(video: dict) -> str:
    """Use Groq to write an original commentary post about the video."""
    client = Groq(api_key=GROQ_API_KEY)

    prompt = (
        f"Escribe un post de Facebook sobre este video de YouTube:\n\n"
        f"Título: {video['title']}\n"
        f"Canal: {video['channel']}\n"
        f"Descripción: {video['description']}\n\n"
        f"Escribe tu comentario original como si fueras un fan apasionado "
        f"compartiendo este video con tu comunidad. "
        f"No copies nada de la descripción. "
        f"Termina con una pregunta para tus fans."
    )

    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": COMMENTARY_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.85,
        max_tokens=512,
    )

    commentary = completion.choices[0].message.content.strip()

    # Append the YouTube URL at the end of the post text
    return f"{commentary}\n\n{video['url']}"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def get_video_post() -> dict | None:
    """
    Full pipeline: pick search term → find video → generate commentary.
    Returns a post dict compatible with the posts.json queue schema,
    or None if the YouTube API is not configured or search fails.
    """
    if not YOUTUBE_API_KEY:
        print("  YOUTUBE_API_KEY not set — skipping video post.")
        return None

    search_term = random.choice(SEARCH_TERMS)
    print(f"  Searching YouTube for: '{search_term}'...")

    video = search_youtube(search_term)
    if not video:
        print("  No YouTube video found — skipping video post.")
        return None

    print(f"  Found: {video['title']} ({video['channel']})")
    print(f"  Generating commentary...")

    text = generate_commentary(video)

    return {
        "type":        "video_youtube",
        "text":        text,
        "image_query": None,   # No Pexels image — YouTube thumbnail used instead
        "video_url":   video["url"],
        "video_title": video["title"],
        "video_channel": video["channel"],
    }


if __name__ == "__main__":
    # Quick standalone test
    post = get_video_post()
    if post:
        print("\n--- Generated post ---")
        print(post["text"])
