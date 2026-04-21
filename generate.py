"""
generate.py
-----------
Generates 14 posts per week (2/day):
  Morning 11am EST  — Poll (Mon/Wed/Sat), Original (Tue/Thu/Fri), Concert (Sun)
  Evening  7pm EST  — YouTube commentary every day

Emulated polls use Like/Love/Care emoji voting instead of native FB polls.

Run manually:  python generate.py
Runs via cron: every Sunday at 8am UTC (GitHub Actions)
"""

from groq import Groq
from find_video import get_video_for_topic
from find_concert import get_concert_info
import json
import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
POSTS_FILE   = "posts.json"

# UTC hours for posting
# 16:00 UTC = 11:00 AM EST (UTC-5)  / 10:00 AM CST (UTC-6)
# 00:00 UTC = 7:00 PM EST (UTC-5)   / 6:00 PM CST (UTC-6)
MORNING_UTC   = 16
EVENING_UTC   = 0   # midnight UTC = 7pm EST previous day

# Day index 0=Mon ... 6=Sun
# Tomorrow is day 0 of the generated week
MORNING_TYPES = {
    0: "poll",      # Monday
    1: "original",  # Tuesday
    2: "poll",      # Wednesday
    3: "original",  # Thursday
    4: "original",  # Friday
    5: "poll",      # Saturday
    6: "concert",   # Sunday
}

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

SYSTEM_ORIGINAL = """Eres el creador de contenido de "Mejor Rock en Español",
una página de Facebook apasionada por el rock en español clásico y moderno.

REGLAS:
- Español natural y conversacional, tono de fan apasionado
- Termina siempre con una pregunta directa que invite a comentar
- NUNCA copies letras de canciones
- 120–220 palabras por post
- Menciona bandas reales y específicas

FORMATO: JSON puro, sin markdown, sin explicaciones.
{
  "posts": [
    {
      "type": "debate|trivia|historia|ranking|recuerdo|curiosidad",
      "topic": "nombre de banda o tema principal",
      "text": "contenido del post",
      "image_query": "nombre específico de banda + descriptor EN INGLÉS, ej: Soda Stereo band photo"
    }
  ]
}"""

SYSTEM_POLL = """Eres el creador de "Mejor Rock en Español" en Facebook.
Crea posts de votación usando emojis en lugar de encuestas nativas.

FORMATO DE VOTO OBLIGATORIO — usa exactamente estos emojis:
👍 = opción A
❤️ = opción B
😮 = opción C (solo si hay 3 opciones)

REGLAS:
- Plantea una pregunta de debate apasionante sobre rock en español
- Lista las opciones claramente con los emojis
- Explica brevemente cada opción (1 línea)
- Termina con: "¡Vota con tu reacción!"
- 80–140 palabras
- NUNCA copies letras de canciones

FORMATO: JSON puro.
{
  "topic": "tema de la votación",
  "text": "contenido del post",
  "image_query": "nombre específico de banda EN INGLÉS, ej: Heroes del Silencio concert"
}"""

SYSTEM_CONCERT = """Eres el creador de "Mejor Rock en Español" en Facebook.
Se te dará información de un concierto próximo. Escribe un post emocionante
para compartirlo con los fans.

REGLAS:
- Tono emocionado, urgente, como si fuera la noticia del día
- Incluye la fecha, ciudad y nombre del artista/evento
- Llama a la acción: "¡Consigue tus boletos antes de que se agoten!"
- NO incluyas el link en el texto — se agrega automáticamente al final
- 80–150 palabras
- Termina con una pregunta: "¿Quién va a ir?" o similar

FORMATO: JSON puro.
{
  "topic": "artista o festival",
  "text": "contenido del post",
  "image_query": "artista o festival EN INGLÉS + concert"
}"""

SYSTEM_YOUTUBE = """Eres el creador de "Mejor Rock en Español" en Facebook.
Se te dará un video de YouTube. Escribe un comentario original para compartirlo.

REGLAS:
- Español conversacional, tono de fan compartiendo algo que le encanta
- Menciona algo específico del video, banda o era musical
- NO copies la descripción del video — escribe tu propia opinión
- NO incluyas el link en el texto — se agrega al final automáticamente
- Termina con una pregunta que invite a comentar
- 100–180 palabras
- NUNCA copies letras de canciones"""

