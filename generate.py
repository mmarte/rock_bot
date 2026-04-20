"""
generate.py
-----------
Calls Groq API (Llama 3.3 70B) to generate 7 Facebook posts for the week,
then writes them to posts.json as a scheduled queue.

Run manually:  python generate.py
Runs via cron: every Sunday at 8am (configured in GitHub Actions)
"""

from groq import Groq
from find_video import get_video_post
import json
import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GROQ_API_KEY  = os.getenv("GROQ_API_KEY")
POSTS_FILE    = "posts.json"

# Post hour in UTC — 15:00 UTC = 11:00 AM EST / 10:00 AM CST (Mexico City)
POST_HOUR_UTC = 15

SYSTEM_PROMPT = """Eres el creador de contenido de "Mejor Rock en Español",
una página de Facebook apasionada por el rock en español clásico y moderno.
Tu misión es generar posts originales, apasionantes, que generen debate,
nostalgia y participación activa de los fans.

REGLAS ESTRICTAS:
- Escribe en español, tono natural y conversacional, como un fan apasionado
- Siempre termina con una pregunta directa que invite a comentar
- NUNCA copies letras de canciones ni menciones reproducir audio/video de terceros
- Varía el formato según el tipo solicitado
- Menciona bandas reales: Soda Stereo, Maná, Heroes del Silencio, Café Tacvba,
  Molotov, Los Prisioneros, Fito & Fitipaldis, Divididos, Caifanes, La Ley,
  Los Fabulosos Cadillacs, Rata Blanca, Intocable, Bunbury, Jarabe de Palo

LONGITUD: entre 120 y 220 palabras por post. No más, no menos.

FORMATO DE RESPUESTA: JSON puro y válido únicamente.
Sin bloques de código, sin markdown, sin explicaciones antes o después.
Esquema exacto requerido:
{
  "posts": [
    {
      "type": "string",
      "text": "string",
      "image_query": "string in English for Pexels image search"
    }
  ]
}"""

CONTENT_TYPES = [
    {
        "type": "debate",
        "instruction": "Genera un post de DEBATE entre dos bandas o épocas del rock en español. "
                       "Plantea el debate de forma apasionante y pide a los fans que elijan."
    },
    {
        "type": "trivia",
        "instruction": "Genera un post de TRIVIA con una curiosidad sorprendente o poco conocida "
                       "sobre una banda o canción icónica del rock en español."
    },
    {
        "type": "historia",
        "instruction": "Genera un post contando la HISTORIA BREVE de cómo se formó una banda "
                       "icónica o cómo nació uno de sus álbumes más famosos."
    },
    {
        "type": "ranking",
        "instruction": "Genera un post con un RANKING de los 3 mejores álbumes, canciones o "
                       "guitarristas de un género o época del rock en español. "
                       "Luego pide al fan que dé su propio top."
    },
    {
        "type": "recuerdo",
        "instruction": "Genera un post evocando el RECUERDO de un concierto mítico, "
                       "una gira legendaria, o el primer día que alguien escuchó a una banda. "
                       "Invita a los fans a compartir su propio recuerdo."
    },
    {
        "type": "curiosidad",
        "instruction": "Genera un post con una CURIOSIDAD MUSICAL impactante: una colaboración "
                       "inesperada, un dato sobre la producción de un álbum, o un hecho que "
                       "pocos fans conocen."
    },
    {
        "type": "pregunta_del_dia",
        "instruction": "Genera una PREGUNTA DEL DÍA simple pero poderosa que haga al fan "
                       "pensar en su relación personal con el rock en español. "
                       "Algo que cualquier fan pueda responder en segundos."
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_user_prompt():
    instructions = "\n".join(
        f"{i+1}. [{ct['type'].upper()}] {ct['instruction']}"
        for i, ct in enumerate(CONTENT_TYPES)
    )
    return (
        f"Genera exactamente 7 posts, uno por cada tipo indicado a continuación.\n\n"
        f"{instructions}\n\n"
        f"Para cada post incluye también un 'image_query' en inglés de 3-5 palabras "
        f"para buscar una imagen relevante en Pexels (ejemplo: 'rock concert crowd stage', "
        f"'electric guitar close up', 'latin band performance').\n\n"
        f"Responde ÚNICAMENTE con el JSON válido. Sin texto adicional."
    )


def schedule_posts():
    """Return ISO datetime strings, one per day starting tomorrow at POST_HOUR_UTC."""
    base = datetime.now(timezone.utc).replace(
        hour=POST_HOUR_UTC, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)
    return [(base + timedelta(days=i)).isoformat() for i in range(7)]


def load_queue():
    if os.path.exists(POSTS_FILE):
        with open(POSTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_queue(posts):
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def clean_json(raw: str) -> str:
    """Strip markdown code fences that some models add around JSON."""
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate_posts():
    now = datetime.now(timezone.utc)
    print(f"[{now.isoformat()}] Starting content generation with Groq (Llama 3.3 70B)...")

    client = Groq(api_key=GROQ_API_KEY)

    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": build_user_prompt()},
        ],
        temperature=0.85,
        max_tokens=4096,
        response_format={"type": "json_object"},
    )

    raw  = completion.choices[0].message.content
    raw  = clean_json(raw)
    data = json.loads(raw)

    # Handle both {"posts": [...]} and bare [...] responses
    if isinstance(data, list):
        generated = data
    elif "posts" in data:
        generated = data["posts"]
    else:
        generated = next(v for v in data.values() if isinstance(v, list))

    if len(generated) != 7:
        raise ValueError(f"Expected 7 posts, got {len(generated)}.\nRaw:\n{raw}")

    schedule  = schedule_posts()
    stamp     = now.strftime("%Y%m%d")

    new_posts = [
        {
            "id":           f"post_{stamp}_{i}",
            "status":       "pending",
            "scheduled_at": schedule[i],
            "type":         generated[i].get("type", CONTENT_TYPES[i]["type"]),
            "text":         generated[i]["text"],
            "image_query":  generated[i].get("image_query", "rock music concert"),
            "fb_post_id":   None,
            "created_at":   now.isoformat(),
            "published_at": None,
            "error":        None,
        }
        for i in range(7)
    ]

    # Keep posts still pending from a previous batch
    existing      = load_queue()
    still_pending = [p for p in existing if p["status"] == "pending"]

    # Replace Wednesday post (index 2) with a YouTube video commentary
    print("  Looking for a YouTube video to feature this week...")
    video_post = get_video_post()
    if video_post:
        new_posts[2]["type"]        = video_post["type"]
        new_posts[2]["text"]        = video_post["text"]
        new_posts[2]["image_query"] = video_post["image_query"]
        new_posts[2]["video_url"]   = video_post.get("video_url")
        new_posts[2]["video_title"] = video_post.get("video_title")
        print(f"  YouTube post set for Wednesday: {video_post.get("video_title","")[:50]}")
    else:
        print("  No YouTube video found — keeping original Wednesday post.")

    merged = still_pending + new_posts

    save_queue(merged)

    print(f"Generated {len(new_posts)} new posts. Total pending in queue: {len(merged)}")
    for p in new_posts:
        print(f"  [{p['type']:18s}] {p['scheduled_at'][:16]} UTC — {p['text'][:55]}...")


if __name__ == "__main__":
    generate_posts()
