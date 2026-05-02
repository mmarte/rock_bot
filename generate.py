"""
generate.py
-----------
Generates ONE post per run. Saves to posts.json. publish.py posts it immediately.

Key improvements:
  - 60+ bands (was 30) — much more variety
  - "Un día como hoy" historical post type
  - 7 post type rotation including "hoy_en_historia"
  - Band exclusion window = 20 posts (was 10) — no repeats for weeks
  - Groq writes accurate historical facts with specific dates/events
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
UNIVERSE_FILE = "band_universe.json"
CURATED_TOP40_FILE = "curated_top40_by_year.json"

try:
    from band_universe import get_band_universe
except Exception:
    get_band_universe = None


_CURATED_TOP40_CACHE = None


def load_curated_top40(path: str = CURATED_TOP40_FILE) -> dict | None:
    """
    Load curated top-40-by-year list (1976–2025).
    Returns dict payload or None if unavailable.
    """
    global _CURATED_TOP40_CACHE
    if _CURATED_TOP40_CACHE is not None:
        return _CURATED_TOP40_CACHE
    if not os.path.exists(path):
        _CURATED_TOP40_CACHE = None
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "top40_by_year" not in data:
            _CURATED_TOP40_CACHE = None
            return None
        _CURATED_TOP40_CACHE = data
        return data
    except Exception:
        _CURATED_TOP40_CACHE = None
        return None


def load_top10_bands(curated: dict | None = None) -> list[str]:
    curated = curated or load_curated_top40()
    if not curated:
        return []
    by_year = curated.get("top40_by_year") or {}
    if not isinstance(by_year, dict):
        return []
    top10 = set()
    for year_list in by_year.values():
        if isinstance(year_list, list):
            for band in year_list[:10]:
                top10.add(band)
    return sorted(top10)

# ---------------------------------------------------------------------------
# Proven rock en español artists — focus on those with top-10 presence in the last 50 years
# ---------------------------------------------------------------------------
FAMOUS_FALLBACK_BANDS = [
    "Soda Stereo", "Maná", "Café Tacvba", "Caifanes", "Héroes del Silencio",
    "Los Fabulosos Cadillacs", "Molotov", "La Ley", "Enrique Bunbury",
    "Divididos", "Los Prisioneros", "Fito Páez", "Charly García",
    "Gustavo Cerati", "Aterciopelados", "Juanes", "Attaque 77",
    "La Renga", "Radio Futura", "Mecano", "Hombres G",
    "Los Rodríguez", "Babasónicos", "Andrés Calamaro", "El Tri",
    "Rata Blanca", "Los Piojos", "Los Auténticos Decadentes",
    "Cuca", "Zoé", "Panteon Rococo", "Santa Sabina",
]

BANDS = FAMOUS_FALLBACK_BANDS[:]

# ---------------------------------------------------------------------------
# Historical events for "Un día como hoy" posts
# Format: (month, day, year, band, event_description)
# ---------------------------------------------------------------------------

HISTORICAL_EVENTS = [
    # January
    (1, 14, 1985, "Soda Stereo", "lanzó su segundo álbum 'Nada Personal', uno de los discos más influyentes del rock argentino"),
    (1, 26, 1967, "Charly García", "nació en Buenos Aires, Argentina, uno de los músicos más influyentes del rock en español"),

    # February
    (2, 11, 1991, "Heroes del Silencio", "publicó 'El Mar No Cesa', el álbum que los catapultó a la fama en toda España y Latinoamérica"),
    (2, 23, 1964, "Gustavo Cerati", "nació en Buenos Aires, Argentina, el guitarrista y vocalista que revolucionó el rock en español"),

    # March
    (3, 7, 1987, "Caifanes", "se formó oficialmente en Ciudad de México, dando inicio a una de las bandas más importantes del rock mexicano"),
    (3, 18, 1992, "Café Tacvba", "lanzó 'Re', el álbum que redefinió el rock alternativo latinoamericano"),
    (3, 21, 1988, "Los Prisioneros", "publicó 'La Cultura de la Basura', consolidándose como la banda más importante del rock chileno"),

    # April
    (4, 3, 1982, "Soda Stereo", "dio su primer concierto oficial en Buenos Aires, marcando el inicio de una era"),
    (4, 19, 1969, "Luis Alberto Spinetta", "lanzó 'Almendra', el disco que fundó el rock argentino tal como lo conocemos"),
    (4, 27, 1992, "Maná", "lanzó 'Donde Jugaran Los Niños', el álbum que los convirtió en la banda de rock en español más vendida de la historia"),

    # May
    (5, 16, 1959, "Victor Jara", "nació en Chile, el músico y poeta que inspiró generaciones de artistas latinoamericanos"),
    (5, 13, 1963, "Fito Páez", "nació en Rosario, Argentina, el pianista y compositor que redefinió el rock argentino"),
    (5, 25, 1994, "Heroes del Silencio", "publicó 'El Espíritu del Vino', su obra maestra y el álbum que los llevó a la cima del rock en español"),

    # June
    (6, 14, 1987, "Enanitos Verdes", "lanzó 'Habitación Disponible', el álbum con sus mayores éxitos incluyendo 'Lamento Boliviano'"),
    (6, 20, 1993, "Molotov", "se formó en Ciudad de México, preparando la explosión más irreverente del rock mexicano"),
    (6, 11, 1967, "Enrique Bunbury", "nació en Zaragoza, España, el vocalista que lideraría Heroes del Silencio"),

    # July
    (7, 11, 1987, "Los Fabulosos Cadillacs", "lanzó su álbum debut, fusionando ska, rock y cumbia de manera única"),
    (7, 19, 1964, "Heroes del Silencio", "el baterista Pedro Andreu nació en Zaragoza, España"),
    (7, 23, 1990, "Soda Stereo", "publicó 'Canción Animal', considerado por muchos el mejor álbum del rock en español"),

    # August
    (8, 1, 2010, "Gustavo Cerati", "sufrió un ACV en Caracas que lo dejaría en coma durante cuatro años, dejando al mundo del rock en shock"),
    (8, 19, 1981, "Soda Stereo", "se formó oficialmente en Buenos Aires con Gustavo Cerati, Zeta Bosio y Charly Alberti"),
    (8, 25, 1995, "Bunbury", "lanzó su primer álbum solista 'Radical Sonora' tras la separación de Heroes del Silencio"),

    # September
    (9, 2, 1996, "Heroes del Silencio", "anunció su separación oficial, dejando a millones de fans devastados en todo el mundo"),
    (9, 11, 1966, "Maná", "el vocalista Fher Olvera nació en Guadalajara, México"),
    (9, 20, 2014, "Gustavo Cerati", "falleció en Buenos Aires a los 55 años, dejando un legado inmortal en el rock en español"),

    # October
    (10, 5, 1984, "Caifanes", "lanzó su primer sencillo, iniciando la era oscura y brillante del rock mexicano"),
    (10, 16, 1987, "Soda Stereo", "publicó 'Signos', el álbum que los estableció como la banda más importante del rock en español"),
    (10, 20, 2007, "Soda Stereo", "reunió a 250,000 personas en el concierto 'Me Verás Volver' en Buenos Aires, uno de los eventos más grandes de la historia del rock latinoamericano"),

    # November
    (11, 4, 1991, "Maná", "publicó 'Falta Amor', el álbum que los lanzó a la fama internacional"),
    (11, 9, 1989, "Los Rodríguez", "se formó en Madrid, uniendo el rock argentino de Andrés Calamaro con el español"),
    (11, 25, 1992, "Heroes del Silencio", "dio su concierto más multitudinario hasta la fecha, llenando el Palacio de los Deportes de Madrid"),

    # December
    (12, 1, 1996, "Café Tacvba", "lanzó 'Avalancha de Éxitos', un álbum de versiones que demostró su versatilidad sin límites"),
    (12, 6, 1977, "Los Prisioneros", "el vocalista Jorge González nació en Santiago de Chile"),
    (12, 20, 1997, "Divididos", "publicó 'Corazón Americano', consolidándose como una de las bandas más respetadas del rock argentino"),
]

# ---------------------------------------------------------------------------
# Poll topics — expanded with more variety
# ---------------------------------------------------------------------------

POLL_TOPICS = [
    ("¿Cuál es la mejor banda de rock en español de todos los tiempos?",
     ["Soda Stereo", "Heroes del Silencio", "Maná"]),
    ("¿El mejor álbum del rock en español de los 90s?",
     ["Canción Animal - Soda Stereo", "Re - Café Tacvba", "El Espíritu del Vino - Heroes del Silencio"]),
    ("¿La mejor banda de rock mexicano?",
     ["Café Tacvba", "Molotov", "Caifanes"]),
    ("¿El mejor vocalista del rock en español?",
     ["Gustavo Cerati", "Enrique Bunbury", "Fito Páez"]),
    ("¿La mejor época del rock en español?",
     ["Los 80s clásicos", "Los 90s dorados", "Los 2000s alternativos"]),
    ("¿El mejor guitarrista del rock en español?",
     ["Gustavo Cerati - Soda Stereo", "Iñaki Uoho - Heroes del Silencio", "Tweety González"]),
    ("¿El álbum más influyente de todos los tiempos?",
     ["Canción Animal - Soda Stereo", "El Espíritu del Vino - Heroes del Silencio", "Donde Jugaran los Niños - Maná"]),
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
    ("¿El mejor disco en vivo del rock en español?",
     ["Me Verás Volver - Soda Stereo", "En Directo - Heroes del Silencio", "MTV Unplugged - Maná"]),
    ("¿La banda que mejor evolucionó con el tiempo?",
     ["Café Tacvba", "Los Fabulosos Cadillacs", "Maná"]),
    ("¿El mejor bajo del rock en español?",
     ["Zeta Bosio - Soda Stereo", "Flavio Cianciarulo - Los Fabulosos Cadillacs", "Juan Alderete"]),
    ("¿La mejor canción de amor del rock en español?",
     ["Ella Usó Mi Cabeza - Soda Stereo", "De Música Ligera - Soda Stereo", "Te Necesito - Maná"]),
    ("¿Cuál fue el mejor año del rock en español?",
     ["1990 - Canción Animal", "1995 - El Espíritu del Vino", "1992 - Re"]),
    ("¿El mejor rock chileno?",
     ["Los Prisioneros", "La Ley", "Los Tres"]),
    ("¿La mejor banda de rock colombiano?",
     ["Aterciopelados", "Juanes", "Bomba Estéreo"]),
    ("¿El mejor solista surgido del rock en español?",
     ["Gustavo Cerati", "Enrique Bunbury", "Andrés Calamaro"]),
]

# ---------------------------------------------------------------------------
# Original post types — expanded
# ---------------------------------------------------------------------------

ORIGINAL_TYPES = [
    {"type": "debate",
     "instruction": "DEBATE apasionante entre dos bandas, épocas o estilos. Presenta ambos lados con argumentos concretos y pide a los fans elegir. Menciona álbumes y canciones específicas."},
    {"type": "trivia",
     "instruction": "TRIVIA con 3 datos sorprendentes y verificables sobre la banda. Deben ser datos reales — fechas de grabación, anécdotas de estudio, colaboraciones reales. Termina preguntando cuál dato los sorprendió más."},
    {"type": "historia",
     "instruction": "HISTORIA detallada de cómo se formó la banda o cómo nació un álbum específico. Incluye el año, la ciudad, los nombres reales de los integrantes y un hecho poco conocido del proceso."},
    {"type": "ranking",
     "instruction": "RANKING de los 3 mejores álbumes o canciones con una explicación específica de por qué cada uno merece su lugar. Pide al fan que comparta su propio ranking."},
    {"type": "recuerdo",
     "instruction": "RECUERDO detallado de un concierto icónico o gira legendaria — el año, la ciudad, cuántas personas asistieron, qué canciones tocaron. Invita a los fans a compartir si estuvieron ahí."},
    {"type": "curiosidad",
     "instruction": "CURIOSIDAD verificable e impactante: una colaboración real inesperada, el proceso de grabación de un álbum famoso, una anécdota real de backstage, o cómo surgió una canción icónica. Incluye año y detalles específicos."},
    {"type": "legado",
     "instruction": "El LEGADO de la banda — cómo influyó en otras bandas, qué artistas los nombran como influencia, cómo su música sigue viva décadas después. Termina preguntando cómo los descubrió el fan."},
    {"type": "claves",
     "instruction": "CLAVES para entender a la banda en 3 puntos: su sonido, su historia y su momento más decisivo. Hazlo compacto, apasionado y con al menos una fecha concreta."},
    {"type": "sorpresa",
     "instruction": "SOPRESA: cuenta un dato poco conocido o una polémica real sobre la banda que muchos fans no saben. Relaciónalo con una canción, un concierto o un cambio de miembros."},
    {"type": "duelo",
     "instruction": "DUEL﻿O entre dos épocas de la banda o entre la banda y otra histórica. Hazlo visual y emotivo, menciona discos, canciones y por qué cada lado merece su lugar."},
]

COVER_SEEDS = [
    {"original": "Soda Stereo", "cover": "Aterciopelados", "song": "De Música Ligera", "context": "una versión especial para un tributo latino"},
    {"original": "Héroes del Silencio", "cover": "Enrique Bunbury", "song": "Entre Dos Tierras", "context": "una reinterpretación íntima en solitario"},
    {"original": "Caifanes", "cover": "Maná", "song": "Afuera", "context": "una versión en vivo en un festival de rock latino"},
    {"original": "Los Fabulosos Cadillacs", "cover": "Café Tacvba", "song": "Matador", "context": "una versión con ribetes electrónicos y ritmo latino"},
    {"original": "Caifanes", "cover": "Café Tacvba", "song": "La Negra Tomasa", "context": "un cover lleno de sabor y actitud rock"},
    {"original": "The Rolling Stones", "cover": "Soda Stereo", "song": "Paint It Black", "context": "una poderosa versión en español de un clásico global"},
]

COVER_VARIANTS = [
    "Cuenta este cover como una de esas versiones que reescriben una canción clásica. Compara el original y el cover, menciona por qué la versión nueva quedó grabada en la memoria del rock y pregunta cuál prefieren los fans.",
    "Relata la conexión entre el artista original y quien hizo el cover. Describe el momento en que la versión se volvió icónica y termina invitando a debatir si el original o el cover es mejor.",
    "Haz una mini-crónica apasionada sobre un cover que se convirtió en referencia. Nombra al artista original, al que lo hizo suyo y pregunta si te quedas con la potencia del cover o la magia del original.",
    "Presenta el cover como un choque de estilos: el clásico original frente a una versión potente y distinta. Incluye detalles reales del artista, la canción y el momento en que el cover brilló.",
]

# Post type rotation — includes "hoy_en_historia" every ~7 posts
POST_TYPE_ROTATION = [
    "original", "poll", "youtube", "hoy_en_historia",
    "original", "concert", "poll", "youtube",
    "original", "hoy_en_historia", "poll", "youtube",
    "original", "concert", "poll",
]

# Band-specific image queries
BAND_IMAGE_QUERIES = {
    "Soda Stereo":                          "Soda Stereo band Argentina rock",
    "Heroes del Silencio":                  "Heroes del Silencio Spain rock band",
    "Maná":                                 "Mana band Mexico rock concert",
    "Café Tacvba":                          "Cafe Tacvba Mexico alternative rock band",
    "Molotov":                              "Molotov Mexico punk rock band",
    "Los Prisioneros":                      "Los Prisioneros Chile rock band",
    "Caifanes":                             "Caifanes Mexico gothic rock concert",
    "La Ley":                               "La Ley Chile rock band concert",
    "Los Fabulosos Cadillacs":              "Los Fabulosos Cadillacs Argentina ska rock",
    "Divididos":                            "Divididos Argentina rock concert",
    "Bunbury":                              "Bunbury Spain rock singer concert",
    "Enrique Bunbury":                      "Enrique Bunbury Spain rock singer",
    "Fito Páez":                            "Fito Paez Argentina rock piano concert",
    "Rata Blanca":                          "Rata Blanca Argentina heavy metal band",
    "Intocable":                            "Intocable Mexico norteño rock band",
    "Jarabe de Palo":                       "Jarabe de Palo Spain rock band",
    "Gustavo Cerati":                       "Gustavo Cerati guitarist Argentina",
    "Babasónicos":                          "Babasónicos Argentina alternative rock",
    "Aterciopelados":                       "Aterciopelados Colombia rock band",
    "Enanitos Verdes":                      "Enanitos Verdes Argentina rock band",
    "Illya Kuryaki and the Valderramas":    "hip hop rock latin band concert",
    "Hombres G":                            "Hombres G Spain pop rock band",
    "El Tri":                               "El Tri Mexico rock band concert",
    "Maldita Vecindad":                     "Maldita Vecindad Mexico ska punk band",
    "Santa Sabina":                         "Santa Sabina Mexico rock band",
    "Panteon Rococo":                       "Panteon Rococo Mexico ska band concert",
    "Los de Abajo":                         "Los de Abajo Mexico ska rock band",
    "Bersuit Vergarabat":                   "Bersuit Vergarabat Argentina rock band",
    "Los Rodríguez":                        "Los Rodriguez Spain Argentina rock band",
    "Charly García":                        "Charly Garcia Argentina rock piano",
    "Luis Alberto Spinetta":                "Luis Alberto Spinetta Argentina rock guitar",
    "Virus":                                "Virus Argentina synth rock band",
    "La Renga":                             "La Renga Argentina rock concert",
    "Los Piojos":                           "Los Piojos Argentina rock concert",
    "Attaque 77":                           "Attaque 77 Argentina punk rock",
    "Los Tres":                             "Los Tres Chile rock band",
    "No Te Va Gustar":                      "No Te Va Gustar Uruguay rock band",
    "El Cuarteto de Nos":                   "El Cuarteto de Nos Uruguay rock band",
    "Ska-P":                                "Ska-P Spain ska punk concert",
    "Extremoduro":                          "Extremoduro Spain rock band",
    "Radio Futura":                         "Radio Futura Spain rock 80s",
    "Mecano":                               "Mecano Spain pop rock band",
    "Alaska y Dinarama":                    "Alaska Dinarama Spain new wave",
    "Patricio Rey y sus Redonditos de Ricota": "Patricio Rey Redonditos Argentina rock",
    "Zoé":                                  "Zoe Mexico alternative rock band",
    "Kinky":                                "Kinky Mexico electronic rock band",
    "Control Machete":                      "Control Machete Mexico hip hop rock",
    "Bomba Estéreo":                        "Bomba Estéreo Colombia electronic rock",
    "Juanes":                               "Juanes Colombia rock singer guitar",
    "Joe Vasconcellos":                     "Joe Vasconcellos Chile rock singer",
    "Miranda!":                             "Miranda Argentina pop rock band",
    "Lucybell":                             "Lucybell Chile rock band",
    "Cuca":                                 "Cuca Mexico rock band",
    "Fobia":                                "Fobia Mexico alternative rock",
    "Barricada":                            "Barricada Spain rock band",
    "Los Secretos":                         "Los Secretos Spain pop rock",
}

DEFAULT_IMAGE = "latin rock concert band stage"


# ---------------------------------------------------------------------------
# State management — prevents repeats
# ---------------------------------------------------------------------------

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {
        "used_bands":           [],
        "used_poll_indices":    [],
        "used_event_indices":   [],
        "original_type_index":  0,
        "post_type_index":      0,
        "total_posts":          0,
    }


def save_state(state):
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def pick_post_type(state):
    candidates = ["original", "poll", "youtube", "hoy_en_historia", "concert", "cover"]
    weights    = [34, 15, 15, 10, 8, 18]
    last_type  = state.get("last_post_type")
    options    = [t for t in candidates if t != last_type]
    if not options:
        options = candidates[:]
    chosen = random.choices(options, weights=[weights[candidates.index(t)] for t in options], k=1)[0]
    state["last_post_type"] = chosen
    return chosen


def pick_band(state):
    """Pick a band not used in the last 20 posts — only proven top-10 artists."""
    used = state.get("used_bands", [])

    curated = load_curated_top40()
    top10_bands = load_top10_bands(curated)
    if top10_bands:
        by_year = curated.get("top40_by_year") or {}
        if isinstance(by_year, dict) and by_year:
            end_year = int(curated.get("end_year", datetime.now(timezone.utc).year))
            start_year = int(curated.get("start_year", end_year - 49))
            year = random.randint(start_year, end_year)
            year_list = by_year.get(str(year)) or []
            top10_year = [b for b in year_list[:10] if b not in used]
            if not top10_year:
                top10_year = year_list[:10]
                state["used_bands"] = []
            band = random.choice(top10_year)
            state["used_bands"] = (used + [band])[-20:]
            state["curation_year"] = year
            return band

        available = [b for b in top10_bands if b not in used]
        if not available:
            available = top10_bands[:]
            state["used_bands"] = []
        band = random.choice(available)
        state["used_bands"] = (used + [band])[-20:]
        return band

    # Fallback to a curated set of proven top-tier artists only.
    pool = FAMOUS_FALLBACK_BANDS
    available = [b for b in pool if b not in used]
    if not available:
        available = pool[:]
        state["used_bands"] = []
    band = random.choice(available)
    state["used_bands"] = (used + [band])[-20:]
    return band


def pick_poll(state):
    used = state.get("used_poll_indices", [])
    available = [i for i in range(len(POLL_TOPICS)) if i not in used]
    if not available:
        available = list(range(len(POLL_TOPICS)))
        state["used_poll_indices"] = []
    idx = random.choice(available)
    state["used_poll_indices"] = (used + [idx])[-10:]
    return POLL_TOPICS[idx]


def pick_original_type(state):
    idx = state.get("original_type_index", 0) % len(ORIGINAL_TYPES)
    state["original_type_index"] = idx + 1
    return ORIGINAL_TYPES[idx]


def pick_historical_event(state):
    """
    Pick a historical event only if it matches today's exact month and day.
    If no exact match exists, return None so the generator can fall back safely.
    """
    now   = datetime.now(timezone.utc)
    month = now.month
    day   = now.day
    used  = state.get("used_event_indices", [])

    today_events = [
        i for i, e in enumerate(HISTORICAL_EVENTS)
        if e[0] == month and e[1] == day and i not in used
    ]
    if not today_events:
        return None, False

    idx = random.choice(today_events)
    state["used_event_indices"] = (used + [idx])[-15:]
    return HISTORICAL_EVENTS[idx], True  # True = exact date match


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


def verify_and_normalize_post(client, topic: str, post_type: str, text: str) -> str:
    """
    Lightweight reliability pass:
    - remove obvious hallucinations / fix wrong dates if the model can self-correct
    - enforce style rules (no lyrics, end with a question, no mention of other posts)
    Returns corrected text (or original if verification fails).
    """
    system = (
        "Eres un verificador editorial para una página de Facebook de rock en español.\n"
        "Tu objetivo es maximizar precisión factual y coherencia SIN inventar datos.\n"
        "Si un dato es incierto, reescribe la frase para que sea general y verdadera.\n"
        "NUNCA inventes fechas, lugares, integrantes o ventas.\n"
        "NUNCA atribuyas canciones, covers o discografías a artistas equivocadamente.\n"
        "NUNCA copies letras de canciones.\n"
        "NUNCA incluyas hashtags.\n"
        "Si el texto incluye 'Lo Mejor del Rock en Español les presenta', elimínalo salvo que el tipo sea 'youtube'.\n"
        "Evita clichés repetidos (ej: 'la energía es increíble', 'una de las bandas más...', 'ha sido una fuerza dominante').\n"
        "Responde ÚNICAMENTE con JSON válido."
    )
    prompt = (
        f"Tema: {topic}\n"
        f"Tipo: {post_type}\n\n"
        "Texto original:\n"
        f"{text}\n\n"
        "Tareas:\n"
        "- Corrige o suaviza afirmaciones dudosas (sin inventar detalles)\n"
        "- Mantén el tono de fan apasionado\n"
        "- Mantén longitud similar\n"
        "- Quita cualquier bloque tipo 'les presenta' si no corresponde\n"
        "- Termina con una pregunta directa\n\n"
        'Devuelve JSON: {"text":"..."}'
    )
    try:
        raw = call_groq(client, system, prompt, max_tokens=700, json_mode=True)
        data = clean_json(raw)
        out = (data.get("text") or "").strip()
        return out if len(out) >= 40 else text
    except Exception:
        return text


# ---------------------------------------------------------------------------
# Hashtag builder
# ---------------------------------------------------------------------------

def clean_tag(text):
    return (text
        .replace(" ", "").replace("á","a").replace("é","e")
        .replace("í","i").replace("ó","o").replace("ú","u")
        .replace("ñ","n").replace("ü","u").replace("&","and")
        .replace(".","").replace(",","").replace("'","")
        .replace("-","").replace("(","").replace(")","")
        .replace("!","").replace("¡","").replace("?","").replace("¿","")
    )


FOLLOW_HANDLE = "@mejorrockespanol"


def build_hashtags(band, extra_tags=None, post_type="original"):
    """
    "Lo Mejor del Rock en Español les presenta:" only on YouTube posts.
    No country-specific hashtags.
    """
    band_tag  = clean_tag(band)
    core_tags = "#LoMejordelRockenEspañol #RockEnEspañol #RockLatino #RockEspañol"

    band_tags = "#" + band_tag
    if extra_tags:
        for t in extra_tags[:3]:
            cleaned = clean_tag(t)
            if cleaned and cleaned.lower() != band_tag.lower():
                band_tags += " #" + cleaned

    follow_text = "🎸 Síguenos para más rock en español → " + FOLLOW_HANDLE

    if post_type == "youtube":
        footer = (
            "\n\nLo Mejor del Rock en Español les presenta: " + band_tags + "\n\n"
            + core_tags + " " + band_tags + "\n\n"
            + follow_text
        )
    else:
        footer = (
            "\n\n"
            + core_tags + " " + band_tags + "\n\n"
            + follow_text
        )
    return footer


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

RULES_COMMON = """
REGLAS OBLIGATORIAS:
- Español natural y conversacional, tono de fan apasionado y conocedor
- NUNCA menciones hora del día ni hagas referencia a otros posts
- NUNCA copies letras de canciones
- USA DATOS REALES Y VERIFICABLES — años, nombres de álbumes reales, ciudades reales
- Termina SIEMPRE con una pregunta directa que invite a comentar
- NO incluyas hashtags — se agregan automáticamente
- EVITA frases genéricas repetidas (ej: "la energía es increíble", "es una de las bandas más...", "ha sido una fuerza dominante")
- NUNCA empieces con "Recuerdan" o frases de nostalgia muy parecidas
- NO atribuyas canciones, covers o discografías a artistas equivocadamente
- VARÍA el gancho: usa pregunta, comparación audaz, anécdota inédita, dato poco conocido o desafío directo
- NO uses "Lo Mejor del Rock en Español les presenta" excepto en posts de tipo YOUTUBE
"""

SYSTEM_ORIGINAL = """Eres el creador apasionado de "Mejor Rock en Español" en Facebook.
Eres un experto en la historia del rock en español con conocimiento profundo de cada banda.
""" + RULES_COMMON + """
- 150–220 palabras
- Incluye datos específicos: años exactos, nombres de álbumes reales, anécdotas verificadas
- Menciona integrantes por nombre cuando sea relevante
- Usa al menos UNA estructura distinta cada vez: mini-historia, mito aclarado, lista exclusiva, comparación de eras o curiosidad sorpresa

