"""
find_concert.py
---------------
Searches Ticketmaster Discovery API for upcoming rock en español concerts.
Returns concert metadata for the Sunday affiliate post.

Free API key: developer.ticketmaster.com
Affiliate program (for commission links): impactradius.com → search Ticketmaster
"""

import os
import random
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

TICKETMASTER_KEY      = os.getenv("TICKETMASTER_API_KEY")
TICKETMASTER_AFFILIATE = os.getenv("TICKETMASTER_AFFILIATE_ID", "")

# Rock en español artists to search for
ARTISTS = [
    "Maná", "Soda Stereo", "Heroes del Silencio", "Café Tacvba",
    "Molotov", "Los Fabulosos Cadillacs", "Bunbury", "Caifanes",
    "La Ley", "Divididos", "Los Prisioneros", "Intocable",
    "Jarabe de Palo", "Fito Paez", "Rata Blanca", "Enrique Bunbury",
    "Vive Latino", "Festival Estéreo Picnic", "Lollapalooza Chile",
    "Lollapalooza Argentina", "rock en español",
]

# Spanish-speaking markets (country codes)
MARKETS = ["MX", "AR", "CO", "CL", "ES", "US", "PE", "VE"]


def build_affiliate_url(base_url: str) -> str:
    """Wrap a Ticketmaster URL with affiliate tracking if ID is set."""
    if not TICKETMASTER_AFFILIATE:
        return base_url
    # Ticketmaster affiliate links via Impact Radius
    return f"https://www.tkqlhce.com/click-{TICKETMASTER_AFFILIATE}-{base_url}"


def search_concerts() -> list[dict]:
    """Search Ticketmaster for upcoming rock en español concerts."""
    if not TICKETMASTER_KEY:
        return []

    now        = datetime.now(timezone.utc)
    start_date = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_date   = (now + timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")

    artist = random.choice(ARTISTS)

    try:
        r = requests.get(
            "https://app.ticketmaster.com/discovery/v2/events.json",
            params={
                "apikey":              TICKETMASTER_KEY,
                "keyword":             artist,
                "classificationName":  "music",
                "startDateTime":       start_date,
                "endDateTime":         end_date,
                "size":                10,
                "sort":                "date,asc",
            },
            timeout=10,
        )
        r.raise_for_status()
        data   = r.json()
        events = data.get("_embedded", {}).get("events", [])

        concerts = []
        for e in events:
            venue    = e.get("_embedded", {}).get("venues", [{}])[0]
            city     = venue.get("city", {}).get("name", "")
            country  = venue.get("country", {}).get("name", "")
            date_str = e.get("dates", {}).get("start", {}).get("localDate", "")
            url      = e.get("url", "")
            name     = e.get("name", "")

            if not all([name, date_str, url]):
                continue

            concerts.append({
                "name":        name,
                "date":        date_str,
                "city":        city,
                "country":     country,
                "url":         build_affiliate_url(url),
                "artist":      artist,
            })

        return concerts

    except Exception as e:
        print(f"    Ticketmaster error: {e}")
        return []


def get_concert_info() -> dict | None:
    """
    Returns info about one upcoming concert, or None if no key configured
    or no concerts found.
    """
    if not TICKETMASTER_KEY:
        return None

    concerts = search_concerts()
    if not concerts:
        # Try a second artist if first returned nothing
        concerts = search_concerts()

    if not concerts:
        return None

    return random.choice(concerts[:5])


if __name__ == "__main__":
    c = get_concert_info()
    if c:
        print(f"Concert: {c['name']}")
        print(f"Date:    {c['date']}")
        print(f"City:    {c['city']}, {c['country']}")
        print(f"URL:     {c['url']}")
    else:
        print("No concerts found (check TICKETMASTER_API_KEY in .env)")
