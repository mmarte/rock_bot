import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests


WDQS_URL = "https://query.wikidata.org/sparql"
CACHE_FILE = "band_universe.json"


@dataclass(frozen=True)
class BandInfo:
    name: str
    qid: str
    country: str = ""
    inception_year: str = ""
    image: str = ""          # Commons file URL if available
    wikipedia_title: str = ""  # English Wikipedia title if available


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _wdqs(query: str, timeout_s: int = 25) -> dict:
    r = requests.get(
        WDQS_URL,
        params={"format": "json", "query": query},
        headers={
            "User-Agent": "rock-bot/1.0 (https://github.com; contact: none)",
            "Accept": "application/sparql-results+json",
        },
        timeout=timeout_s,
    )
    r.raise_for_status()
    return r.json()


def fetch_band_universe(limit: int = 800) -> List[BandInfo]:
    """
    Pull a broad universe of Rock en Español artists/bands from Wikidata.

    Heuristic (strict):
    - Instance of: band / musical group / singer / musician
    - Genre: rock music (or subclasses)
    - Country: Spanish-speaking countries + Spain (hard filter to avoid non–Rock en Español bleed)
    - Prefer items with an English/Spanish label and (optionally) an enwiki article
    """
    # Notes:
    # - We intentionally keep this wide; content quality is enforced downstream by the LLM verification step.
    # - We grab a P18 image when present; it often matches the artist/band better than generic search.
    query = f"""
SELECT ?item ?itemLabel ?countryLabel ?inceptionYear ?image ?enwikiTitle WHERE {{
  VALUES ?kind {{ wd:Q215380 wd:Q5741069 wd:Q177220 wd:Q639669 }}  # band, musical group, singer, musician
  ?item wdt:P31/wdt:P279* ?kind .
  ?item wdt:P136/wdt:P279* wd:Q11399 .  # rock music (or subclass)

  # Spanish-speaking markets + Spain (keep this tight for "Rock en Español")
  VALUES ?country {{
    wd:Q29    # Spain
    wd:Q96    # Mexico
    wd:Q414   # Argentina
    wd:Q298   # Chile
    wd:Q739   # Colombia
    wd:Q419   # Peru
    wd:Q717   # Venezuela
    wd:Q77    # Uruguay
    wd:Q736   # Ecuador
    wd:Q750   # Bolivia
    wd:Q733   # Paraguay
    wd:Q800   # Costa Rica
    wd:Q774   # Guatemala
    wd:Q783   # Honduras
    wd:Q792   # El Salvador
    wd:Q811   # Nicaragua
    wd:Q804   # Panama
    wd:Q786   # Dominican Republic
    wd:Q241   # Cuba
    wd:Q1183  # Puerto Rico
  }}
  ?item wdt:P17 ?country .
  OPTIONAL {{ ?item wdt:P571 ?inception . }}
  OPTIONAL {{ ?item wdt:P18 ?image . }}
  OPTIONAL {{
    ?enwiki schema:about ?item ;
           schema:isPartOf <https://en.wikipedia.org/> ;
           schema:name ?enwikiTitle .
  }}

  BIND( IF(BOUND(?inception), STR(YEAR(?inception)), "") AS ?inceptionYear )
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "es,en". }}
}}
LIMIT {int(limit)}
"""
    data = _wdqs(query)
    infos: List[BandInfo] = []
    for row in data.get("results", {}).get("bindings", []):
        item_uri = row.get("item", {}).get("value", "")
        qid = item_uri.rsplit("/", 1)[-1] if item_uri else ""
        name = row.get("itemLabel", {}).get("value", "").strip()
        if not name or not qid:
            continue
        infos.append(
            BandInfo(
                name=name,
                qid=qid,
                country=row.get("countryLabel", {}).get("value", "").strip(),
                inception_year=row.get("inceptionYear", {}).get("value", "").strip(),
                image=row.get("image", {}).get("value", "").strip(),
                wikipedia_title=row.get("enwikiTitle", {}).get("value", "").strip(),
            )
        )

    # De-dupe by lowercase name (keep first occurrence)
    seen = set()
    deduped: List[BandInfo] = []
    for info in infos:
        k = info.name.lower()
        if k in seen:
            continue
        seen.add(k)
        deduped.append(info)
    return deduped


def save_band_universe(infos: List[BandInfo], path: str = CACHE_FILE) -> None:
    payload = {
        "generated_at": _now_iso(),
        "count": len(infos),
        "items": [asdict(i) for i in infos],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_band_universe(path: str = CACHE_FILE) -> List[BandInfo]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("items", [])
        infos: List[BandInfo] = []
        for it in items:
            if not isinstance(it, dict) or not it.get("name") or not it.get("qid"):
                continue
            infos.append(
                BandInfo(
                    name=it.get("name", ""),
                    qid=it.get("qid", ""),
                    country=it.get("country", ""),
                    inception_year=it.get("inception_year", ""),
                    image=it.get("image", ""),
                    wikipedia_title=it.get("wikipedia_title", ""),
                )
            )
        return infos
    except Exception:
        return []


def get_band_universe(refresh: bool = False, min_count: int = 200) -> List[BandInfo]:
    """
    Returns cached universe if present; otherwise fetches and caches.
    """
    cached = load_band_universe()
    if not refresh and len(cached) >= min_count:
        return cached
    try:
        infos = fetch_band_universe()
        if len(infos) >= min_count:
            save_band_universe(infos)
            return infos
    except Exception:
        pass
    return cached


def universe_name_index(infos: List[BandInfo]) -> Dict[str, BandInfo]:
    return {i.name: i for i in infos}

