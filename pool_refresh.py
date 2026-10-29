#!/usr/bin/env python3
"""
pool_refresh.py — monthly pool refresh for rock_bot. Fully automated, no API keys.

Pipeline (every run, 1st of the month via pool_refresh.yml):
  1. Usage: reads log.json, counts band/topic usage over the last 60 days
     (informational — printed in the summary).
  2. Candidates: Wikipedia category members for rock-en-espanol groups by
     country (keyless API), excluding every band already in any pool.
     Countries with the thinnest pools are served first.
  3. Reel gate: each reel candidate must yield >= 2 relevant photos via
     make_reel.get_wikimedia_photos — the exact relevance filters the reel
     pipeline uses (band name in title, band/concert/music category).
     Candidates that fail the gate never enter the pool.
  4. Writes additions to pool_additions.json (caps: 10 text bands, 5 reel
     bands per run), appends a run record to meta.runs. Additive only —
     nothing is ever removed.

Run monthly from GitHub Actions. Local: python pool_refresh.py [--dry-run]
(--dry-run does everything except writing pool_additions.json).
"""

import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent
ADDITIONS_PATH = REPO_ROOT / "pool_additions.json"
LOG_PATH = REPO_ROOT / "log.json"

MAX_TEXT_ADDITIONS = 10
MAX_REEL_ADDITIONS = 5
MAX_GATE_CHECKS = 15   # upper bound on photo-gate API work per run
USAGE_WINDOW_DAYS = 60

UA = {"User-Agent": "rock_bot-pool-refresh/1.0 (Lo Mejor del Rock en Espanol; monthly pool maintenance)"}

# Wikipedia categories (en.wikipedia) of notable rock groups by country.
# A band with a Wikipedia article is notable enough for a text post; the
# photo gate decides reel eligibility separately.
# Member counts verified 2026-10-29. Bolivian, Panamanian, Honduran and
# Dominican Republic categories returned no members and are omitted.
WIKI_CATEGORIES = {
    "Argentina": "Argentine rock music groups",
    "México": "Mexican rock music groups",
    "España": "Spanish rock music groups",
    "Chile": "Chilean rock music groups",
    "Colombia": "Colombian rock music groups",
    "Uruguay": "Uruguayan rock music groups",
    "Perú": "Peruvian rock music groups",
    "Venezuela": "Venezuelan rock music groups",
    # Thin pools (verified member counts 2026-10-29):
    "Cuba": "Cuban rock music groups",                    # 6 members
    "Costa Rica": "Costa Rican rock music groups",        # 5 members
    "El Salvador": "Salvadoran rock music groups",        # 3 members
    "Guatemala": "Guatemalan rock music groups",          # 3 members
    "Ecuador": "Ecuadorian rock music groups",            # 2 members
    "Nicaragua": "Nicaraguan rock music groups",          # 2 members
    "Paraguay": "Paraguayan rock music groups",           # 2 members
    "Puerto Rico": "Puerto Rican rock music groups",      # 10 members
}

SKIP_TITLE_PATTERNS = (
    "discography", "list of", "albums", "songs", "members",
    "tour", "filmography", "awards",
)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def clean_band_title(title: str):
    """Turn a Wikipedia article title into a display band name, or None to skip."""
    low = title.lower()
    if any(p in low for p in SKIP_TITLE_PATTERNS):
        return None
    # Strip parenthetical disambiguation: "Foo (band)" -> "Foo"
    name = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()
    if not name or len(name) < 2:
        return None
    return name


def wiki_get(params):
    for attempt in range(3):
        r = requests.get("https://en.wikipedia.org/w/api.php",
                         headers=UA, params=params, timeout=25)
        if r.status_code == 429 and attempt < 2:
            time.sleep(10)
            continue
        r.raise_for_status()
        return r.json()
    return {}


def category_members(category: str):
    """All page titles in a Wikipedia category (paginated)."""
    titles, cont = [], None
    while True:
        params = {"action": "query", "format": "json", "formatversion": "2",
                  "list": "categorymembers", "cmtitle": f"Category:{category}",
                  "cmtype": "page", "cmlimit": "500"}
        if cont:
            params["cmcontinue"] = cont
        try:
            data = wiki_get(params)
        except Exception as e:
            print(f"  category fetch error ({category}): {e}")
            break
        members = data.get("query", {}).get("categorymembers", []) or []
        titles.extend(m.get("title", "") for m in members if m.get("title"))
        cont = data.get("continue", {}).get("cmcontinue")
        if not cont:
            break
    return titles