FORMATO: JSON puro.
{"type":"string","topic":"banda principal","text":"contenido","image_query":"nombre banda inglés + descriptor específico"}"""

SYSTEM_POLL = """Eres el creador de "Mejor Rock en Español" en Facebook.
""" + RULES_COMMON + """
Crea posts de votación con reacciones como votos.

EMOJIS: 👍 = opción A | ❤️ = opción B | 😮 = opción C

- 2-3 frases de contexto apasionante antes de las opciones
- Lista las 3 opciones claramente con emojis
- Termina EXACTAMENTE con: "¡Vota con tu reacción! 👍❤️😮"
- 100–150 palabras

FORMATO: JSON puro.
{"topic":"tema","text":"contenido","image_query":"banda específica inglés + band concert"}"""

SYSTEM_HOY = """Eres el historiador musical de "Mejor Rock en Español" en Facebook.
Escribes posts de la serie "Un día como hoy" sobre eventos históricos reales del rock en español.
""" + RULES_COMMON + """
ESTRUCTURA OBLIGATORIA:
- Primera línea: "🎸 Un día como hoy, [DD de mes de AÑO]..." 
- Luego narra el evento histórico con detalles específicos y apasionantes
- Menciona el impacto que tuvo ese evento en la música
- Pregunta final: invita a los fans a compartir qué significa ese evento para ellos
- 150–200 palabras
- USA SOLO HECHOS REALES del evento proporcionado

