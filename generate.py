"""
generate.py
-----------
Generates 2 posts for TODAY:
  Morning (11am EST) — Poll / Original / Concert depending on weekday
  Evening  (7pm EST) — YouTube commentary every day

Key improvements:
  - Fully randomized band/topic selection (no repeats within the week)
  - Every post guaranteed to have a specific image query
  - Poll topics rotate without repeating for 12 weeks
  - Original posts cycle all 6 types before repeating
"""

from groq import Groq
from find_video import get_video_for_topic
from find_concert import get_concert_info
import json
import os
import random
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
POSTS_FILE   = "posts.json"
STATE_FILE   = "bot_state.json"   # tracks rotation state across days

MORNING_UTC = 16   # 11am EST
EVENING_UTC = 0    # 7pm EST (midnight UTC next calendar day)

# Day → morning post type
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
# Randomization pools — large and varied
# ---------------------------------------------------------------------------

BANDS = [
    "Soda Stereo", "Heroes del Silencio", "Maná", "Café Tacvba",
    "Molotov", "Los Prisioneros", "Caifanes", "La Ley",
    "Los Fabulosos Cadillacs", "Divididos", "Bunbury", "Fito Páez",
    "Rata Blanca", "Intocable", "Jarabe de Palo", "Gustavo Cerati",
    "Enrique Bunbury", "Bersuit Vergarabat", "Aterciopelados",
    "Babasónicos", "Illya Kuryaki and the Valderramas", "Enanitos Verdes",
    "Los Rodríguez", "Hombres G", "Mecano", "El Tri", "Panteon Rococo",
    "Santa Sabina", "Maldita Vecindad", "Los de Abajo",
]

ERAS = [
    "los 80s", "los 90s", "los 2000s", "la época dorada",
    "el rock alternativo latino", "el rock argentino clásico",
    "el rock mexicano clásico", "el rock español clásico",
]

POLL_TOPICS = [
    ("¿Cuál es la mejor banda de rock en español de todos los tiempos?",
     ["Soda Stereo", "Heroes del Silencio", "Maná"]),
    ("¿El mejor álbum de los 90s?",
     ["Dynamo - Soda Stereo", "Re - Café Tacvba", "Donde Jugaran los Niños - Maná"]),
    ("¿La mejor banda de rock mexicano?",
     ["Café Tacvba", "Molotov", "Caifanes"]),
    ("¿El mejor vocalista del rock en español?",
     ["Gustavo Cerati", "Enrique Bunbury", "Fito Páez"]),
    ("¿La mejor época del rock en español?",
     ["Los 80s clásicos", "Los 90s dorados", "Los 2000s alternativos"]),
    ("¿El mejor guitarrista del rock en español?",
     ["Zeta Bosio - Soda Stereo", "Iñaki Uoho - Heroes del Silencio", "Quique Rangel - Café Tacvba"]),
    ("¿El álbum más influyente de todos los tiempos?",
     ["Doble Vida - Soda Stereo", "El Espíritu del Vino - Heroes", "Donde Jugaran los Niños - Maná"]),
    ("¿Rock argentino o rock mexicano?",
     ["Rock argentino siempre", "Rock mexicano para siempre", "¡Los dos son iguales!"]),
    ("¿La canción perfecta del rock en español?",
     ["De Música Ligera - Soda Stereo", "Entre Dos Tierras - Heroes del Silencio", "Oye Mi Amor - Maná"]),
    ("¿El mejor festival de rock en español?",
     ["Vive Latino", "Lollapalooza LatAm", "Festival Estéreo Picnic"]),
    ("¿La mejor colaboración del rock en español?",
     ["Cerati y Spinetta", "Maná y Santana", "Bunbury y Los Tigres del Norte"]),
    ("¿La mejor intro de guitarra del rock en español?",
     ["De Música Ligera - Cerati", "La Chispa Adecuada - Divididos", "Matador - Los Fabulosos Cadillacs"]),
    ("¿Qué define más a una banda de rock?",
     ["Las letras y el mensaje", "El sonido y la música", "La energía en vivo"]),
    ("¿El mejor bajo del rock en español?",
     ["Zeta Bosio - Soda Stereo", "Juan Alderete - Racer X", "Flavio Cianciarulo - Los Fabulosos"]),
    ("¿El mejor concierto en vivo de la historia?",
     ["Soda Stereo Me Verás Volver", "Heroes del Silencio Parasiempre", "Maná en el Zócalo"]),
    ("¿La mejor canción de amor del rock en español?",
     ["Ella Usó Mi Cabeza - Soda Stereo", "Amor de Hombre - Hombres G", "Te Necesito - Maná"]),
]

