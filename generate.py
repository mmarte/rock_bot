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
import hashlib
import json
import os
import random
import re
import requests
import unicodedata
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


LAST_N_YEARS = 30
MIN_YEAR = 1985

def load_top10_bands(curated: dict | None = None) -> list[str]:
    curated = curated or load_curated_top40()
    if not curated:
        return []
    by_year = curated.get("top40_by_year") or {}
    if not isinstance(by_year, dict):
        return []
    end_year = int(curated.get("end_year", datetime.now(timezone.utc).year))
    start_year = max(MIN_YEAR, end_year - LAST_N_YEARS + 1)
    top10 = set()
    for year_str, year_list in by_year.items():
        try:
            year = int(year_str)
        except ValueError:
            continue
        if year < start_year or year > end_year:
            continue
        if isinstance(year_list, list):
            for band in year_list[:10]:
                top10.add(band)
    return sorted(top10)

# ---------------------------------------------------------------------------
# Country-balanced fallback pools for proven rock en español artists
# ---------------------------------------------------------------------------
COUNTRY_BAND_POOLS = {
    "Argentina": [
        "Soda Stereo", "Divididos", "Fito Páez", "Los Fabulosos Cadillacs",
        "La Renga", "Charly García", "Gustavo Cerati", "Los Piojos",
    ],
    "México": [
        "Maná", "Café Tacvba", "Molotov", "Caifanes",
        "El Tri", "Zoé", "Panteon Rococo", "Cuca",
    ],
    "España": [
        "Héroes del Silencio", "Enrique Bunbury", "Mecano", "Hombres G",
        "Radio Futura", "Los Rodríguez", "Extremoduro",
    ],
    "Chile": [
        "La Ley", "Los Prisioneros", "Los Tres",
    ],
    "Colombia": [
        "Juanes", "Aterciopelados", "Bomba Estéreo",
    ],
    "Uruguay": [
        "No Te Va Gustar", "El Cuarteto de Nos", "La Vela Puerca",
    ],
    "Perú": [
        "Líbido", "Los Mojarras", "Frágil",
    ],
    "Venezuela": [
        "Caramelos de Cianuro", "Desorden Público", "Zapato 3",
    ],
    "Ecuador": [
        "La Máquina Camaleón", "Dedicados", "Cascomar",
    ],
    "Panamá": [
        "Los Rabanes",
    ],
    "Puerto Rico": [
        "Fiel a la Vega",
    ],
    "Guatemala": [
        "Alux Nahual",
    ],
    "Costa Rica": [
        "Gandhi", "Malpaís",
    ],
    "República Dominicana": [
        "Toque Profundo",
    ],
    "Bolivia": [
        "Octavia",
    ],
    "Paraguay": [
        "Flou",
    ],
    "Honduras": [
        "Savage",
    ],
    "El Salvador": [
        "Cinema", "Kraken",
    ],
    "Nicaragua": [
        "La Cuneta Son Machín",
    ],
    "Cuba": [
        "Habana Abierta",
    ],
}

BAND_COUNTRY = {
    band: country
    for country, bands in COUNTRY_BAND_POOLS.items()
    for band in bands
}

# ---------------------------------------------------------------------------
# Monthly pool additions (pool_refresh.py, fully automated).
# pool_additions.json is merged here so new bands enter the rotation
# without editing this file. Additive only — never removes bands.
# ---------------------------------------------------------------------------
def _load_pool_additions():
    try:
        _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pool_additions.json")
        with open(_p, encoding="utf-8") as _f:
            _data = json.load(_f)
        for _country, _bands in (_data.get("text") or {}).items():
            _existing = {b.lower() for b in COUNTRY_BAND_POOLS.get(_country, [])}
            for _b in _bands:
                if _b and _b.lower() not in _existing:
                    COUNTRY_BAND_POOLS.setdefault(_country, []).append(_b)
                    _existing.add(_b.lower())
    except FileNotFoundError:
        pass
    except Exception as _e:
        print(f"  pool_additions.json not loaded: {_e}")


_load_pool_additions()