# ---------------------------------------------------------------------------
# Content variety pools for original posts
# ---------------------------------------------------------------------------

ORIGINAL_TYPES = [
    {"type": "debate",       "instruction": "DEBATE apasionante entre dos bandas o épocas. Pide a los fans que elijan."},
    {"type": "trivia",       "instruction": "TRIVIA con curiosidad poco conocida sobre una banda o canción icónica."},
    {"type": "historia",     "instruction": "HISTORIA BREVE de cómo se formó una banda o nació un álbum famoso."},
    {"type": "ranking",      "instruction": "RANKING de los 3 mejores álbumes, canciones o guitarristas. Pide el top del fan."},
    {"type": "recuerdo",     "instruction": "RECUERDO de un concierto mítico o gira legendaria. Invita a compartir recuerdos."},
    {"type": "curiosidad",   "instruction": "CURIOSIDAD impactante: colaboración inesperada, dato de producción, hecho poco conocido."},
]

POLL_TOPICS = [
    ("¿Cuál fue el mejor álbum de los 90s?",    ["Dynamo - Soda Stereo", "Entre Dos Aguas - Heroes del Silencio", "Re - Café Tacvba"]),
    ("¿El mejor concierto en vivo de la historia?", ["Soda Stereo Me Verás Volver", "Heroes del Silencio", "Maná"]),
    ("¿La mejor banda de rock mexicano?",        ["Café Tacvba", "Molotov", "Caifanes"]),
    ("¿El mejor vocalista del rock en español?", ["Gustavo Cerati", "Enrique Bunbury", "Fito Páez"]),
    ("¿La mejor época del rock en español?",     ["Los 80s clásicos", "Los 90s dorados", "Los 2000s alternativos"]),
    ("¿El mejor guitarrista del rock en español?", ["Zeta Bosio - Soda Stereo", "Iñaki Uoho - Heroes", "Quique Rangel - Café Tacvba"]),
    ("¿El álbum más influyente?",                ["Doble Vida - Soda Stereo", "Nada Personal - Soda Stereo", "Donde Jugaran los Niños - Maná"]),
    ("¿La mejor colaboración del rock en español?", ["Bunbury y Héroes del Silencio", "Cerati y Spinetta", "Maná y Santana"]),
    ("¿Rock argentino o rock mexicano?",         ["Rock argentino", "Rock mexicano", "¡Los dos por igual!"]),
    ("¿La canción perfecta del rock en español?", ["De Música Ligera - Soda Stereo", "Entre Dos Tierras - Heroes", "Oye Mi Amor - Maná"]),
    ("¿El mejor festival de rock en español?",   ["Vive Latino", "Lollapalooza LatAm", "Festival Estéreo Picnic"]),
    ("¿La mejor intro de guitarra?",             ["De Música Ligera", "Entre Dos Tierras", "La Chispa Adecuada"]),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw   = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def load_queue() -> list:
    if os.path.exists(POSTS_FILE):
        with open(POSTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_queue(posts: list):
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def schedule_slot(day_offset: int, hour_utc: int) -> str:
    """Return ISO datetime for a given day offset from tomorrow at a UTC hour."""
    base = datetime.now(timezone.utc).replace(
        minute=0, second=0, microsecond=0
    ) + timedelta(days=day_offset + 1)
    # For evening (hour=0), we need to add 1 extra day
    # because 00:00 UTC is midnight, which is evening of the NEXT day
    if hour_utc == 0:
        base = base + timedelta(days=1)
    return base.replace(hour=hour_utc).isoformat()


def make_post(stamp, day, slot, post_type, topic, text, image_query,
              video_url=None, concert_url=None) -> dict:
    return {
        "id":           f"post_{stamp}_day{day}_{slot}",
        "status":       "pending",
        "scheduled_at": schedule_slot(day, MORNING_UTC if slot == "morning" else EVENING_UTC),
        "slot":         slot,
        "type":         post_type,
        "topic":        topic,
        "text":         text,
        "image_query":  image_query,
        "video_url":    video_url,
        "concert_url":  concert_url,
        "fb_post_id":   None,
        "created_at":   datetime.now(timezone.utc).isoformat(),
        "published_at": None,
        "error":        None,
    }


# ---------------------------------------------------------------------------
# Content generators
# ---------------------------------------------------------------------------

def gen_original(client: Groq, used_types: list) -> dict:
    """Generate one original post (debate/trivia/historia/ranking/recuerdo/curiosidad)."""
    # Pick a type not recently used
    available = [t for t in ORIGINAL_TYPES if t["type"] not in used_types]
    if not available:
        available = ORIGINAL_TYPES
    chosen = available[0]
    used_types.append(chosen["type"])

    prompt = (
        f"Genera 1 post de tipo {chosen['type'].upper()}. "
        f"Instrucción: {chosen['instruction']}\n\n"
        f"IMPORTANTE: image_query debe ser el nombre específico de la banda "
        f"mencionada en el post + un descriptor visual en inglés. "
        f"Ejemplo: 'Soda Stereo band', 'Mana concert', 'Heroes del Silencio live'.\n\n"
        f"Responde ÚNICAMENTE con JSON válido."
    )

    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_ORIGINAL},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.85,
        max_tokens=1024,
        response_format={"type": "json_object"},
    )

    data = json.loads(clean_json(completion.choices[0].message.content))

    # Handle both {"posts": [...]} and flat object
    if "posts" in data:
        data = data["posts"][0]

    return data


