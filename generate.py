"""
generate.py
-----------
Generates ONE post per run and saves it to posts.json.
publish.py immediately publishes it.

Both scripts run together via GitHub Actions on the same schedule.
No time-based scheduling logic — generate creates, publish posts, done.

Post types rotate: original, poll, youtube, concert
All posts include: image query, hashtags, follow CTA, no time references
"""

from groq import Groq
from find_video import get_video_for_topic
from find_concert import get_concert_info
import json
import os
import random
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
POSTS_FILE   = "posts.json"
STATE_FILE   = "bot_state.json"

# ---------------------------------------------------------------------------
# Randomization pools
# ---------------------------------------------------------------------------

BANDS = [
    "Soda Stereo", "Heroes del Silencio", "Maná", "Café Tacvba",
    "Molotov", "Los Prisioneros", "Caifanes", "La Ley",
    "Los Fabulosos Cadillacs", "Divididos", "Bunbury", "Fito Páez",
    "Rata Blanca", "Intocable", "Jarabe de Palo", "Gustavo Cerati",
    "Enrique Bunbury", "Babasónicos", "Aterciopelados",
    "Enanitos Verdes", "Illya Kuryaki and the Valderramas",
    "Hombres G", "El Tri", "Maldita Vecindad", "Caifanes",
    "Santa Sabina", "Panteon Rococo", "Los de Abajo",
    "Bersuit Vergarabat", "Los Rodríguez",
]

POLL_TOPICS = [
    ("¿Cuál es la mejor banda de rock en español de todos los tiempos?",
     ["Soda Stereo", "Heroes del Silencio", "Maná"]),
    ("¿El mejor álbum del rock en español de los 90s?",
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
    ("¿El mejor concierto en vivo de la historia?",
     ["Soda Stereo Me Verás Volver", "Heroes del Silencio Parasiempre", "Maná en el Zócalo"]),
    ("¿La mejor canción de amor del rock en español?",
     ["Ella Usó Mi Cabeza - Soda Stereo", "Amor de Hombre - Hombres G", "Te Necesito - Maná"]),
    ("¿El mejor disco en vivo del rock en español?",
     ["Conmemorativo - Soda Stereo", "En Directo - Heroes del Silencio", "MTV Unplugged - Maná"]),
]

ORIGINAL_TYPES = [
    {"type": "debate",     "instruction": "Un DEBATE apasionante comparando dos bandas o épocas. Argumenta ambos lados y pide a los fans elegir."},
    {"type": "trivia",     "instruction": "TRIVIA con 2-3 datos sorprendentes y poco conocidos. Termina preguntando si lo sabían."},
    {"type": "historia",   "instruction": "HISTORIA de cómo se formó la banda o nació su álbum más icónico. Incluye detalles poco conocidos."},
    {"type": "ranking",    "instruction": "RANKING de los 3 mejores álbumes o canciones con una frase explicando cada elección. Pide el ranking del fan."},
    {"type": "recuerdo",   "instruction": "RECUERDO poderoso de un concierto mítico o gira legendaria. Invita a los fans a compartir el suyo."},
    {"type": "curiosidad", "instruction": "CURIOSIDAD impactante: colaboración inesperada, anécdota de grabación, hecho histórico que pocos conocen."},
]

# Post type rotation — cycles through all types evenly
POST_TYPE_ROTATION = ["original", "poll", "youtube", "original", "concert", "poll", "youtube", "original"]

# Band-specific image queries for Pexels
BAND_IMAGE_QUERIES = {
    "Soda Stereo":                      "Soda Stereo band Argentina rock",
    "Heroes del Silencio":              "Heroes del Silencio Spain rock band",
    "Maná":                             "Mana band Mexico rock concert",
    "Café Tacvba":                      "Cafe Tacvba Mexico alternative rock band",
    "Molotov":                          "Molotov Mexico punk rock band",
    "Los Prisioneros":                  "Los Prisioneros Chile rock band",
    "Caifanes":                         "Caifanes Mexico gothic rock concert",
    "La Ley":                           "La Ley Chile rock band concert",
    "Los Fabulosos Cadillacs":          "Los Fabulosos Cadillacs Argentina ska rock",
    "Divididos":                        "Divididos Argentina rock concert",
    "Bunbury":                          "Bunbury Spain rock singer concert",
    "Fito Páez":                        "Fito Paez Argentina rock piano",
    "Rata Blanca":                      "Rata Blanca Argentina heavy metal band",
    "Intocable":                        "Intocable Mexico norteño rock band",
    "Jarabe de Palo":                   "Jarabe de Palo Spain rock band",
    "Gustavo Cerati":                   "Gustavo Cerati guitarist Argentina",
    "Enrique Bunbury":                  "Enrique Bunbury Spain rock singer",
    "Babasónicos":                      "Babasónicos Argentina alternative rock",
    "Aterciopelados":                   "Aterciopelados Colombia rock band",
    "Enanitos Verdes":                  "Enanitos Verdes Argentina rock band",
    "Illya Kuryaki and the Valderramas": "hip hop rock latin band concert",
    "Hombres G":                        "Hombres G Spain pop rock band",
    "El Tri":                           "El Tri Mexico rock band concert",
    "Maldita Vecindad":                 "Maldita Vecindad Mexico ska punk band",
    "Santa Sabina":                     "Santa Sabina Mexico rock band",
    "Panteon Rococo":                   "Panteon Rococo Mexico ska band concert",
    "Los de Abajo":                     "Los de Abajo Mexico ska rock band",
    "Bersuit Vergarabat":               "Bersuit Vergarabat Argentina rock band",
    "Los Rodríguez":                    "Los Rodriguez Spain rock band",
}

DEFAULT_IMAGE = "latin rock concert band stage performance"

# ---------------------------------------------------------------------------
# Hashtag builder
# ---------------------------------------------------------------------------

def clean_tag(text):
    """Convert a band name or word into a clean hashtag."""
    return (text
        .replace(" ", "").replace("á","a").replace("é","e")
        .replace("í","i").replace("ó","o").replace("ú","u")
        .replace("ñ","n").replace("ü","u").replace("&","and")
        .replace(".","").replace(",","").replace("'","")
        .replace("-","").replace("(","").replace(")","")
    )


def build_hashtags(band, extra_tags=None, post_type="original"):
    """
    Build hashtag footer.
    "Lo Mejor del Rock en Español les presenta:" only appears on YouTube posts.
    All other posts just get hashtags + follow CTA.
    """
    band_tag  = clean_tag(band)
    core_tags = "#LoMejordelRockenEspañol #RockEnEspañol #RockLatino #RockEspañol"

    # Build band tags — main band first, then any extras
    band_tags = "#" + band_tag
    if extra_tags:
        for t in extra_tags[:3]:
            cleaned = clean_tag(t)
            if cleaned and cleaned.lower() != band_tag.lower():
                band_tags += " #" + cleaned

    if post_type == "youtube":
        footer = (
            "\n\n"
            "Lo Mejor del Rock en Español les presenta: " + band_tags + "\n\n"
            + core_tags + " " + band_tags + "\n\n"
            "🎸 Síguenos para más rock en español → @mejorrockespanol"
        )
    else:
        footer = (
            "\n\n"
            + core_tags + " " + band_tags + "\n\n"
            "🎸 Síguenos para más rock en español → @mejorrockespanol"
        )
    return footer

# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {
        "used_bands":          [],
        "used_poll_indices":   [],
        "original_type_index": 0,
        "post_type_index":     0,
        "total_posts":         0,
    }