# ---------------------------------------------------------------------------
# Proven rock en español artists — focus on those with top-10 presence in the last 30 years
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
    (3, 13, 1963, "Fito Páez", "nació en Rosario, Argentina, el pianista y compositor que redefinió el rock argentino"),
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
    (12, 8, 1959, "Maná", "el vocalista Fher Olvera nació en Puebla, México"),
    (9, 20, 2014, "Gustavo Cerati", "falleció en Buenos Aires a los 55 años, dejando un legado inmortal en el rock en español"),

    # October
    (10, 5, 1984, "Caifanes", "lanzó su primer sencillo, iniciando la era oscura y brillante del rock mexicano"),
    (10, 16, 1987, "Soda Stereo", "publicó 'Signos', el álbum que los estableció como la banda más importante del rock en español"),
    (10, 20, 2007, "Soda Stereo", "reunió a 250,000 personas en el concierto 'Me Verás Volver' en Buenos Aires, uno de los eventos más grandes de la historia del rock latinoamericano"),

    # November
    (7, 3, 1990, "Maná", "publicó 'Falta Amor', el álbum que los lanzó a la fama internacional"),
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
     "instruction": "DUELO entre dos épocas de la MISMA banda (nunca inventes una banda rival). Menciona solo discos, canciones, integrantes y fechas REALES y verificables de esa banda. Hazlo visual y emotivo y explica por qué cada época merece su lugar."},
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
        # Auto-update / no-repeat tracking, added 2026-10-24:
        # used_topics holds "topic|post_type" for the FINAL published topic
        # (not just the band first picked — cover/concert/hoy posts can change
        # topic after pick_band runs). used_text_hashes holds hashes of the
        # final post text, so near-identical text is not regenerated.
        "used_topics":          [],
        "used_text_hashes":     [],
    }


def save_state(state):
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def normalize_text_for_hash(text):
    """Normalize post text for duplicate detection.

    URLs, hashtags and whitespace differences do not make a post new:
    the same story about the same band, reworded only by hashtags, is
    still a repeat for followers.
    """
    import re as _re
    t = (text or "").lower()
    t = _re.sub(r"https?://\S+", " ", t)
    t = _re.sub(r"#[\w\-]+", " ", t)
    t = _re.sub(r"[^\w\s]", " ", t)
    return _re.sub(r"\s+", " ", t).strip()


def text_hash(text):
    return hashlib.sha256(normalize_text_for_hash(text).encode("utf-8")).hexdigest()


def topic_key(topic, post_type):
    return ((topic or "").strip().lower() + "|" + (post_type or "").strip().lower())


def pick_post_type(state):
    candidates = ["original", "poll", "youtube", "hoy_en_historia", "concert", "cover"]
    weights    = [28, 16, 16, 10, 8, 22]
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
    if top10_bands and curated:
        by_year = curated.get("top40_by_year") or {}
        if isinstance(by_year, dict) and by_year:
            end_year = int(curated.get("end_year", datetime.now(timezone.utc).year))
            start_year = max(MIN_YEAR, end_year - LAST_N_YEARS + 1)
            year = random.randint(start_year, end_year)
            year_list = by_year.get(str(year)) or []
            top10_year = [b for b in year_list[:10] if b not in used]
            if not top10_year:
                top10_year = [b for b in year_list[:10] if isinstance(b, str)]
                state["used_bands"] = []
                used = []

            if top10_year:
                mapped = [b for b in top10_year if b in BAND_COUNTRY]
                if mapped:
                    countries = sorted(set(BAND_COUNTRY[b] for b in mapped))
                    country = random.choice(countries)
                    country_choices = [b for b in mapped if BAND_COUNTRY[b] == country]
                    band = random.choice(country_choices)
                else:
                    band = random.choice(top10_year)
                state["used_bands"] = (used + [band])[-20:]
                state["curation_year"] = year
                return band

        available = [b for b in top10_bands if b not in used]
        if not available:
            available = top10_bands[:]
            state["used_bands"] = []
            used = []
        band = random.choice(available)
        state["used_bands"] = (used + [band])[-20:]
        return band

    # Fallback to a balanced country pool of proven top-tier artists.
    country = random.choice(list(COUNTRY_BAND_POOLS.keys()))
    pool = COUNTRY_BAND_POOLS[country][:]
    available = [b for b in pool if b not in used]
    if not available:
        available = pool[:]
        state["used_bands"] = []
        used = []
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
    last_error = None
    # Model availability on Groq Developer accounts changed in 2026:
    # qwen/qwen3.6-27b 404s, and llama-3.3-70b-versatile 404s too because
    # Llama 3.x is now Enterprise-only on Groq (shut down for free/Developer
    # accounts Aug 2026). The models that remain on Developer accounts are
    # the gpt-oss pair, plus qwen3.8 as a third fallback. A dead model must
    # not kill the run: any API error now falls through to the next model.
    # Also request JSON mode from the API itself: gpt-oss was returning
    # non-JSON text that clean_json rejected, which is what forced the
    # fallback to a dead model in the first place.
    for model in ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"):
        for attempt in range(2):
            kwargs = dict(
                model       = model,
                messages    = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature = 0.9 if attempt == 0 else 0.6,
                max_tokens  = max_tokens,
            )
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            try:
                content = client.chat.completions.create(**kwargs).choices[0].message.content or ""
            except Exception as error:
                last_error = error
                error_text = str(error)
                # A missing/retired model will fail the same way on retry,
                # so skip straight to the next model instead of retrying it.
                if "not_found" in error_text or "does not exist" in error_text:
                    break
                continue

            if not content.strip():
                last_error = RuntimeError("Groq returned an empty response.")
                continue
            if json_mode:
                try:
                    clean_json(content)
                except (TypeError, ValueError, json.JSONDecodeError) as error:
                    last_error = error
                    continue
            return content

    raise RuntimeError("Groq returned no usable JSON response from the configured models.") from last_error


