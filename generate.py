"""
generate.py
-----------
Generates exactly 2 posts for TODAY (not a whole week):
  Morning 11am EST  — Poll (Mon/Wed/Sat), Original (Tue/Thu/Fri), Concert (Sun)
  Evening  7pm EST  — YouTube commentary every day

Runs daily via GitHub Actions cron at 08:00 UTC (before the 11am morning post).
Can also be run manually anytime: python generate.py

Daily schedule:
  Monday    → Poll      + YouTube
  Tuesday   → Original  + YouTube
  Wednesday → Poll      + YouTube
  Thursday  → Original  + YouTube
  Friday    → Original  + YouTube
  Saturday  → Poll      + YouTube
  Sunday    → Concert   + YouTube
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

# UTC hours — adjust if your audience is primarily in a different timezone
# 16:00 UTC = 11:00 AM EST / 10:00 AM CST (Mexico City)
# 00:00 UTC = 7:00 PM EST / 6:00 PM CST  (next calendar day in UTC)
MORNING_UTC = 16
EVENING_UTC = 0

# Day-of-week to morning post type (0=Monday ... 6=Sunday)
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
# Poll topics — rotated based on week number so they don't repeat
# ---------------------------------------------------------------------------

POLL_TOPICS = [
    ("¿Cuál fue el mejor álbum de los 90s?",
     ["Dynamo - Soda Stereo", "Nada Personal - Soda Stereo", "Re - Café Tacvba"]),
    ("¿El mejor concierto en vivo de la historia del rock en español?",
     ["Soda Stereo Me Verás Volver", "Heroes del Silencio", "Maná en el Zócalo"]),
    ("¿La mejor banda de rock mexicano?",
     ["Café Tacvba", "Molotov", "Caifanes"]),
    ("¿El mejor vocalista del rock en español?",
     ["Gustavo Cerati", "Enrique Bunbury", "Fito Páez"]),
    ("¿La mejor época del rock en español?",
     ["Los 80s clásicos", "Los 90s dorados", "Los 2000s alternativos"]),
    ("¿El mejor guitarrista del rock en español?",
     ["Zeta Bosio - Soda Stereo", "Iñaki Uoho - Heroes del Silencio", "Quique Rangel - Café Tacvba"]),
    ("¿El álbum más influyente de todos los tiempos?",
     ["Doble Vida - Soda Stereo", "Donde Jugaran los Niños - Maná", "El Espíritu del Vino - Heroes"]),
    ("¿Rock argentino o rock mexicano?",
     ["Rock argentino siempre", "Rock mexicano para siempre", "¡Los dos son igual de grandes!"]),
    ("¿La canción perfecta del rock en español?",
     ["De Música Ligera - Soda Stereo", "Entre Dos Tierras - Heroes del Silencio", "Oye Mi Amor - Maná"]),
    ("¿El mejor festival de rock en español?",
     ["Vive Latino", "Lollapalooza LatAm", "Festival Estéreo Picnic"]),
    ("¿La mejor colaboración del rock en español?",
     ["Cerati y Spinetta", "Maná y Santana", "Bunbury y Los Tigres del Norte"]),
    ("¿La mejor intro de guitarra del rock en español?",
     ["De Música Ligera - Cerati", "La Chispa Adecuada - Divididos", "Matador - Los Fabulosos Cadillacs"]),
]

# ---------------------------------------------------------------------------
# Original post variety types (rotated by weekday)
# ---------------------------------------------------------------------------

ORIGINAL_TYPES = [
    {"type": "debate",     "instruction": "DEBATE apasionante entre dos bandas o épocas. Pide a los fans que elijan."},
    {"type": "trivia",     "instruction": "TRIVIA con curiosidad poco conocida sobre una banda o canción icónica."},
    {"type": "historia",   "instruction": "HISTORIA BREVE de cómo se formó una banda o nació un álbum famoso."},
    {"type": "ranking",    "instruction": "RANKING de los 3 mejores álbumes, canciones o guitarristas. Pide el top del fan."},
    {"type": "recuerdo",   "instruction": "RECUERDO de un concierto mítico o gira legendaria. Invita a compartir recuerdos."},
    {"type": "curiosidad", "instruction": "CURIOSIDAD impactante: dato de producción, hecho poco conocido, colaboración inesperada."},
]

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

SYSTEM_ORIGINAL = """Eres el creador de "Mejor Rock en Español" en Facebook.
REGLAS:
- Español natural y conversacional, tono de fan apasionado
- Termina siempre con una pregunta directa que invite a comentar
- NUNCA copies letras de canciones
- 120–220 palabras
- Menciona bandas reales y específicas

FORMATO: JSON puro, sin markdown.
{"type":"string","topic":"banda o tema principal","text":"contenido","image_query":"nombre banda EN INGLÉS + descriptor, ej: Soda Stereo band photo"}"""

SYSTEM_POLL = """Eres el creador de "Mejor Rock en Español" en Facebook.
Crea posts de votación con emojis en lugar de encuestas nativas.

EMOJIS DE VOTO:
👍 = opción A
❤️ = opción B
😮 = opción C (solo si hay 3 opciones)