ORIGINAL_TYPES = [
    {
        "type": "debate",
        "instruction": "Un DEBATE apasionante comparando dos bandas, épocas o estilos del rock en español. Argumenta ambos lados y pide a los fans que elijan."
    },
    {
        "type": "trivia",
        "instruction": "Una TRIVIA impactante con 2-3 datos poco conocidos sobre la banda o tema. Termina preguntando si lo sabían."
    },
    {
        "type": "historia",
        "instruction": "La HISTORIA BREVE y apasionante de cómo se formó la banda o cómo nació su álbum más icónico. Incluye detalles poco conocidos."
    },
    {
        "type": "ranking",
        "instruction": "Un RANKING personal de los 3 mejores álbumes o canciones, con una frase explicando cada elección. Pide al fan su propio ranking."
    },
    {
        "type": "recuerdo",
        "instruction": "Evoca un RECUERDO poderoso: un concierto mítico, el día que salió un álbum, o la primera vez que escuchaste a esta banda. Invita a los fans a compartir el suyo."
    },
    {
        "type": "curiosidad",
        "instruction": "Una CURIOSIDAD que sorprenda: una colaboración inesperada, un dato de grabación, una anécdota histórica que pocos fans conocen."
    },
]

# Specific image queries per band — ensures relevant images
BAND_IMAGE_QUERIES = {
    "Soda Stereo":        "Soda Stereo band Argentina rock",
    "Heroes del Silencio": "Heroes del Silencio Spain rock band",
    "Maná":               "Mana band Mexico rock concert",
    "Café Tacvba":        "Cafe Tacvba Mexico alternative rock",
    "Molotov":            "Molotov Mexico punk rock band",
    "Los Prisioneros":    "Los Prisioneros Chile rock band",
    "Caifanes":           "Caifanes Mexico gothic rock",
    "La Ley":             "La Ley Chile rock band",
    "Los Fabulosos Cadillacs": "Los Fabulosos Cadillacs Argentina ska",
    "Divididos":          "Divididos Argentina rock concert",
    "Bunbury":            "Bunbury Spain rock singer concert",
    "Fito Páez":          "Fito Paez Argentina rock singer",
    "Rata Blanca":        "Rata Blanca Argentina heavy metal",
    "Intocable":          "Intocable Mexico norteño rock",
    "Gustavo Cerati":     "Gustavo Cerati guitarist Argentina",
    "Enrique Bunbury":    "Enrique Bunbury singer Spain rock",
    "Babasónicos":        "Babasónicos Argentina alternative rock",
    "Aterciopelados":     "Aterciopelados Colombia rock band",
    "Enanitos Verdes":    "Enanitos Verdes Argentina rock",
    "El Tri":             "El Tri Mexico rock band",
    "Maldita Vecindad":   "Maldita Vecindad Mexico ska punk",
    "Hombres G":          "Hombres G Spain pop rock band",
}

DEFAULT_IMAGE_QUERY = "latin rock concert band stage"

# ---------------------------------------------------------------------------
# State management — tracks what was used recently to avoid repeats
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {
        "used_bands":       [],
        "used_poll_indices": [],
        "original_type_index": 0,
        "last_updated":     "",
    }


def save_state(state: dict):
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def pick_band(state: dict) -> str:
    """Pick a band not used in the last 7 days."""
    used = state.get("used_bands", [])
    available = [b for b in BANDS if b not in used]
    if not available:
        available = BANDS
        state["used_bands"] = []
    band = random.choice(available)
    state["used_bands"] = (used + [band])[-7:]  # keep last 7
    return band


def pick_poll(state: dict) -> tuple:
    """Pick a poll topic not recently used."""
    used = state.get("used_poll_indices", [])
    available = [i for i in range(len(POLL_TOPICS)) if i not in used]
    if not available:
        available = list(range(len(POLL_TOPICS)))
        state["used_poll_indices"] = []
    idx = random.choice(available)
    state["used_poll_indices"] = (used + [idx])[-8:]
    return POLL_TOPICS[idx]


def pick_original_type(state: dict) -> dict:
    """Cycle through all 6 original types before repeating."""
    idx = state.get("original_type_index", 0) % len(ORIGINAL_TYPES)
    state["original_type_index"] = idx + 1
    return ORIGINAL_TYPES[idx]


def get_image_query(band: str, fallback: str = "") -> str:
    """Return a specific image query for the band, or a descriptive fallback."""
    if band in BAND_IMAGE_QUERIES:
        return BAND_IMAGE_QUERIES[band]
    if fallback:
        return fallback
    return f"{band} rock band concert"

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