def clean_json(raw):
    raw = (raw or "").strip()
    if raw.startswith("```"):
        parts = raw.split("```", 2)
        raw = parts[1] if len(parts) > 1 else raw
        if raw.lstrip().lower().startswith("json"):
            raw = raw.lstrip()[4:]

    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError as original_error:
        # Models sometimes add a short explanation around otherwise valid JSON.
        # Parse the first complete object/array found in that response.
        decoder = json.JSONDecoder()
        for index, character in enumerate(raw):
            if character not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(raw[index:])
                return value
            except json.JSONDecodeError:
                continue
        raise original_error


def verify_and_normalize_post(client, topic: str, post_type: str, text: str, facts: str = "") -> str:
    """
    Lightweight reliability pass:
    - remove obvious hallucinations / fix wrong dates if the model can self-correct
    - enforce style rules (no lyrics, end with a question, no mention of other posts)
    - when `facts` (Wikipedia) is given, claims are checked against it instead of memory
    - then the programmatic date gate runs on the result: years/decades
      must be supported by `facts` (see _unsupported_date_claims). Dates
      the model invented are stripped sentence-by-sentence; if nothing
      salvageable remains, the post falls back to _safe_post_from_facts.
    Returns corrected text (or original if verification fails).
    """
    system = (
        "Eres un verificador editorial para una página de Facebook de rock en español.\n"
        "Tu objetivo es maximizar precisión factual y coherencia SIN inventar datos.\n"
        "Si un dato es incierto, reescribe la frase para que sea general y verdadera.\n"
        "NUNCA inventes fechas, lugares, integrantes o ventas.\n"
        "NUNCA atribuyas canciones, covers o discografías a artistas equivocadamente.\n"
        "NUNCA copies letras de canciones.\n"
        "NUNCA empieces con 'Recuerda' o 'Recuerdan'.\n"
        "NUNCA incluyas hashtags.\n"
        "Si el texto incluye 'Lo Mejor del Rock en Español les presenta', elimínalo salvo que el tipo sea 'youtube'.\n"
        "Evita clichés repetidos (ej: 'la energía es increíble', 'una de las bandas más...', 'ha sido una fuerza dominante').\n"
        "Responde ÚNICAMENTE con JSON válido."
    )
    if facts:
        system += (
            "\nDATOS VERIFICADOS (fuente: Wikipedia) — coteja cada nombre, fecha, álbum, canción e integrante contra estos datos:\n"
            + facts[:1200] + "\n"
            "Todo lo que contradiga estos datos o no aparezca en ellos, suavízalo a una frase general o elimínalo.\n"
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
        "- Reescribe la primera frase si comienza con nostalgia repetitiva como 'Recuerda cuando' o 'Recuerdan cuando'\n"
        "- Termina con una pregunta directa\n\n"
        'Devuelve JSON: {"text":"..."}'
    )
    try:
        raw = call_groq(client, system, prompt, max_tokens=700, json_mode=True)
        data = clean_json(raw)
        out = (data.get("text") or "").strip()
        base = out if len(out) >= 40 else text
    except Exception:
        base = text
    bad = _unsupported_date_claims(base, facts) if post_type != "hoy_en_historia" else []
    # "hoy_en_historia" is exempt: its date is injected from the curated
    # HISTORICAL_EVENTS list (corrected against Wikipedia 2026-11-04),
    # not invented by the model, so the gate must not strip it.
    if not bad:
        return base
    print(f"  Date gate: unsupported date claims {bad} — stripping those sentences.")
    stripped = _strip_sentences_with(base, bad)
    if len(stripped) >= 40 and "?" in stripped:
        return stripped
    print("  Date gate: nothing salvageable — using safe fallback post.")
    return _safe_post_from_facts(topic, facts)


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