REGLAS:
- Plantea la votación con emoción y pasión
- Lista las opciones claramente con los emojis y una breve descripción
- Termina EXACTAMENTE con: "¡Vota con tu reacción! 👍❤️😮"
- 80–140 palabras
- NUNCA copies letras de canciones

FORMATO: JSON puro.
{"topic":"tema","text":"contenido","image_query":"banda específica EN INGLÉS + band o concert"}"""

SYSTEM_CONCERT = """Eres el creador de "Mejor Rock en Español" en Facebook.
Escribe un post emocionante sobre un concierto próximo.
REGLAS:
- Tono emocionado y urgente
- Incluye fecha, ciudad y artista
- Termina con "¡Consigue tus boletos antes de que se agoten!" y una pregunta
- NO incluyas el link — va al final automáticamente
- 80–150 palabras

FORMATO: JSON puro.
{"topic":"artista","text":"contenido","image_query":"artista EN INGLÉS + concert live"}"""

SYSTEM_YOUTUBE = """Eres el creador de "Mejor Rock en Español" en Facebook.
Escribe un comentario para compartir un video de YouTube esta noche.
REGLAS:
- Español conversacional, como un fan compartiendo algo que le encanta
- Empieza con frases como: "Para cerrar el día 🎸", "Esta noche les traigo un clásico...", "Los dejo con esto antes de dormir..."
- Menciona algo específico de la banda o era musical
- NO copies la descripción del video
- NO incluyas el link — va al final
- Termina con una pregunta
- 100–180 palabras
- NUNCA copies letras"""

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


def today_schedule(hour_utc: int) -> str:
    """Return ISO datetime for today at the given UTC hour."""
    now  = datetime.now(timezone.utc)
    slot = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    # Evening slot (hour=0) is midnight UTC — if we're past midnight, push to tonight
    if hour_utc == 0:
        slot = slot + timedelta(days=1)
    return slot.isoformat()


def make_post(stamp, slot, post_type, topic, text, image_query,
              video_url=None, concert_url=None) -> dict:
    hour = MORNING_UTC if slot == "morning" else EVENING_UTC
    return {
        "id":           f"post_{stamp}_{slot}",
        "status":       "pending",
        "scheduled_at": today_schedule(hour),
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


def call_groq(client, system, user, max_tokens=1024, json_mode=True) -> str:
    kwargs = dict(
        model    = "llama-3.3-70b-versatile",
        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        temperature = 0.85,
        max_tokens  = max_tokens,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    completion = client.chat.completions.create(**kwargs)
    return completion.choices[0].message.content


# ---------------------------------------------------------------------------
# Content generators
# ---------------------------------------------------------------------------

def gen_poll(client: Groq, week_number: int) -> dict:
    topic_idx          = week_number % len(POLL_TOPICS)
    question, options  = POLL_TOPICS[topic_idx]
    emoji_map          = ["👍", "❤️", "😮"]
    options_lines      = "\n".join(
        f"{emoji_map[i]} {opt}" for i, opt in enumerate(options[:3])
    )
    vote_instruction = (
        f"👍 = {options[0]}, ❤️ = {options[1]}"
        + (f", 😮 = {options[2]}" if len(options) > 2 else "")
    )
    prompt = (
        f"Crea un post de votación para esta pregunta: '{question}'\n\n"
        f"Opciones con emojis:\n{options_lines}\n\n"
        f"Sistema de voto: {vote_instruction}\n\n"
        f"image_query: nombre específico de una de las bandas mencionadas + 'band' o 'concert' en inglés.\n\n"
        f"Responde ÚNICAMENTE con JSON válido."
    )
    raw  = call_groq(client, SYSTEM_POLL, prompt, max_tokens=512)
    data = json.loads(clean_json(raw))
    return data


def gen_original(client: Groq, weekday: int) -> dict:
    # Rotate original types by weekday (Tue=1, Thu=3, Fri=4)
    original_map = {1: 0, 3: 1, 4: 2}  # weekday → ORIGINAL_TYPES index (mod len)
    idx    = original_map.get(weekday, 0)
    chosen = ORIGINAL_TYPES[idx % len(ORIGINAL_TYPES)]

    prompt = (
        f"Genera 1 post de tipo {chosen['type'].upper()}.\n"
        f"Instrucción: {chosen['instruction']}\n\n"
        f"IMPORTANTE: image_query = nombre específico de la banda mencionada "
        f"+ descriptor visual en inglés (ej: 'Soda Stereo band', 'Mana concert', "
        f"'Heroes del Silencio live').\n\n"
        f"Responde ÚNICAMENTE con JSON válido."
    )
    raw  = call_groq(client, SYSTEM_ORIGINAL, prompt, max_tokens=1024)
    data = json.loads(clean_json(raw))

    # Handle {"posts": [...]} wrapper
    if "posts" in data:
        data = data["posts"][0]
    return data


def gen_concert(client: Groq) -> dict:
    concert = get_concert_info()

    if concert:
        prompt = (
            f"Concierto próximo:\n"
            f"  Artista: {concert['name']}\n"
            f"  Fecha: {concert['date']}\n"
            f"  Ciudad: {concert['city']}, {concert['country']}\n\n"
            f"Escribe el post. NO incluyas el link.\n"
            f"image_query: nombre del artista en inglés + 'concert live'.\n\n"
            f"Responde ÚNICAMENTE con JSON válido."
        )
        concert_url = concert["url"]
        fallback_url = None
    else:
        prompt = (
            f"Escribe un post general animando a los fans a ver bandas de rock en español "
            f"en vivo. Menciona sitios como Ticketmaster, Vivid Seats y StubHub para conseguir boletos.\n"
            f"image_query: 'rock concert latinamerica live'.\n\n"
            f"Responde ÚNICAMENTE con JSON válido."
        )
        concert_url = "https://www.vividseats.com/concerts"
        fallback_url = concert_url

    raw  = call_groq(client, SYSTEM_CONCERT, prompt, max_tokens=512)
    data = json.loads(clean_json(raw))
    data["concert_url"] = concert_url
    return data


def gen_youtube(client: Groq, morning_topic: str) -> dict | None:
    video = get_video_for_topic(morning_topic, [])
    if not video:
        return None

    prompt = (
        f"Video de YouTube:\n"
        f"  Título: {video['title']}\n"
        f"  Canal: {video['channel']}\n"
        f"  Descripción: {video['description']}\n\n"
        f"El post de esta mañana fue sobre: {morning_topic}\n\n"
        f"Escribe el comentario de esta noche. NO incluyas el link."
    )
    commentary = call_groq(
        client, SYSTEM_YOUTUBE, prompt,
        max_tokens=512, json_mode=False
    ).strip()

    return {
        "text":      f"{commentary}\n\n{video['url']}",
        "video_url": video["url"],
        "topic":     morning_topic,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate_posts():
    now      = datetime.now(timezone.utc)
    weekday  = now.weekday()   # 0=Mon, 6=Sun
    week_num = now.isocalendar()[1]
    stamp    = now.strftime("%Y%m%d")

    day_names    = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    morning_type = MORNING_TYPES[weekday]

    print(f"[{now.isoformat()}] Generating 2 posts for {day_names[weekday]}...")
    print(f"  Morning type: {morning_type}\n")

    client = Groq(api_key=GROQ_API_KEY)

    # ------------------------------------------------------------------
    # MORNING POST
    # ------------------------------------------------------------------
    if morning_type == "poll":
        data  = gen_poll(client, week_num)
        topic = data.get("topic", "rock en español")
        morning = make_post(
            stamp, "morning", "poll", topic,
            data["text"],
            data.get("image_query", f"{topic} band"),
        )

    elif morning_type == "original":
        data  = gen_original(client, weekday)
        topic = data.get("topic", "rock en español")
        morning = make_post(
            stamp, "morning", data.get("type", "original"), topic,
            data["text"],
            data.get("image_query", f"{topic} band"),
        )

    elif morning_type == "concert":
        data  = gen_concert(client)
        topic = data.get("topic", "conciertos rock en español")
        morning = make_post(
            stamp, "morning", "concert", topic,
            data["text"] + f"\n\n{data['concert_url']}",
            data.get("image_query", "rock concert latinamerica"),
            concert_url=data.get("concert_url"),
        )

    print(f"  Morning post ready: [{morning['type']}] topic='{morning['topic']}'")
    print(f"  {morning['text'][:80]}...\n")

    # ------------------------------------------------------------------
    # EVENING POST — YouTube commentary
    # ------------------------------------------------------------------
    print(f"  Finding YouTube video for topic: '{morning['topic']}'...")
    yt = gen_youtube(client, morning["topic"])

    if yt:
        evening = make_post(
            stamp, "evening", "video_youtube",
            yt["topic"], yt["text"],
            morning["image_query"],
            video_url=yt["video_url"],
        )
        print(f"  Evening post ready: YouTube — {yt['text'][:60]}...\n")
    else:
        # Fallback if YouTube API not configured
        evening = make_post(
            stamp, "evening", "evening_note",
            morning["topic"],
            f"¡Buenas noches a todos los fans del rock en español! 🎸 "
            f"¿Cuál fue su canción favorita de {morning['topic']} hoy?",
            morning["image_query"],
        )
        print(f"  Evening post ready: fallback note (no YouTube video found)\n")

    # ------------------------------------------------------------------
    # Merge with existing queue (keep pending posts from previous days)
    # ------------------------------------------------------------------
    existing      = load_queue()
    still_pending = [p for p in existing if p["status"] == "pending"]

    # Avoid duplicates — remove any posts already generated for today
    still_pending = [p for p in still_pending if stamp not in p["id"]]

    merged = still_pending + [morning, evening]
    save_queue(merged)

    print(f"  Saved 2 new posts. Total pending in queue: {len(merged)}")
    print(f"  Morning scheduled: {morning['scheduled_at']}")
    print(f"  Evening scheduled: {evening['scheduled_at']}")


if __name__ == "__main__":
    generate_posts()