def today_schedule(hour_utc: int) -> str:
    now  = datetime.now(timezone.utc)
    slot = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
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
        model       = "llama-3.3-70b-versatile",
        messages    = [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        temperature = 0.9,
        max_tokens  = max_tokens,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    return client.chat.completions.create(**kwargs).choices[0].message.content


def clean_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

SYSTEM_ORIGINAL = """Eres el creador apasionado de "Mejor Rock en Español" en Facebook.
REGLAS:
- Español natural y conversacional, tono de fan experto
- Termina SIEMPRE con una pregunta directa que invite a comentar
- NUNCA copies letras de canciones
- 150–220 palabras — posts más largos generan más engagement
- Datos específicos: fechas, nombres de álbumes, anécdotas reales

FORMATO: JSON puro, sin markdown.
{"type":"string","topic":"banda principal","text":"contenido completo","image_query":"nombre banda en inglés + descriptor específico"}"""

SYSTEM_POLL = """Eres el creador de "Mejor Rock en Español" en Facebook.
Crea posts de votación usando reacciones de Facebook como votos.

FORMATO DE VOTO — usa EXACTAMENTE estos emojis con sus opciones:
👍 = opción A
❤️ = opción B  
😮 = opción C

REGLAS:
- Contexto apasionante antes de las opciones (2-3 frases)
- Lista las 3 opciones claramente con los emojis
- Termina EXACTAMENTE con: "¡Vota con tu reacción! 👍❤️😮"
- 100–150 palabras total
- NUNCA copies letras de canciones

FORMATO: JSON puro.
{"topic":"tema","text":"contenido completo","image_query":"banda específica en inglés + band o concert"}"""

SYSTEM_CONCERT = """Eres el creador de "Mejor Rock en Español" en Facebook.
Escribe un post emocionante sobre un concierto o evento próximo.
REGLAS:
- Tono emocionado y urgente, como si fuera la mejor noticia del año
- Incluye fecha, ciudad y artista prominentemente
- Termina con "¡Consigue tus boletos!" y una pregunta ("¿Quién va?")
- NO incluyas links en el texto — van al final automáticamente
- 100–160 palabras

FORMATO: JSON puro.
{"topic":"artista","text":"contenido","image_query":"artista en inglés + concert live performance"}"""

SYSTEM_YOUTUBE = """Eres el creador de "Mejor Rock en Español" en Facebook.
Escribe un comentario original para compartir un video esta noche.
REGLAS:
- Empieza con: "🎸 Para cerrar el día..." o "Esta noche les traigo..." o "Los dejo con este clásico..."
- Conecta el video con el tema de la mañana
- Opina algo específico sobre la banda, álbum o era
- NO copies la descripción del video
- NO incluyas el link — va al final
- Termina con una pregunta
- 120–180 palabras
- NUNCA copies letras"""

# ---------------------------------------------------------------------------
# Content generators
# ---------------------------------------------------------------------------

def gen_poll(client: Groq, state: dict) -> dict:
    question, options = pick_poll(state)
    band = options[0].split(" - ")[-1] if " - " in options[0] else options[0]
    image_query = get_image_query(band, f"{band} rock band")

    prompt = (
        f"Crea un post de votación apasionante para esta pregunta:\n"
        f"'{question}'\n\n"
        f"Opciones:\n"
        f"👍 {options[0]}\n"
        f"❤️ {options[1]}\n"
        f"😮 {options[2]}\n\n"
        f"Añade contexto emocionante antes de las opciones. "
        f"Termina EXACTAMENTE con: '¡Vota con tu reacción! 👍❤️😮'\n\n"
        f"image_query debe ser: '{image_query}'\n\n"
        f"Responde ÚNICAMENTE con JSON válido."
    )
    data = clean_json(call_groq(client, SYSTEM_POLL, prompt, max_tokens=600))
    data["image_query"] = image_query  # enforce specific query
    return data


def gen_original(client: Groq, state: dict, band: str) -> dict:
    chosen      = pick_original_type(state)
    image_query = get_image_query(band)

    prompt = (
        f"Genera un post sobre: {band}\n"
        f"Tipo: {chosen['type'].upper()}\n"
        f"Instrucción: {chosen['instruction']}\n\n"
        f"IMPORTANTE:\n"
        f"- image_query DEBE SER: '{image_query}'\n"
        f"- Menciona {band} específicamente\n"
        f"- Incluye datos reales: álbumes, años, nombres de canciones\n\n"
        f"Responde ÚNICAMENTE con JSON válido."
    )
    data = clean_json(call_groq(client, SYSTEM_ORIGINAL, prompt, max_tokens=1024))
    if "posts" in data:
        data = data["posts"][0]
    data["image_query"] = image_query  # always enforce
    data["topic"]       = band
    return data


def gen_concert(client: Groq, band: str) -> dict:
    concert     = get_concert_info()
    image_query = get_image_query(band, "rock concert latinamerica live")

    if concert:
        prompt = (
            f"Concierto próximo:\n"
            f"  Artista: {concert['name']}\n"
            f"  Fecha: {concert['date']}\n"
            f"  Ciudad: {concert['city']}, {concert['country']}\n\n"
            f"Escribe el post de anuncio. NO incluyas links.\n"
            f"image_query: '{get_image_query(concert['artist'], image_query)}'\n\n"
            f"Responde ÚNICAMENTE con JSON válido."
        )
        concert_url = concert["url"]
        topic       = concert["artist"]
        image_query = get_image_query(concert["artist"], image_query)
    else:
        prompt = (
            f"Escribe un post animando a los fans a ver conciertos de rock en español en vivo. "
            f"Menciona Ticketmaster, Vivid Seats y StubHub. "
            f"image_query: 'rock concert latinamerica crowd stage'\n\n"
            f"Responde ÚNICAMENTE con JSON válido."
        )
        concert_url = "https://www.vividseats.com/concerts"
        topic       = "conciertos rock en español"
        image_query = "rock concert latinamerica crowd stage"

    data = clean_json(call_groq(client, SYSTEM_CONCERT, prompt, max_tokens=600))
    data["concert_url"] = concert_url
    data["topic"]       = topic
    data["image_query"] = image_query
    return data


def gen_youtube(client: Groq, band: str) -> dict | None:
    video = get_video_for_topic(band, [])
    if not video:
        return None

    prompt = (
        f"Video de YouTube:\n"
        f"  Título: {video['title']}\n"
        f"  Canal: {video['channel']}\n"
        f"  Descripción: {video['description']}\n\n"
        f"El post de esta mañana fue sobre: {band}\n\n"
        f"Escribe el comentario de esta noche. NO incluyas el link."
    )
    commentary = call_groq(
        client, SYSTEM_YOUTUBE, prompt,
        max_tokens=600, json_mode=False
    ).strip()

    return {
        "text":      f"{commentary}\n\n{video['url']}",
        "video_url": video["url"],
        "topic":     band,
    }

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate_posts():
    now      = datetime.now(timezone.utc)
    weekday  = now.weekday()
    stamp    = now.strftime("%Y%m%d")
    day_name = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][weekday]

    print(f"[{now.isoformat()}] Generating posts for {day_name}...")

    state        = load_state()
    client       = Groq(api_key=GROQ_API_KEY)
    morning_type = MORNING_TYPES[weekday]
    band         = pick_band(state)

    print(f"  Today's band/topic: {band}")
    print(f"  Morning type: {morning_type}\n")

    # ── Morning post ──────────────────────────────────────────────────────
    if morning_type == "poll":
        data    = gen_poll(client, state)
        topic   = data.get("topic", band)
        morning = make_post(
            stamp, "morning", "poll", topic,
            data["text"],
            data.get("image_query", get_image_query(band)),
        )

    elif morning_type == "original":
        data    = gen_original(client, state, band)
        topic   = data.get("topic", band)
        morning = make_post(
            stamp, "morning", data.get("type", "original"), topic,
            data["text"],
            data.get("image_query", get_image_query(band)),
        )

    elif morning_type == "concert":
        data    = gen_concert(client, band)
        topic   = data.get("topic", band)
        morning = make_post(
            stamp, "morning", "concert", topic,
            data["text"] + f"\n\n{data['concert_url']}",
            data.get("image_query", get_image_query(band)),
            concert_url=data.get("concert_url"),
        )

    print(f"  Morning ready: [{morning['type']}] {morning['topic']}")
    print(f"  Image query:   {morning['image_query']}")
    print(f"  Text preview:  {morning['text'][:80]}...\n")

    # ── Evening post — YouTube ────────────────────────────────────────────
    print(f"  Finding YouTube video for: {band}...")
    yt = gen_youtube(client, band)

    if yt:
        evening = make_post(
            stamp, "evening", "video_youtube",
            yt["topic"], yt["text"],
            get_image_query(band),   # topic-matched image even for YouTube posts
            video_url=yt["video_url"],
        )
        print(f"  Evening ready: YouTube — {yt['text'][:60]}...")
    else:
        evening = make_post(
            stamp, "evening", "evening_note",
            band,
            f"🎸 Buenas noches a todos los fans del rock en español!\n\n"
            f"¿Cuál es su canción favorita de {band} para terminar el día?",
            get_image_query(band),
        )
        print(f"  Evening ready: fallback note (no YouTube video found)")

    print(f"  Image query:   {evening['image_query']}\n")

    # ── Merge and save ────────────────────────────────────────────────────
    existing      = load_queue()
    still_pending = [p for p in existing if p["status"] == "pending"
                     and stamp not in p["id"]]
    merged        = still_pending + [morning, evening]
    save_queue(merged)
    save_state(state)

    print(f"  Saved to queue. Total pending: {len(merged)}")
    print(f"  Morning: {morning['scheduled_at']}")
    print(f"  Evening: {evening['scheduled_at']}")


if __name__ == "__main__":
    generate_posts()