def build_hashtags(band, extra_tags=None, post_type="original", include_band_tag=True):
    """
    "Lo Mejor del Rock en Español les presenta:" only on YouTube posts.
    No country-specific hashtags.

    include_band_tag=False (2026-11-09 topic-tag guardrail): omit the
    topic band's own tag when the verified body never names it — a tag
    for a band the post is not about is misleading. Extra tags for bands
    the body DOES name are still appended.
    """
    band_tag  = clean_tag(band)
    core_tags = "#LoMejordelRockenEspañol #RockEnEspañol #RockLatino #RockEspañol"

    band_tags = ("#" + band_tag) if include_band_tag else ""
    if extra_tags:
        for t in extra_tags[:3]:
            cleaned = clean_tag(t)
            if cleaned and cleaned.lower() != band_tag.lower():
                band_tags += (" " if band_tags else "") + "#" + cleaned

    follow_text = "🎸 Síguenos para más rock en español → " + FOLLOW_HANDLE
    tag_line = (core_tags + " " + band_tags).rstrip()

    if post_type == "youtube":
        presenta = ("Lo Mejor del Rock en Español les presenta: " + band_tags
                    if band_tags else "Lo Mejor del Rock en Español les presenta:")
        footer = (
            "\n\n" + presenta + "\n\n"
            + tag_line + "\n\n"
            + follow_text
        )
    else:
        footer = (
            "\n\n"
            + tag_line + "\n\n"
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
- NUNCA empieces con "Recuerda", "Recuerdan" o frases de nostalgia muy parecidas
- NUNCA uses ganchos nostálgicos como "Recuerda cuando", "Recuerdan cuando" o "¿Recuerdas?" al comienzo del post
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
- La primera frase no debe comenzar con nostalgia ni con expresiones tipo "Recuerda cuando" o "Recuerdan cuando"
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
- Crea un gancho fuerte: una razón por la que no pueden perderse ese show
- No empieces con "Recuerdan" ni con frases de nostalgia repetitivas
- Termina con "¡Consigue tus boletos!" y una pregunta
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
# Wikipedia facts grounding (2026-11-04)
# Text posts are grounded in the band's Wikipedia article lead at generation
# time, so the generator AND the verifier check claims against a real source
# instead of the model's memory alone. Keyless; soft-fails to "" (no facts),
# in which case the prompts forbid inventing concrete facts outright.
# ---------------------------------------------------------------------------

_WIKI_FACTS_UA = {"User-Agent": "rock_bot-text-posts/1.0 (Lo Mejor del Rock en Espanol; fact grounding)"}
_WIKI_FACTS_CACHE = {}


def _wiki_norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


# Parentheticals that mark the article as the musical act, not a homonym
# (e.g. "Maná (banda)" over "Maná", the biblical manna).
_BAND_DISAMBIG = ("(banda)", "(band)", "(grupo)", "(grupo musical)",
                  "(cantante)", "(m\u00fasico)", "(musician)", "(singer)")
_DISAMBIG_RE = re.compile(r"(?i)may refer to|desambiguaci|puede referirse|se puede referir")
# The lead must read like a musical act, not a homonym (footballer, cookie…).
_MUSIC_RE = re.compile(
    r"(?i)\b(banda|grupo|rock|pop|música|music|cantante|singer"
    r"|músico|musician|álbum|album|discograf|trovador|sonero|dúo|trío)"
)
# Parentheticals that mark the article as a NON-musical work (film, novel,
# book, …) — never accept these as the band, even when the extract happens
# to contain a music word. Found 2026-11-05: "Los chicos de la banda
# (película)" passed the music check on the word "banda" in its own title,
# while the real band's one-sentence lead (71 chars) was skipped by the
# 120-char minimum — so grounding returned a 1970 film's facts for the band.
_NONMUSIC_DISAMBIG_RE = re.compile(
    r"(?i)\((película|pelicula|film|movie|novela|libro|book|serie|videojuego"
    r"|obra|relato|cómic|comic|programa|telenovela|documental)\)"
)


def _rank_article_titles(titles, key):
    """Candidate article titles for the band, best first: musical-act
    disambiguation ("X (banda)") wins over bare homonyms ("X"), then exact
    name match. Returns [] when nothing fits."""
    scored = []
    for t in titles:
        plain = re.sub(r"\s*\([^)]*\)\s*$", "", t).strip()
        pnorm = _wiki_norm(plain)
        if not key or key not in pnorm:
            continue
        score = (
            1 if any(d in t.lower() for d in _BAND_DISAMBIG) else 0,
            1 if pnorm == key else 0,
        )
        scored.append((score, t))
    scored.sort(key=lambda s: s[0], reverse=True)
    return [t for _, t in scored]


def get_wikipedia_facts(band):
    """Short verified-facts block for a band from Wikipedia, or "" if none."""
    key = _wiki_norm(band)
    if key in _WIKI_FACTS_CACHE:
        return _WIKI_FACTS_CACHE[key]
    facts = ""
    for wiki in ("es.wikipedia.org", "en.wikipedia.org"):
        try:
            # Resolve the article title first (opensearch, keyless).
            r = requests.get(
                "https://" + wiki + "/w/api.php",
                headers=_WIKI_FACTS_UA,
                params={"action": "opensearch", "search": band, "limit": 8,
                        "namespace": 0, "format": "json"},
                timeout=20,
            )
            r.raise_for_status()
            titles = (r.json() or [None, []])[1]
            for title in _rank_article_titles(titles, key)[:4]:
                if _NONMUSIC_DISAMBIG_RE.search(title):
                    continue
                # Fetch the plain-text lead section.
                r2 = requests.get(
                    "https://" + wiki + "/w/api.php",
                    headers=_WIKI_FACTS_UA,
                    params={"action": "query", "format": "json", "formatversion": "2",
                            "prop": "extracts", "exintro": "1", "explaintext": "1",
                            "exsectionformat": "plain", "redirects": "1",
                            "titles": title},
                    timeout=20,
                )
                r2.raise_for_status()
                pages = (r2.json().get("query") or {}).get("pages") or []
                extract = (pages[0].get("extract") or "").strip() if pages else ""
                # Short leads are valid (Los Chicos' real lead is 71 chars).
                if len(extract) < 50 or _DISAMBIG_RE.search(extract):
                    continue
                # The lead must describe a musical act — never a homonym
                # (footballer, cookie, …). Wrong facts are worse than none.
                if _MUSIC_RE.search(extract[:600]):
                    facts = extract[:1500]
                    break
            if facts:
                break
        except Exception:
            continue
    _WIKI_FACTS_CACHE[key] = facts
    return facts


# ---------------------------------------------------------------------------
# Programmatic date gate (2026-11-05)
# Why: the Nov 5 spot-check proved the model verifier cannot be the last
# word on dates — it is the same model that invents them, and it let an
# "años 80" Los Chicos post through even with Wikipedia grounding live.
# So dates are now checked with code, not judgment:
#   - a 4-digit year must appear verbatim in the Wikipedia facts block;
#   - a decade ("años 80", "80s", "década de los 80", "los ochenta")
#     needs at least one year of that decade in the facts;
#   - when there are NO verified facts at all, every date token and every
#     quoted title is unsupported (nothing verified = nothing concrete).
# What it does NOT catch (honest limit): wrong cities, wrong member roles
# and invented song titles with no date attached — e.g. "Nació en La Plata
# en 1963" passes because 1963 IS in Fito's facts. Those still rely on the
# grounding prompt above. The gate is deliberately narrow so it almost
# never false-positives: it only fires on dates, and dates in the post
# are supposed to come from the facts block by construction.
# ---------------------------------------------------------------------------

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_DECADE_WORD = {"sesenta": 1960, "setenta": 1970, "ochenta": 1980, "noventa": 1990}
# Decade forms: "años 2000" / "década de 2000" (4-digit), "años 80" /
# "década de los ochenta" (2-digit/word after años/década), bare "los 80"
# (rock decades only, 50-99 — "los 15 años" is a count, not a decade),
# and "80s". A decade span is masked out before the year pass, so
# "los 2000" is checked as the 2000s decade, not as the year 2000.
_DECADE_RE = re.compile(
    r"(?i)\b(?:a\u00f1os|los|(?:la\s+)?d\u00e9cada\s+de(?:\s+los)?)\s+((?:19|20)\d{2})(?!\d)\b"
    r"|\b(?:a\u00f1os|(?:la\s+)?d\u00e9cada\s+de(?:\s+los)?)\s+(\d{2}|sesenta|setenta|ochenta|noventa)(?!\d)\b"
    r"|\blos\s+([5-9]\d)(?!\d)\b"
    r"|\b(\d{2})s\b"
)


def _unsupported_date_claims(text, facts):
    """Date tokens (years, decades, quoted titles when facts are empty)
    in `text` with no support in `facts`. Returns offending tokens."""
    bad = []
    fnorm = _wiki_norm(facts) if facts else ""
    text = text or ""
    decades = list(_DECADE_RE.finditer(text))
    masked = text
    for m in reversed(decades):
        masked = masked[:m.start()] + " " * (m.end() - m.start()) + masked[m.end():]
    for m in _YEAR_RE.finditer(masked):
        if m.group(0) not in fnorm:
            bad.append(m.group(0))
    for m in decades:
        tok = (m.group(1) or m.group(2) or m.group(3) or m.group(4) or "").lower()
        if tok.isdigit():
            start = int(tok) if len(tok) == 4 else int(tok) + 1900
        else:
            start = _DECADE_WORD.get(tok)
        if start is None:
            continue
        if not any(str(y) in fnorm for y in range(start, start + 10)):
            bad.append(m.group(0).strip())
    # Quoted titles are concrete claims too, but only reject them when
    # there are NO verified facts (a real song often isn't in the short
    # lead, so checking quotes against a non-empty lead would
    # false-positive constantly).
    if not facts:
        for m in re.finditer(r"[\u201c\"«]([^\"\u201d»]{3,60})[\"\u201d»]", text or ""):
            bad.append("\u201c" + m.group(1) + "\u201d")
    return bad


def _strip_sentences_with(text, bad_tokens):
    """Drop sentences containing any of `bad_tokens` (accent-insensitive)."""
    kept = []
    for sent in re.split(r"(?<=[.!?])\s+", (text or "").strip()):
        low = _wiki_norm(sent)
        if any(_wiki_norm(t).strip("\u201c\u201d\"") in low for t in bad_tokens if t.strip("\u201c\u201d\"")):
            continue
        kept.append(sent)
    return " ".join(kept).strip()


def _safe_post_from_facts(topic, facts):
    """Generic, verifiably-true fallback post, used when the gated text
    can't be salvaged. Built only from the verified lead (first sentence)
    or, with no facts at all, from no concrete claims whatsoever."""
    if facts:
        first = re.split(r"\.\s+", facts.strip(), maxsplit=1)[0].strip()
        first = first if first.endswith(".") else first + "."
        if len(first) > 280:
            first = first[:277].rsplit(" ", 1)[0] + "."
        return first + " ¿Cuál es tu canción favorita de " + topic + "?"
    return (
        "Hoy suena " + topic + " en Lo Mejor del Rock en Español. "
        "Una banda para redescubrir con calma y a todo volumen. "
        "¿Cuál es tu canción favorita de " + topic + "?"
    )


# ---------------------------------------------------------------------------
# Content generators
# ---------------------------------------------------------------------------

def gen_original(client, state, band):
    chosen      = pick_original_type(state)
    image_query = get_image_query(band)
    facts = get_wikipedia_facts(band)
    if facts:
        facts_block = (
            "DATOS VERIFICADOS sobre " + band + " (fuente: Wikipedia \u2014 tu \u00daNICA fuente de hechos):\n"
            + facts + "\n"
            "REGLA: todo nombre, fecha, \u00e1lbum, canci\u00f3n e integrante debe salir de estos datos. "
            "Lo que no aparezca aqu\u00ed, NO lo inventes: usa frases generales sin datos concretos.\n\n"
        )
    else:
        facts_block = (
            "No se encontraron datos verificados sobre " + band + ". "
            "REGLA: NO inventes nombres, fechas, \u00e1lbumes, canciones ni integrantes. "
            "Escribe solo afirmaciones generales y verdaderas.\n\n"
        )
    prompt = (
        "Genera un post tipo " + chosen["type"].upper() + " sobre: " + band + "\n"
        "Instrucción: " + chosen["instruction"] + "\n\n"
        + facts_block +
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
    """Generate ONE post, with auto-update / no-repeat protection.

    A candidate is first tried against posts.json (published or pending)
    and bot_state.json: if its FINAL topic + post type, or its final
    text hash, already appears, it is regenerated with a different band,
    up to 3 attempts. But a repeat is NOT a blocker: if all 3 attempts
    are repeats, the latest generated version is published anyway, so
    the bot never stalls with an empty queue. Content still auto-updates
    over time because each run regenerates fresh text with Groq and the
    band/year rotation advances on every run.
    """
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    state = load_state()
    client = Groq(api_key=os.getenv("GROQ" + "_API_KEY"))

    # Blocked set: everything already queued or published, plus state history.
    queue_before = load_queue()
    blocked_topics = set()
    blocked_hashes = set(state.get("used_text_hashes", [])[-200:])
    for _p in queue_before:
        if _p.get("topic") and _p.get("status") in ("published", "pending"):
            blocked_topics.add(topic_key(_p["topic"], _p.get("post_type", "")))
        if _p.get("text"):
            blocked_hashes.add(text_hash(_p["text"]))
        if _p.get("text_hash"):
            blocked_hashes.add(_p["text_hash"])
    for _t in state.get("used_topics", [])[-100:]:
        if isinstance(_t, str):
            blocked_topics.add(_t)

    accepted = None
    last_candidate = None
    for attempt in range(3):
        post_type = pick_post_type(state)
        band = pick_band(state)

        print("[" + now.isoformat() + "] Generating ONE post (attempt %d)..." % (attempt + 1))
        print("  Post type : " + post_type)
        print("  Band/topic: " + band)

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

        import re as _re
        years_found = _re.findall(r"\b(19[5-9]\d|20[0-2]\d)\b", data.get("text", ""))
        post_year = data.get("post_year", years_found[0] if years_found else "")
        actual_type = data.get("post_type", post_type)
        verified_text = verify_and_normalize_post(
            client,
            topic=data.get("topic", band),
            post_type=actual_type,
            text=data.get("text", ""),
            facts=get_wikipedia_facts(data.get("topic", band)),
        ).rstrip()
        video_url = data.get("video_url")
        if video_url and video_url not in verified_text:
            verified_text = verified_text.rstrip() + "\n\n" + video_url
        # 2026-11-06: hashtags from the VERIFIED text, not the pre-verification
        # draft. Extra tags used to come from substring matches over the draft,
        # computed BEFORE verify_and_normalize_post ran — so a passing mention
        # the verifier stripped still left its tag behind (La Ley post, Nov 6:
        # #GustavoCerati with Cerati nowhere in the published text). Matching
        # against verified_text keeps legitimate multi-band tags (a Soda vs
        # Maná duelo still tags both) while orphan tags disappear.
        extra_mentions = [b for b in BANDS if b in verified_text and b != data.get("topic", band)]
        # 2026-11-09: topic-tag guardrail. The topic band comes from the
        # rotation (pick_band) and for polls it is unrelated to the poll
        # question — gen_poll writes about the question's options, not the
        # picked band — so the body can never name it (Nov 9 Desorden
        # Público poll: all Soda Stereo / Héroes del Silencio / Maná,
        # #DesordenPublico orphaned; same pattern Nov 6 #LosPrisioneros
        # and the Nov 7 Soda vs Maná poll). A tag for a band the post
        # never names is misleading, so drop just the topic tag; bands
        # the body DOES name keep their tags via extra_mentions.
        # Accent-insensitive (_wiki_norm), so "Heroes" in the text still
        # counts as "Héroes del Silencio". Applies to every post type:
        # it is a no-op whenever the body names its topic band, and it
        # also catches drift in non-poll posts (e.g. a verifier strip
        # that removed the topic mention).
        topic_band = data.get("topic", band)
        topic_mentioned = _wiki_norm(topic_band) in _wiki_norm(verified_text)
        if not topic_mentioned:
            print("  Topic tag dropped: %s never named in verified text." % topic_band)
        hashtags = build_hashtags(topic_band, extra_tags=extra_mentions[:3], post_type=actual_type,
                                  include_band_tag=topic_mentioned)
        final_text = verified_text.rstrip() + hashtags
        final_topic = data.get("topic", band)
        tkey = topic_key(final_topic, actual_type)
        thash = text_hash(final_text)

        last_candidate = (actual_type, final_topic, final_text, data, post_year, thash, tkey)
        if tkey in blocked_topics or thash in blocked_hashes:
            print("  Duplicate detected: %s / %s already published or queued — trying another band" % (final_topic, actual_type))
            blocked_topics.add(tkey)
            blocked_hashes.add(thash)
            continue

        accepted = last_candidate
        break

    if not accepted:
        if last_candidate is None:
            # Nothing was generated at all — there is nothing to publish.
            print("  No post was generated — saving nothing to the queue.")
            save_state(state)
            return
        # Auto-update, not auto-block: the user wants fresh posts over
        # time, but publishing a repeat is better than publishing nothing.
        # Freshness is a preference (try 3 different bands first), not a
        # blocker. The text itself is newly generated by Groq each run,
        # and the rotation state advances, so content still updates over
        # time even when a band repeats.
        print("  All 3 attempts were repeats — publishing the latest generated version anyway.")
        accepted = last_candidate

    actual_type, final_topic, final_text, data, post_year, thash, tkey = accepted
    entry = {
        "id":           "post_" + stamp,
        "status":       "pending",
        "created_at":   now.isoformat(),
        "post_type":    actual_type,
        "topic":        final_topic,
        "text":         final_text,
        "text_hash":    thash,
        "image_query":  data.get("image_query", get_image_query(final_topic)),
        "extra_topics": [b for b in BANDS if b in final_text and b != final_topic][:4],
        "post_year":    post_year,
        "curation_year": str(state.get("curation_year", "")) if state.get("curation_year") else "",
        "video_url":    data.get("video_url"),
        "concert_url":  data.get("concert_url"),
        "fb_post_id":   None,
        "ig_post_id":   None,
        "threads_post_id": None,
        "youtube_post_url": None,
        "published_at": None,
        "error":        None,
    }

    # Auto-update state with the FINAL topic/text, not just the picked band.
    # Cover/concert/hoy posts change topic after pick_band, so record both.
    state["used_topics"] = (state.get("used_topics", []) + [tkey])[-100:]
    state["used_text_hashes"] = (state.get("used_text_hashes", []) + [thash])[-200:]
    if final_topic not in state.get("used_bands", []):
        state["used_bands"] = (state.get("used_bands", []) + [final_topic])[-20:]

    queue = load_queue()
    queue.append(entry)
    # Prune history, but NEVER drop a pending post: drop the oldest
    # non-pending entries first so a backed-up queue cannot lose a post.
    while len(queue) > 200:
        _idx = next((i for i, _p in enumerate(queue) if _p.get("status") != "pending"), None)
        if _idx is None:
            break
        queue.pop(_idx)
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