FORMATO: JSON puro.
{"type":"hoy_en_historia","topic":"banda","text":"contenido completo","image_query":"banda inglés + año + concert o band"}"""

SYSTEM_CONCERT = """Eres el creador de "Mejor Rock en Español" en Facebook.
""" + RULES_COMMON + """
Escribe un post emocionante sobre un concierto o evento próximo.
- Tono emocionado y urgente
- Fecha, ciudad y artista prominentes
- Crea un gancho fuerte: una razón por la que no pueden perderse ese show- No empieces con "Recuerdan" ni con frases de nostalgia repetitivas- Termina con "¡Consigue tus boletos!" y una pregunta
- NO incluyas links — van al final automáticamente
- 100–160 palabras

FORMATO: JSON puro.
{"topic":"artista","text":"contenido","image_query":"artista inglés + concert live performance"}"""

SYSTEM_YOUTUBE = """Eres el creador de "Mejor Rock en Español" en Facebook.
""" + RULES_COMMON + """
Escribe un comentario original para compartir un video de YouTube.
- Elige un ángulo claro: la energía del vivo, el legado del clip, una anécdota del escenario, o por qué este video es imprescindible
- Opina algo específico y apasionado sobre la banda, álbum o era
- NO copies la descripción del video
- NO incluyas el link — va al final
- 120–180 palabras