def save_state(state):
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def pick_post_type(state):
    idx = state.get("post_type_index", 0) % len(POST_TYPE_ROTATION)
    state["post_type_index"] = idx + 1
    return POST_TYPE_ROTATION[idx]


def pick_band(state):
    used = state.get("used_bands", [])
    available = [b for b in BANDS if b not in used]
    if not available:
        available = BANDS
        state["used_bands"] = []
    band = random.choice(available)
    state["used_bands"] = (used + [band])[-10:]
    return band


def pick_poll(state):
    used = state.get("used_poll_indices", [])
    available = [i for i in range(len(POLL_TOPICS)) if i not in used]
    if not available:
        available = list(range(len(POLL_TOPICS)))
        state["used_poll_indices"] = []
    idx = random.choice(available)
    state["used_poll_indices"] = (used + [idx])[-8:]
    return POLL_TOPICS[idx]


def pick_original_type(state):
    idx = state.get("original_type_index", 0) % len(ORIGINAL_TYPES)
    state["original_type_index"] = idx + 1
    return ORIGINAL_TYPES[idx]


def get_image_query(band):
    return BAND_IMAGE_QUERIES.get(band, band + " rock band concert")

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

# ---------------------------------------------------------------------------
# Groq helper
# ---------------------------------------------------------------------------

def call_groq(client, system, user, max_tokens=1024, json_mode=True):
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


def clean_json(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())

# ---------------------------------------------------------------------------
# System prompts — no time references, no cross-post references
# ---------------------------------------------------------------------------