def existing_pools():
    """Collect every band already in any pool (regex-parse, no heavy imports)."""
    text_pools = {}
    src = (REPO_ROOT / "generate.py").read_text(encoding="utf-8")
    m = re.search(r"COUNTRY_BAND_POOLS = \{(.*?)\n\}", src, re.S)
    if m:
        for cm in re.finditer(r'"([^"]+)": \[(.*?)\]', m.group(1), re.S):
            text_pools[cm.group(1)] = re.findall(r'"([^"]+)"', cm.group(2))
    reel_src = (REPO_ROOT / "make_reel.py").read_text(encoding="utf-8")
    reel_bands = set(re.findall(r'"topic":\s*"([^"]+)"', reel_src))
    if "EXPANDED_BANDS = [" in reel_src:
        _exp = reel_src.split("EXPANDED_BANDS = [", 1)[1].split("\n]\n", 1)[0]
        reel_bands.update(b for b, _c in re.findall(r'\("([^"]+)",\s*"([^"]+)"\)', _exp))
    additions = {"text": {}, "reels": []}
    if ADDITIONS_PATH.exists():
        try:
            additions = json.loads(ADDITIONS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    for country, bands in (additions.get("text") or {}).items():
        text_pools.setdefault(country, []).extend(bands)
    for entry in additions.get("reels") or []:
        if entry.get("topic"):
            reel_bands.add(entry["topic"])
    return text_pools, reel_bands, additions


def usage_report():
    """Most-used topics in log.json over the last USAGE_WINDOW_DAYS days."""
    if not LOG_PATH.exists():
        return []
    try:
        log = json.loads(LOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=USAGE_WINDOW_DAYS)).isoformat()
    counts = {}
    for e in log:
        if not isinstance(e, dict):
            continue
        if e.get("executed_at", "") < cutoff:
            continue
        t = e.get("topic")
        if t:
            counts[t] = counts.get(t, 0) + 1
    return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:8]


def photo_gate(band: str) -> bool:
    """True if the reel pipeline's own photo finder yields >= 2 relevant photos."""
    from make_reel import get_wikimedia_photos
    photos = []
    try:
        photos = get_wikimedia_photos(band, count=2) or []
    except Exception as e:
        print(f"  photo gate error ({band}): {e}")
        return False
    finally:
        for p in photos:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass
        try:
            d = REPO_ROOT / "reels"
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        except Exception:
            pass
    ok = len(photos) >= 2
    print(f"  gate {'PASS' if ok else 'FAIL'}: {band} ({len(photos)} photos)")
    return ok


def main():
    dry_run = "--dry-run" in sys.argv
    os.chdir(REPO_ROOT)

    text_pools, reel_bands, additions = existing_pools()
    known = {norm(b) for bands in text_pools.values() for b in bands}
    known |= {norm(b) for b in reel_bands}

    print("== pool refresh ==")
    used = usage_report()
    if used:
        print("Most used topics (last 60d): " +
              ", ".join(f"{t} x{c}" for t, c in used[:5]))

    # Countries thinnest-first so underrepresented scenes get candidates first.
    countries = sorted(WIKI_CATEGORIES, key=lambda c: len(text_pools.get(c, [])))
    print("Country pool sizes: " +
          ", ".join(f"{c}:{len(text_pools.get(c, []))}" for c in countries))

    text_new = {}   # country -> [bands]
    reel_candidates = []  # (band, country), thinnest-country order
    for country in countries:
        if sum(len(v) for v in text_new.values()) >= MAX_TEXT_ADDITIONS:
            break
        cat = WIKI_CATEGORIES[country]
        print(f"Scanning Category:{cat} ...")
        fresh = []
        for title in category_members(cat):
            name = clean_band_title(title)
            if name and norm(name) not in known:
                known.add(norm(name))
                fresh.append(name)
        print(f"  {len(fresh)} new candidates")
        take = fresh[:2]
        if take:
            text_new[country] = take
            reel_candidates.extend((b, country) for b in take)

    # Reel gate: same relevance bar as the reel pipeline, capped work.
    reel_new = []
    checked = 0
    for band, country in reel_candidates:
        if len(reel_new) >= MAX_REEL_ADDITIONS or checked >= MAX_GATE_CHECKS:
            break
        checked += 1
        if photo_gate(band):
            reel_new.append({"topic": band, "country": country})

    added_text = sum(len(v) for v in text_new.values())
    print(f"\nResult: +{added_text} text bands, +{len(reel_new)} reel bands"
          + (" (dry run — nothing written)" if dry_run else ""))

    run_record = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "added_text": added_text,
        "added_reels": len(reel_new),
        "gate_checked": checked,
        "text_by_country": {c: b for c, b in text_new.items()},
        "reel_bands": [e["topic"] for e in reel_new],
        "most_used_60d": [{"topic": t, "count": c} for t, c in used[:5]],
    }

    if not dry_run:
        for country, bands in text_new.items():
            additions.setdefault("text", {}).setdefault(country, []).extend(bands)
        additions.setdefault("reels", []).extend(reel_new)
        additions.setdefault("meta", {}).setdefault("runs", []).append(run_record)
        ADDITIONS_PATH.write_text(json.dumps(additions, ensure_ascii=False, indent=2)
                                  + "\n", encoding="utf-8")
        print(f"Wrote {ADDITIONS_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