def gen_poll(client: Groq, used_polls: list) -> dict:
    """Generate one emulated poll post using emoji reactions."""
    import random as _random
    available = [p for p in POLL_TOPICS if p[0] not in used_polls]
    if not available:
        available = POLL_TOPICS
    question, options = _random.choice(available)
    used_polls.append(question)

    emoji_map = ["👍", "❤️", "😮"]
    options_text = "\n".join(
        f"{emoji_map[i]} {opt}" for i, opt in enumerate(options[:3])
    )

    prompt = (
        f"Crea un post de votación sobre: '{question}'\n\n"
        f"Opciones:\n{options_text}\n\n"
        f"Usa exactamente estos emojis para votar: "
        f"👍 = {options[0]}, ❤️ = {options[1]}"
        + (f", 😮 = {options[2]}" if len(options) > 2 else "") +
        f"\n\nTermina con: '¡Vota con tu reacción!'\n\n"
        f"Para image_query usa el nombre de una de las bandas mencionadas + 'band' o 'concert'.\n\n"
        f"Responde ÚNICAMENTE con JSON válido."
    )

    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_POLL},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.75,
        max_tokens=512,
        response_format={"type": "json_object"},
    )

    return json.loads(clean_json(completion.choices[0].message.content))


def gen_concert(client: Groq) -> dict:
    """Generate a concert announcement post using Ticketmaster data."""
    concert = get_concert_info()

    if concert:
        prompt = (
            f"Concierto próximo:\n"
            f"  Artista/Evento: {concert['name']}\n"
            f"  Fecha: {concert['date']}\n"
            f"  Ciudad: {concert['city']}, {concert['country']}\n\n"
            f"Escribe el post de anuncio. NO incluyas el link — va al final automáticamente.\n"
            f"image_query: nombre del artista + 'concert' en inglés.\n\n"
            f"Responde ÚNICAMENTE con JSON válido."
        )
        concert_url = concert["url"]
        topic       = concert["artist"]
    else:
        # Fallback if no Ticketmaster key or no events found
        prompt = (
            f"Escribe un post general sobre cómo comprar boletos para ver bandas "
            f"de rock en español en vivo. Menciona sitios como Ticketmaster y StubHub. "
            f"image_query: 'rock concert tickets latinamerica'.\n\n"
            f"Responde ÚNICAMENTE con JSON válido."
        )
        concert_url = "https://www.ticketmaster.com/search?q=rock+en+espanol"
        topic       = "conciertos rock en español"

    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_CONCERT},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.80,
        max_tokens=512,
        response_format={"type": "json_object"},
    )

    data = json.loads(clean_json(completion.choices[0].message.content))
    data["concert_url"] = concert_url
    data["topic"]       = topic
    return data