RULES_COMMON = """
REGLAS OBLIGATORIAS:
- Español natural y conversacional, tono de fan apasionado
- NUNCA menciones hora del día (no: "esta noche", "esta mañana", "hoy por la tarde")
- NUNCA hagas referencia a otros posts (no: "como dijimos antes", "en el post anterior")
- NUNCA copies letras de canciones
- Termina SIEMPRE con una pregunta directa que invite a comentar
- NO incluyas hashtags ni llamada a seguir — se agregan automáticamente al final
"""

SYSTEM_ORIGINAL = """Eres el creador apasionado de "Mejor Rock en Español" en Facebook.
""" + RULES_COMMON + """
- 150–220 palabras
- Datos específicos: fechas, nombres de álbumes, anécdotas reales

FORMATO: JSON puro, sin markdown.
{"type":"string","topic":"banda principal","text":"contenido","image_query":"nombre banda inglés + descriptor"}"""

SYSTEM_POLL = """Eres el creador de "Mejor Rock en Español" en Facebook.
""" + RULES_COMMON + """
Crea posts de votación usando reacciones como votos.

EMOJIS DE VOTO:
👍 = opción A
❤️ = opción B
😮 = opción C

- Contexto apasionante antes de las opciones (2-3 frases)
- Lista las 3 opciones con emojis y descripción breve
- Termina EXACTAMENTE con: "¡Vota con tu reacción! 👍❤️😮"
- 100–150 palabras total

FORMATO: JSON puro.
{"topic":"tema","text":"contenido","image_query":"banda específica inglés + band o concert"}"""

SYSTEM_YOUTUBE = """Eres el creador de "Mejor Rock en Español" en Facebook.
""" + RULES_COMMON + """
Escribe un comentario original para compartir un video de YouTube.

- Opina algo específico sobre la banda, álbum o era musical
- NO copies la descripción del video — escribe tu propia opinión
- NO incluyas el link en el texto — se agrega automáticamente
- Empieza directo con el contenido, sin saludos
- 120–180 palabras

FORMATO: JSON puro.
{"topic":"banda","text":"comentario","image_query":"banda inglés + concert live"}"""

SYSTEM_CONCERT = """Eres el creador de "Mejor Rock en Español" en Facebook.
""" + RULES_COMMON + """
Escribe un post emocionante sobre un concierto o evento próximo.

- Tono emocionado y urgente
- Incluye fecha, ciudad y artista prominentemente
- Termina con una pregunta ("¿Quién va?")
- NO incluyas links — van al final automáticamente
- 100–160 palabras

FORMATO: JSON puro.
{"topic":"artista","text":"contenido","image_query":"artista inglés + concert live"}"""

# ---------------------------------------------------------------------------
# Content generators
# ---------------------------------------------------------------------------

def gen_original(client, state, band):
    chosen      = pick_original_type(state)
    image_query = get_image_query(band)
    prompt = (
        "Genera un post sobre: " + band + "\n"
        "Tipo: " + chosen["type"].upper() + "\n"
        "Instrucción: " + chosen["instruction"] + "\n\n"
        "image_query DEBE SER: '" + image_query + "'\n"
        "Menciona " + band + " específicamente con datos reales.\n\n"
        "Responde ÚNICAMENTE con JSON válido."
    )
    data = clean_json(call_groq(client, SYSTEM_ORIGINAL, prompt))
    if "posts" in data:
        data = data["posts"][0]
    data["image_query"] = image_query
    data["topic"]       = band
    data["post_type"]   = "original"
    return data


def gen_poll(client, state, band):
    question, options = pick_poll(state)
    image_query = get_image_query(band)
    prompt = (
        "Crea un post de votación para: '" + question + "'\n\n"
        "Opciones:\n"
        "👍 " + options[0] + "\n"
        "❤️ " + options[1] + "\n"
        "😮 " + options[2] + "\n\n"
        "Añade contexto apasionante antes de las opciones.\n"
        "Termina EXACTAMENTE con: '¡Vota con tu reacción! 👍❤️😮'\n"
        "image_query: '" + image_query + "'\n\n"
        "Responde ÚNICAMENTE con JSON válido."
    )
    data = clean_json(call_groq(client, SYSTEM_POLL, prompt, max_tokens=600))
    data["image_query"] = image_query
    data["topic"]       = band
    data["post_type"]   = "poll"
    return data


def gen_youtube(client, band):
    video = get_video_for_topic(band, [])
    if not video:
        return None
    image_query = get_image_query(band)
    prompt = (
        "Video de YouTube:\n"
        "  Título: " + video["title"] + "\n"
        "  Canal: " + video["channel"] + "\n"
        "  Descripción: " + video["description"] + "\n\n"
        "Banda: " + band + "\n\n"
        "Escribe el comentario. NO incluyas el link.\n"
        "image_query: '" + image_query + "'\n\n"
        "Responde ÚNICAMENTE con JSON válido."
    )
    data = clean_json(call_groq(client, SYSTEM_YOUTUBE, prompt, max_tokens=600))
    data["image_query"] = image_query
    data["topic"]       = band
    data["post_type"]   = "youtube"
    data["video_url"]   = video["url"]
    # Append YouTube URL to text
    data["text"]        = data["text"] + "\n\n" + video["url"]
    return data