FORMATO: JSON puro.
{"topic":"banda","text":"comentario","image_query":"banda inglés + concert live"}"""
SYSTEM_COVER = """Eres el creador de \"Mejor Rock en Español\" en Facebook.
""" + RULES_COMMON + """
Escribe un post creativo sobre un cover famoso entre dos artistas reconocidos.
- Elige un caso real o plausible de:
  * un artista famoso cubriendo una canción clásica del rock en español
  * o un artista de rock en español cubriendo una canción famosa internacional
- Menciona al artista original, al artista que hizo el cover y el título de la canción
- Destaca lo que hace especial la versión cover: el arreglo, la voz, el escenario, el legado o el impacto cultural
- No empieces con "Recuerdan" ni frases de nostalgia repetitivas
- Termina con una pregunta que invite al fan a elegir entre original y cover o a comentar qué versión le mueve más
- 120–180 palabras

FORMATO: JSON puro.
{"topic":"cover","text":"contenido","image_query":"artista cover + canción"}"""

# ---------------------------------------------------------------------------
# Content generators
# ---------------------------------------------------------------------------

def gen_original(client, state, band):
    chosen      = pick_original_type(state)
    image_query = get_image_query(band)
    prompt = (
        "Genera un post tipo " + chosen["type"].upper() + " sobre: " + band + "\n"
        "Instrucción: " + chosen["instruction"] + "\n\n"
        "IMPORTANTE: usa datos reales y verificables sobre " + band + ".\n"
        "image_query: '" + image_query + "'\n\n"
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
    image_query       = get_image_query(band)
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


def gen_hoy_en_historia(client, state):
    """Generate a 'Un día como hoy' historical post."""
    event, is_exact = pick_historical_event(state)
    if not event:
        return None
    month, day, year, band, description = event

    month_names = {
        1:"enero",2:"febrero",3:"marzo",4:"abril",5:"mayo",6:"junio",
        7:"julio",8:"agosto",9:"septiembre",10:"octubre",11:"noviembre",12:"diciembre"
    }
    month_name  = month_names[month]
    image_query = get_image_query(band) + " " + str(year)

    prompt = (
        "Escribe un post de la serie 'Un día como hoy' sobre este evento histórico REAL:\n\n"
        "Fecha: " + str(day) + " de " + month_name + " de " + str(year) + "\n"
        "Banda/Artista: " + band + "\n"
        "Evento: " + description + "\n\n"
        "La primera línea DEBE ser: '🎸 Un día como hoy, " + str(day) + " de " + month_name + " de " + str(year) + "...'\n"
        "Luego narra el evento con pasión y detalle.\n"
        "image_query: '" + image_query + "'\n\n"
        "Responde ÚNICAMENTE con JSON válido."
    )
    data = clean_json(call_groq(client, SYSTEM_HOY, prompt, max_tokens=800))
    data["image_query"] = image_query
    data["topic"]       = band
    data["post_type"]   = "hoy_en_historia"
    data["post_year"]   = str(year)
    return data


def gen_concert(client, state, band):
    concert     = get_concert_info(band)
    if not concert:
        return gen_original(client, state, band)

    topic       = concert.get("artist", band)
    image_query = get_image_query(topic)
    prompt = (
        "Concierto próximo en los próximos 1-3 meses:\n"
        "  Artista: " + concert["name"] + "\n"
        "  Fecha: " + concert["date"] + "\n"
        "  Ciudad: " + concert["city"] + ", " + concert["country"] + "\n\n"
        "Escribe un post que invite a los fans a ir, destaque por qué este show no se puede perder y mencione dónde conseguir boletos. NO incluyas links.\n"
        "image_query: '" + image_query + "'\n\n"
        "Responde ÚNICAMENTE con JSON válido."
    )
    concert_url = concert["url"]

    data = clean_json(call_groq(client, SYSTEM_CONCERT, prompt, max_tokens=600))
    data["concert_url"] = concert_url
    data["topic"]       = topic
    data["post_type"]   = "concert"
    data["image_query"] = image_query
    data["text"]        = data["text"] + "\n\n🎟️ Consigue boletos en Ticketmaster, en la web oficial del evento o en la taquilla del venue."
    return data


def gen_cover(client, state, band):
    seed = random.choice(COVER_SEEDS)
    variant = random.choice(COVER_VARIANTS)
    image_query = seed["cover"] + " " + seed["song"] + " live"
    prompt = (
        f"{variant}\n\n"
        f"Artista original: {seed['original']}\n"
        f"Cover: {seed['cover']}\n"
        f"Canción: {seed['song']}\n"
        f"Contexto: {seed['context']}\n\n"
        "Escribe un post creativo y diferente cada vez, usando un tono de fan apasionado. "
        "No copies letras. No incluyas hashtags ni links. Responde ÚNICAMENTE con JSON válido."
    )
    data = clean_json(call_groq(client, SYSTEM_COVER, prompt, max_tokens=700))
    data["image_query"] = image_query
    data["topic"]       = seed["cover"]
    data["post_type"]   = "cover"

    video = get_video_for_topic(seed["cover"] + " " + seed["song"])
    if not video:
        video = get_video_for_topic(seed["original"] + " " + seed["song"])
    if video:
        data["video_url"] = video["url"]
        if video["url"] not in data.get("text", ""):
            data["text"] = data.get("text", "").rstrip() + "\n\n" + video["url"]

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
        "Escribe el comentario apasionado. NO incluyas el link.\n"
        "image_query: '" + image_query + "'\n\n"
        "Responde ÚNICAMENTE con JSON válido."
    )
    data = clean_json(call_groq(client, SYSTEM_YOUTUBE, prompt, max_tokens=600))
    data["image_query"] = image_query
    data["topic"]       = band
    data["post_type"]   = "youtube"
    data["video_url"]   = video["url"]
    data["text"]        = data["text"] + "\n\n" + video["url"]
    return data


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate_post():
    now       = datetime.now(timezone.utc)
    stamp     = now.strftime("%Y%m%d_%H%M%S")
    state     = load_state()
    client    = Groq(api_key=GROQ_API_KEY)
    post_type = pick_post_type(state)
    band      = pick_band(state)

    print("[" + now.isoformat() + "] Generating ONE post...")
    print("  Post type : " + post_type)
    print("  Band/topic: " + band)

    # Generate content based on type
    if post_type == "original":
        data = gen_original(client, state, band)

    elif post_type == "poll":
        data = gen_poll(client, state, band)

    elif post_type == "hoy_en_historia":
        data = gen_hoy_en_historia(client, state)
        if not data:
            print("  No exact 'Un día como hoy' event for today — falling back to original")
            data = gen_original(client, state, band)
            post_type = "original"
        else:
            band = data.get("topic", band)

    elif post_type == "youtube":
        data = gen_youtube(client, band)
        if not data:
            print("  YouTube not found — falling back to original")
            data = gen_original(client, state, band)

    elif post_type == "concert":
        data = gen_concert(client, state, band)
        band = data.get("topic", band)

    elif post_type == "cover":
        data = gen_cover(client, state, band)
        band = data.get("topic", band)

    else:
        data = gen_original(client, state, band)

    # Extract year from text for era-matched images
    import re as _re
    years_found = _re.findall(r"\b(19[5-9]\d|20[0-2]\d)\b", data.get("text", ""))
    post_year   = data.get("post_year", years_found[0] if years_found else "")

    # Find extra band mentions for hashtags
    text_so_far  = data.get("text", "")
    extra_mentions = [b for b in BANDS if b in text_so_far and b != data.get("topic", band)]

    # Build hashtags — "presents" only for YouTube
    actual_type  = data.get("post_type", post_type)
    hashtags     = build_hashtags(data.get("topic", band), extra_tags=extra_mentions[:3], post_type=actual_type)
    # Reliability pass BEFORE adding hashtags (keeps the verifier focused on facts/style)
    verified_text = verify_and_normalize_post(
        client,
        topic=data.get("topic", band),
        post_type=actual_type,
        text=data.get("text", ""),
    ).rstrip()

    video_url = data.get("video_url")
    if video_url and video_url not in verified_text:
        verified_text = verified_text.rstrip() + "\n\n" + video_url

    data["text"] = verified_text.rstrip() + hashtags

    # Build queue entry
    entry = {
        "id":           "post_" + stamp,
        "status":       "pending",
        "created_at":   now.isoformat(),
        "post_type":    actual_type,
        "topic":        data.get("topic", band),
        "text":         data["text"],
        "image_query":  data.get("image_query", get_image_query(band)),
        "extra_topics": extra_mentions[:4],
        "post_year":    post_year,
        "curation_year": str(state.get("curation_year", "")) if state.get("curation_year") else "",
        "video_url":    data.get("video_url"),
        "concert_url":  data.get("concert_url"),
        "fb_post_id":   None,
        "ig_post_id":   None,
        "published_at": None,
        "error":        None,
    }

    # Add to queue — keep last 50 for history
    queue = load_queue()
    queue.append(entry)
    queue = queue[-50:]
    save_queue(queue)

    state["total_posts"] = state.get("total_posts", 0) + 1
    save_state(state)

    print("  Topic     : " + entry["topic"])
    print("  Year      : " + (post_year or "not specified"))
    print("  Image     : " + entry["image_query"])
    print("  Text      : " + entry["text"][:100] + "...")
    print("  Saved     : " + entry["id"])


if __name__ == "__main__":
    generate_post()