def gen_youtube_commentary(client: Groq, morning_topic: str,
                           used_video_ids: list) -> dict | None:
    """Find a YouTube video and generate commentary for the evening post."""
    video = get_video_for_topic(morning_topic, used_video_ids)
    if not video:
        return None

    used_video_ids.append(video["video_id"])

    prompt = (
        f"Video de YouTube:\n"
        f"  Título: {video['title']}\n"
        f"  Canal: {video['channel']}\n"
        f"  Descripción: {video['description']}\n\n"
        f"El post de la mañana fue sobre: {morning_topic}\n\n"
        f"Escribe el comentario. NO incluyas el link.\n"
        f"Empieza con algo como 'Para cerrar el día', 'Les comparto este clásico', "
        f"'Esta noche les traigo'..."
    )

    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_YOUTUBE},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.85,
        max_tokens=512,
    )

    commentary = completion.choices[0].message.content.strip()

    return {
        "text":      f"{commentary}\n\n{video['url']}",
        "video_url": video["url"],
        "topic":     morning_topic,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate_posts():
    now   = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d")
    print(f"[{now.isoformat()}] Generating 14 posts (7 morning + 7 evening YouTube)...\n")

    client        = Groq(api_key=GROQ_API_KEY)
    all_posts     = []
    used_types    = []
    used_polls    = []
    used_video_ids = []

    for day in range(7):
        day_name     = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][day]
        morning_type = MORNING_TYPES[day]

        print(f"  Day {day} ({day_name}) — morning: {morning_type}")

        # ------------------------------------------------------------------
        # MORNING POST
        # ------------------------------------------------------------------
        if morning_type == "poll":
            data        = gen_poll(client, used_polls)
            topic       = data.get("topic", "rock en español")
            morning_post = make_post(
                stamp, day, "morning", "poll", topic,
                data["text"], data.get("image_query", f"{topic} band"),
            )

        elif morning_type == "original":
            data        = gen_original(client, used_types)
            topic       = data.get("topic", "rock en español")
            morning_post = make_post(
                stamp, day, "morning", data.get("type", "original"), topic,
                data["text"], data.get("image_query", f"{topic} band"),
            )

        elif morning_type == "concert":
            data        = gen_concert(client)
            topic       = data.get("topic", "conciertos")
            morning_post = make_post(
                stamp, day, "morning", "concert", topic,
                data["text"] + f"\n\n{data['concert_url']}",
                data.get("image_query", "rock concert"),
                concert_url=data.get("concert_url"),
            )

        all_posts.append(morning_post)
        print(f"         topic='{morning_post['topic']}' — {morning_post['text'][:50]}...")

        # ------------------------------------------------------------------
        # EVENING POST — YouTube commentary based on morning topic
        # ------------------------------------------------------------------
        print(f"           evening: YouTube (topic: {morning_post['topic']})")
        yt = gen_youtube_commentary(client, morning_post["topic"], used_video_ids)

        if yt:
            evening_post = make_post(
                stamp, day, "evening", "video_youtube",
                yt["topic"], yt["text"],
                morning_post["image_query"],   # reuse topic-matched image query
                video_url=yt["video_url"],
            )
        else:
            # Fallback if YouTube unavailable — duplicate morning as text-only
            print(f"           (no YouTube video found — skipping evening)")
            evening_post = make_post(
                stamp, day, "evening", "video_youtube_unavailable",
                morning_post["topic"],
                "¡Nos vemos mañana con más rock en español! 🎸",
                morning_post["image_query"],
            )

        all_posts.append(evening_post)
        print(f"         {evening_post['text'][:60]}...")
        print()

    # ------------------------------------------------------------------
    # Save queue
    # ------------------------------------------------------------------
    existing      = load_queue()
    still_pending = [p for p in existing if p["status"] == "pending"]
    merged        = still_pending + all_posts
    save_queue(merged)

    morning_count = sum(1 for p in all_posts if p["slot"] == "morning")
    evening_count = sum(1 for p in all_posts if p["slot"] == "evening")
    print(f"Done. Generated {morning_count} morning + {evening_count} evening posts.")
    print(f"Total pending in queue: {len(merged)}")


if __name__ == "__main__":
    generate_posts()