def gen_concert(client, band):
    concert     = get_concert_info()
    image_query = get_image_query(band)

    if concert:
        prompt = (
            "Concierto próximo:\n"
            "  Artista: " + concert["name"] + "\n"
            "  Fecha: " + concert["date"] + "\n"
            "  Ciudad: " + concert["city"] + ", " + concert["country"] + "\n\n"
            "Escribe el post. NO incluyas links.\n"
            "image_query: '" + image_query + "'\n\n"
            "Responde ÚNICAMENTE con JSON válido."
        )
        concert_url = concert["url"]
        topic       = concert.get("artist", band)
        image_query = get_image_query(topic) if topic in BAND_IMAGE_QUERIES else image_query
    else:
        prompt = (
            "Escribe un post animando a los fans a ver conciertos de rock en español en vivo. "
            "Menciona Ticketmaster, Vivid Seats y StubHub.\n"
            "image_query: 'rock concert latinamerica crowd stage'\n\n"
            "Responde ÚNICAMENTE con JSON válido."
        )
        concert_url = "https://www.vividseats.com/concerts"
        topic       = band
        image_query = "rock concert latinamerica crowd stage"

    data = clean_json(call_groq(client, SYSTEM_CONCERT, prompt, max_tokens=600))
    data["image_query"] = image_query
    data["topic"]       = topic
    data["post_type"]   = "concert"
    data["concert_url"] = concert_url
    # Append concert URL to text
    data["text"]        = data["text"] + "\n\n🎟️ Boletos: " + concert_url
    return data

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate_post():
    now    = datetime.now(timezone.utc)
    stamp  = now.strftime("%Y%m%d_%H%M%S")
    state  = load_state()
    client = Groq(api_key=GROQ_API_KEY)

    post_type = pick_post_type(state)
    band      = pick_band(state)

    print("[" + now.isoformat() + "] Generating ONE post...")
    print("  Post type : " + post_type)
    print("  Band/topic: " + band)

    # Generate content
    if post_type == "original":
        data = gen_original(client, state, band)
    elif post_type == "poll":
        data = gen_poll(client, state, band)
    elif post_type == "youtube":
        data = gen_youtube(client, band)
        if not data:
            print("  YouTube video not found — falling back to original")
            data = gen_original(client, state, band)
    elif post_type == "concert":
        data = gen_concert(client, band)

    # Extract any other band names mentioned in the post text
    # so we can include them as additional hashtags
    text_so_far = data.get("text", "")
    extra_tags  = [b for b in BANDS if b != band and b in text_so_far]

    # Append hashtags + follow CTA to every post
    # "Lo Mejor del Rock en Español les presenta:" only on YouTube posts
    actual_post_type = data.get("post_type", post_type)
    hashtags         = build_hashtags(data.get("topic", band), extra_tags=extra_tags, post_type=actual_post_type)
    data["text"]     = data["text"].rstrip() + hashtags

    # Collect all bands/artists mentioned in the text for image matching
    text_so_far  = data.get("text", "")
    all_mentions = [b for b in BANDS if b in text_so_far and b != data.get("topic", band)]

    # Build the queue entry
    entry = {
        "id":           "post_" + stamp,
        "status":       "pending",
        "created_at":   now.isoformat(),
        "post_type":    data.get("post_type", post_type),
        "topic":        data.get("topic", band),
        "text":         data["text"],
        "image_query":  data.get("image_query", get_image_query(band)),
        "extra_topics": all_mentions[:4],   # up to 4 extra bands for image matching
        "video_url":    data.get("video_url"),
        "concert_url":  data.get("concert_url"),
        "fb_post_id":   None,
        "ig_post_id":   None,
        "published_at": None,
        "error":        None,
    }

    # Add to queue (keep last 50 for history)
    queue = load_queue()
    queue.append(entry)
    queue = queue[-50:]
    save_queue(queue)
    save_state(state)

    state["total_posts"] = state.get("total_posts", 0) + 1
    save_state(state)

    print("  Topic    : " + entry["topic"])
    print("  Image    : " + entry["image_query"])
    print("  Text     : " + entry["text"][:100] + "...")
    print("  Saved to posts.json as: " + entry["id"])


if __name__ == "__main__":
    generate_post()
