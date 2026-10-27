"""
make_reel.py
------------
Generates a 60-second Facebook/Instagram Reel — 100% free:
  1. Groq  → writes Spanish script
  2. Kokoro → converts to Spanish voiceover (free, local, no API key)
  3. Wikimedia Commons → actual photos of the band (new, 2026-10-26)
  4. MoviePy → assembles 9:16 vertical Reel (photo slideshow, Ken Burns)

Output: reels/reel_YYYYMMDD.mp4  — download from GitHub Actions artifacts,
        upload to Facebook/Instagram manually (takes ~5 minutes)

Run manually:  python make_reel.py
Runs via cron: every day at 09:00 UTC (GitHub Actions)

2026-10-26, user decision: STOP chasing YouTube downloads. YouTube
footage from GitHub Actions IPs is bot-blocked even with cookies and
ios/tv clients, and Pexels stock is generic, not the band. The reel
now uses actual band photos first (Wikimedia Commons, freely licensed),
with Pexels video as fallback only when Commons has too few usable
photos. YouTube download code stays in the file but is no longer
called from make_reel().
"""

import os
import random
import requests
import tempfile
import shutil
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from groq import Groq

try:
    from find_video import get_video_for_topic
except Exception:
    get_video_for_topic = None

load_dotenv()

# Strip: a pasted GitHub secret with a trailing newline breaks HTTP
# headers — Pexels failed 2026-10-25 with "Invalid leading whitespace
# ... in header value" because PEXELS_KEY was not stripped.
GROQ_API_KEY  = (os.getenv("GROQ_API_KEY") or "").strip()
PEXELS_KEY    = (os.getenv("PEXELS_API_KEY") or "").strip()
YOUTUBE_API_KEY = (os.getenv("YOUTUBE_API_KEY") or "").strip()

OUTPUT_DIR = Path("reels")
OUTPUT_DIR.mkdir(exist_ok=True)

# Reel topics — rotated by calendar day so daily runs get variety
REEL_TOPICS = [
    {"topic": "Soda Stereo",              "search": "rock concert argentina crowd",   "angle": "el legado eterno de Soda Stereo"},
    {"topic": "Heroes del Silencio",      "search": "rock band spain concert stage",  "angle": "el fenómeno de Heroes del Silencio"},
    {"topic": "Maná",                     "search": "latin rock concert mexico city", "angle": "por qué Maná es el rey del rock mexicano"},
    {"topic": "Café Tacvba",              "search": "alternative rock concert band",  "angle": "los más originales del rock en español"},
    {"topic": "Molotov",                  "search": "punk rock concert energy crowd", "angle": "la banda más explosiva del rock en español"},
    {"topic": "Gustavo Cerati",           "search": "guitarist electric guitar solo", "angle": "el genio que cambió el rock en español"},
    {"topic": "rock en español años 90",  "search": "rock concert 90s nostalgia",     "angle": "la época dorada del rock en español"},
    {"topic": "Los Fabulosos Cadillacs",  "search": "ska rock concert argentina",     "angle": "ska + rock = Los Fabulosos Cadillacs"},
    {"topic": "Caifanes",                 "search": "gothic rock concert mexico",     "angle": "Caifanes, la banda más oscura y brillante"},
    {"topic": "Bunbury",                  "search": "rock singer spain concert tour", "angle": "Bunbury, el eterno rebelde del rock"},
    {"topic": "Divididos",                "search": "rock band argentina concert",    "angle": "el rock más puro de Argentina"},
    {"topic": "La Ley",                   "search": "rock band chile concert stage",  "angle": "La Ley y el rock chileno en su mejor momento"},
]

SCRIPT_SYSTEM = """Eres el guionista de "Mejor Rock en Español".
Escribes guiones cortos y apasionantes para Reels de 60 segundos.

ESTRUCTURA OBLIGATORIA:
- Gancho inicial (5 seg): frase impactante que engancha de inmediato
- Desarrollo (40 seg): 3-4 datos fascinantes e interesantes
- Cierre (10 seg): pregunta que invite a comentar

REGLAS:
- Español conversacional y energético
- NUNCA copies letras de canciones
- Sin indicaciones de escena, sin paréntesis, solo el texto a narrar
- EXACTAMENTE entre 130 y 150 palabras"""


def pick_topic() -> dict:
    now = datetime.now(timezone.utc)
    # One topic per UTC day (not one per ISO week), so daily workflow stays varied.
    day_index = int(now.timestamp() // 86400)
    return REEL_TOPICS[day_index % len(REEL_TOPICS)]


# TTS-only pronunciation fixes (2026-10-25, user request: correct band
# name pronunciation). Applied ONLY to the voiceover text, never to the
# saved script file or the reel caption, so captions keep the correct
# spelling (e.g. Tacvba, Cadillacs) while the voice says the name the
# way fans say it. Longest names first, so "Café Tacvba" is replaced
# before the bare "Tacvba" rule.
TTS_PRONUNCIATION = {
    "Café Tacvba": "Café Tacuba",
    "Tacvba": "Tacuba",
    "Los Fabulosos Cadillacs": "Los Fabulosos Cadilacs",
    "Cadillacs": "Cadilacs",
    "Héroes del Silencio": "Éroes del Silencio",
}


def _apply_tts_pronunciation(text: str) -> str:
    for name in sorted(TTS_PRONUNCIATION, key=len, reverse=True):
        text = text.replace(name, TTS_PRONUNCIATION[name])
    return text


def generate_script(topic_data: dict) -> str:
    client = Groq(api_key=GROQ_API_KEY)
    prompt = (
        f"Escribe un guión de Reel de 60 segundos sobre: {topic_data['topic']}\n"
        f"Ángulo: {topic_data['angle']}\n\n"
        f"OBLIGATORIO: escribe EXACTAMENTE entre 140 y 155 palabras. "
        f"Cuenta las palabras antes de responder. "
        f"Si tienes menos de 140 palabras, agrega más detalles y ejemplos. "
        f"Solo el texto a narrar, sin indicaciones de escena."
    )
    # Same fallback chain as generate.py: gpt-oss-120b can return empty
    # content, and older models were retired on Groq. Try each model in
    # order and return the first non-empty script; an empty script must
    # never reach TTS, because Kokoro then returns no audio and the
    # whole reel run produces no mp4 (seen 2026-10-25).
    for model in ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"):
        try:
            completion = client.chat.completions.create(
                model       = model,
                messages    = [
                    {"role": "system", "content": SCRIPT_SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
                temperature = 0.85,
                max_tokens  = 400,
            )
            text = (completion.choices[0].message.content or "").strip()
            if text:
                return text
            print(f"  Groq {model} returned empty script, trying next model...")
        except Exception as e:
            print(f"  Groq {model} failed: {e}, trying next model...")
    return ""


def text_to_speech_kokoro(script: str, output_path: str) -> str | None:
    """
    Generate Spanish voiceover using Kokoro TTS.
    Kokoro is 100% free, open-source, runs locally — no API key needed.
    Install: pip install kokoro soundfile
    Kokoro supports Spanish with the 'es' language code.
    """
    # Voiceover text only: pronounce band names correctly, keep the
    # written script/caption spelling unchanged (see TTS_PRONUNCIATION).
    script = _apply_tts_pronunciation(script)
    try:
        from kokoro import KPipeline
        import soundfile as sf
        import numpy as np

        print("  Loading Kokoro TTS (first run downloads ~500MB model)...")
        pipeline = KPipeline(lang_code="es")   # Spanish

        # Generate audio — Kokoro returns audio chunks
        audio_chunks = []
        for chunk in pipeline(script, voice="ef_dora"):  # Spanish female voice
            if chunk.audio is not None:
                audio_chunks.append(chunk.audio)

        if not audio_chunks:
            print("  Kokoro returned no audio. Falling back to gTTS...")
            return text_to_speech_gtts(script, output_path)

        # Concatenate chunks and save as WAV
        audio = np.concatenate(audio_chunks)
        sf.write(output_path, audio, 24000)
        print(f"  Audio saved: {output_path}")
        return output_path

    except ImportError:
        print("  Kokoro not installed. Run: pip install kokoro soundfile")
        print("  Falling back to gTTS (Google TTS, also free)...")
        return text_to_speech_gtts(script, output_path)
    except Exception as e:
        print(f"  Kokoro error: {e}")
        print("  Falling back to gTTS...")
        return text_to_speech_gtts(script, output_path)


def text_to_speech_gtts(script: str, output_path: str) -> str | None:
    """
    Fallback: Google Text-to-Speech (gTTS) — free, no API key.
    Quality is lower than Kokoro but works everywhere.
    Install: pip install gtts
    """
    script = _apply_tts_pronunciation(script)
    try:
        from gtts import gTTS
        # gTTS always outputs MP3 bytes. Do NOT save them to a .wav path.
        # Use .mp3 so downstream (MoviePy) can decode correctly.
        mp3_path = output_path
        if mp3_path.lower().endswith(".wav"):
            mp3_path = mp3_path[:-4] + ".mp3"
        tts = gTTS(text=script, lang="es", slow=False)
        tts.save(mp3_path)
        print(f"  Audio saved via gTTS: {mp3_path}")
        return mp3_path
    except ImportError:
        print("  gTTS not installed. Run: pip install gtts")
        return None
    except Exception as e:
        print(f"  gTTS error: {e}")
        return None


def get_pexels_videos(query: str, count: int = 6) -> list:
    if not PEXELS_KEY:
        print("  PEXELS_API_KEY not set.")
        return []
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": PEXELS_KEY},
            params={
                "query":       query,
                "per_page":    15,
                "orientation": "portrait",
                "size":        "medium",
            },
            timeout=15,
        )
        r.raise_for_status()
        videos = r.json().get("videos", [])
        urls = []
        sample = random.sample(videos, min(count, len(videos)))
        for v in sample:
            files = sorted(
                [f for f in v["video_files"] if f.get("quality") in ("hd", "sd")],
                key=lambda x: x.get("width", 0),
            )
            if files:
                # Prefer the highest-resolution variant for better final quality.
                urls.append(files[-1]["link"])
        return urls
    except Exception as e:
        print(f"  Pexels video error: {e}")
        return []


def download_file(url: str, path: str) -> bool:
    try:
        r = requests.get(
            url, timeout=60, stream=True,
            headers={"User-Agent": "rock_bot/1.0 (Lo Mejor del Rock en Espanol)"},
        )
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"  Download error: {e}")
        return False


def get_wikimedia_photos(topic: str, count: int = 6, sources_path=None) -> list:
    """Actual photos of the band from Wikimedia Commons (freely licensed).

    2026-10-26, user decision: stop chasing YouTube downloads, use
    actual photos instead of Pexels stock or YouTube video. Commons
    is the legal source for this: its photos are CC-licensed or public
    domain, unlike official YouTube footage or promotional photos
    scraped from Google/Instagram, which would be copyrighted.
    Returns local file paths (downloaded into reels/), plus a sources
    file with title/URL/license per photo for attribution, when
    sources_path is given. Returns [] when Commons has too few usable
    photos, so the caller can fall back to Pexels video.
    """
    headers = {"User-Agent": "rock_bot/1.0 (Lo Mejor del Rock en Espanol; https://www.tiktok.com/@mejorrockespanol)"}
    photos = []
    sources = []
    seen_urls = set()
    queries = [f"{topic} band", f"{topic} concert", topic]
    for query in queries:
        if len(photos) >= count:
            break
        try:
            r = requests.get(
                "https://commons.wikimedia.org/w/api.php",
                headers=headers,
                params={
                    "action": "query",
                    "format": "json",
                    "formatversion": "2",
                    "generator": "search",
                    "gsrnamespace": "6",
                    "gsrsearch": query,
                    "gsrlimit": "20",
                    "prop": "imageinfo",
                    "iiprop": "url|size|mime|extmetadata",
                    "iiurlwidth": "1600",
                },
                timeout=20,
            )
            r.raise_for_status()
            pages = r.json().get("query", {}).get("pages", []) or []
        except Exception as e:
            print(f"  Wikimedia search error ({query}): {e}")
            continue
        for page in pages:
            if len(photos) >= count:
                break
            info_list = page.get("imageinfo") or []
            if not info_list:
                continue
            info = info_list[0]
            mime = info.get("mime", "")
            width = info.get("width", 0)
            height = info.get("height", 0)
            title = page.get("title", "")
            low = title.lower()
            if mime not in ("image/jpeg", "image/png"):
                continue
            if width < 900 or height < 600:
                continue
            if any(bad in low for bad in ("logo", "icon", "album cover", "single cover", "signature")):
                continue
            # Prefer the 1600px thumb when available (smaller download,
            # still plenty for 1080x1920), else the original URL.
            url = info.get("thumburl") or info.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            ext = ".jpg" if mime == "image/jpeg" else ".png"
            slug = "".join(c if c.isalnum() else "_" for c in topic)[:20]
            local = OUTPUT_DIR / f"photo_{slug}_{len(photos)}.jpg" if ext == ".jpg" else OUTPUT_DIR / f"photo_{slug}_{len(photos)}.png"
            if download_file(url, str(local)):
                photos.append(str(local))
                meta = info.get("extmetadata") or {}
                lic = (meta.get("LicenseShortName") or {}).get("value", "unknown")
                artist = (meta.get("Artist") or {}).get("value", "")
                sources.append(f"{title} | {url} | License: {lic} | Artist: {artist}")
                print(f"    Photo {len(photos)} OK: {title}")
    if sources_path and sources:
        try:
            Path(sources_path).write_text("\n".join(sources) + "\n", encoding="utf-8")
        except Exception:
            pass
    return photos


_TEMP_COOKIES_PATH = None
_COOKIES_LOGGED = False


def _youtube_cookies_path():
    """Return a cookies.txt path for yt-dlp, or None.

    2026-10-26: android/web player clients alone do NOT beat YouTube's
    bot check from GitHub Actions runner IPs (all 10 videos blocked on
    2026-10-26, three runs in a row). The yt-dlp-recommended fix is
    cookies from a real browser session. Two ways to supply them,
    never in chat and never logged:
      - YOUTUBE_COOKIES_FILE: path to a cookies.txt file on disk.
      - YOUTUBE_COOKIES: the cookies.txt content itself, passed as a
        GitHub Actions secret into the workflow env. It is written to
        a temp file here (never committed, never printed) and deleted
        after the YouTube clip loop finishes.
    Without either, downloads will keep failing from CI and the reel
    falls back to Pexels stock, which is expected, not a code bug.
    """
    global _TEMP_COOKIES_PATH, _COOKIES_LOGGED
    cookies_file = os.getenv("YOUTUBE_COOKIES_FILE", "").strip()
    if cookies_file and os.path.exists(cookies_file):
        if not _COOKIES_LOGGED:
            print("  Using YouTube cookies from file (values never logged).")
            _COOKIES_LOGGED = True
        return cookies_file
    cookies_content = os.getenv("YOUTUBE_COOKIES", "")
    if cookies_content.strip():
        if _TEMP_COOKIES_PATH is None:
            import tempfile
            fd, tmp = tempfile.mkstemp(prefix="youtube_cookies_", suffix=".txt")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(cookies_content)
            _TEMP_COOKIES_PATH = tmp
        if not _COOKIES_LOGGED:
            print("  Using YouTube cookies from secret (values never logged).")
            _COOKIES_LOGGED = True
        return _TEMP_COOKIES_PATH
    if not _COOKIES_LOGGED:
        print("  No YouTube cookies configured — CI runner IPs are bot-blocked, expect Pexels fallback.")
        _COOKIES_LOGGED = True
    return None


def _cleanup_youtube_cookies():
    global _TEMP_COOKIES_PATH
    if _TEMP_COOKIES_PATH and os.path.exists(_TEMP_COOKIES_PATH):
        try:
            os.remove(_TEMP_COOKIES_PATH)
        except Exception:
            pass
    _TEMP_COOKIES_PATH = None


def download_youtube_video(video_url: str, output_path: str) -> bool:
    if get_video_for_topic is None:
        print("  YouTube download helper unavailable.")
        return False
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        print("  yt-dlp not installed. Install with: pip install yt_dlp")
        return False

    print(f"  Downloading YouTube footage: {video_url}")
    # 2026-10-25: default web client hit YouTube's "Sign in to confirm
    # you're not a bot" check from GitHub Actions IPs, so the download
    # failed and the reel fell back to Pexels. Android client is far
    # less likely to hit that check, and needs no cookies.
    # 2026-10-26: android/web also blocked from CI IPs, and cookies
    # alone (22:15 UTC run, "Using YouTube cookies from secret") also
    # did NOT unblock CI downloads. YouTube now also enforces a PO
    # token for many clients, which cookies do not provide. Adding
    # ios/tv clients as well is the next cheap test: yt-dlp tries
    # clients in order, and ios/tv have historically needed less
    # verification. If this still fails, the remaining CI options
    # are a PO-token provider or a residential proxy, both heavy,
    # or accepting Pexels stock — not another client shuffle.
    ydl_opts = {
        "format": "best[ext=mp4]+bestaudio/best",
        "outtmpl": output_path,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "merge_output_format": "mp4",
        "extractor_args": {"youtube": {"player_client": ["android", "ios", "web", "tv"]}},
    }
    cookies_path = _youtube_cookies_path()
    if cookies_path:
        ydl_opts["cookiefile"] = cookies_path
    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        return os.path.exists(output_path)
    except Exception as e:
        print(f"  yt-dlp error: {e}")
        return False


def get_youtube_clips(topic: str, count: int = 2) -> list:
    if get_video_for_topic is None:
        return []
    clips = []
    used_ids = []
    # Try extra videos: a single bot-blocked download must not kill the
    # whole YouTube path (old code used break, so one failure fell back
    # to Pexels even when other videos would have downloaded).
    for _ in range(count + 4):
        if len(clips) >= count:
            break
        video = get_video_for_topic(topic, used_ids)
        if not video:
            break
        video_id = video["url"].split("v=")[-1].split("&")[0]
        used_ids.append(video_id)
        filename = OUTPUT_DIR / f"yt_clip_{video_id}.mp4"
        if filename.exists() or download_youtube_video(video["url"], str(filename)):
            clips.append(str(filename))
        else:
            continue
    # Temp cookies file (from YOUTUBE_COOKIES secret content) must not
    # linger on disk after the run. A user-supplied YOUTUBE_COOKIES_FILE
    # path is never deleted — only the temp file we created is.
    _cleanup_youtube_cookies()
    return clips


def assemble_reel(audio_path: str, video_urls: list, output_path: str) -> bool:
    try:
        # Patch Pillow ANTIALIAS removal (Pillow 10+ removed it, MoviePy 1.0.3 needs it)
        import PIL.Image as _PILImage
        if not hasattr(_PILImage, "ANTIALIAS"):
            _PILImage.ANTIALIAS = _PILImage.LANCZOS

        from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips, CompositeAudioClip

        TARGET_W, TARGET_H = 1080, 1920

        narration_audio = AudioFileClip(audio_path)
        # Do NOT add +1.0 here: the 2026-10-25 run set video/narration
        # duration to narration+1 (57.4s) while the wav itself was ~56s,
        # and MoviePy failed reading audio at t=56.35-56.40 with
        # "clip duration=56 seconds". Video length must never exceed
        # the actual narration file length.
        duration = narration_audio.duration
        print(f"  Narration duration: {duration:.1f}s")

        # Download clips to a permanent temp folder (avoids Windows file-locking issue)
        clips_dir = OUTPUT_DIR / "tmp_clips"
        clips_dir.mkdir(exist_ok=True)
        clip_paths = []

        for i, src in enumerate(video_urls):
            if src.startswith("http://") or src.startswith("https://"):
                tmp = str(clips_dir / f"clip_{i}.mp4")
                if download_file(src, tmp):
                    clip_paths.append(tmp)
            elif os.path.exists(src):
                clip_paths.append(src)
            else:
                print(f"    Skipping invalid source: {src}")

        clips = []
        for i, path in enumerate(clip_paths):
            try:
                is_photo = path.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                if is_photo:
                    # Photo slideshow (2026-10-26): actual band photos,
                    # not video. Static 10s per photo, hard cuts, no
                    # clip audio — narration carries the reel. Ken Burns
                    # zoom is intentionally NOT done here: a
                    # time-varying resize changes frame size mid-clip
                    # and breaks MoviePy concatenate in CI. A stable
                    # slideshow is the reliable v1; zoom/crossfade can
                    # be added later only if this version proves out.
                    from moviepy.editor import ImageClip
                    clip = ImageClip(path)
                    clip = clip.set_duration(10.0)
                else:
                    clip = VideoFileClip(path)
                ratio = clip.w / clip.h
                tgt   = TARGET_W / TARGET_H
                if ratio > tgt:
                    new_w = int(clip.h * tgt)
                    clip  = clip.crop(x1=(clip.w - new_w) // 2, width=new_w)
                else:
                    new_h = int(clip.w / tgt)
                    clip  = clip.crop(y1=(clip.h - new_h) // 2, height=new_h)
                clip = clip.resize((TARGET_W, TARGET_H))
                if not is_photo:
                    clip = clip.subclip(0, min(clip.duration, 10.0))
                clips.append(clip)
                print(f"    Clip {i} OK ({clip.duration:.1f}s, {'photo' if is_photo else 'video'})")
            except Exception as e:
                print(f"    Clip {i} error: {e}")

        if not clips:
            print("  No valid clips — cannot assemble Reel.")
            narration_audio.close()
            shutil.rmtree(clips_dir, ignore_errors=True)
            return False

        # Loop clips to fill audio duration
        while sum(c.duration for c in clips) < duration:
            clips.extend(clips[:])
        clips = clips[:20]

        video = concatenate_videoclips(clips, method="compose")
        video = video.subclip(0, min(duration, video.duration))

        # Prefer actual clip audio when available, otherwise use narration only.
        if video.audio is not None:
            print("  Using actual clip audio with narration overlay.")
            clip_audio = video.audio.volumex(0.65)
            # Cap narration at its real length: extending an AudioFileClip
            # beyond its file length makes MoviePy read past EOF.
            narration = narration_audio.volumex(1.0).set_duration(
                min(video.duration, narration_audio.duration)
            )
            mixed_audio = CompositeAudioClip([clip_audio, narration])
            mixed_audio = mixed_audio.set_duration(video.duration)
            video = video.set_audio(mixed_audio)
        else:
            print("  No clip audio found; using narration only.")
            video = video.set_audio(narration_audio)

        video.write_videofile(
            output_path,
            fps         = 30,
            codec       = "libx264",
            audio_codec = "aac",
            audio_bitrate = "128k",
            bitrate     = "4000k",
            verbose     = False,
            logger      = None,
            # Instagram ProcessingFailedError fix attempt 2026-10-26:
            # IG requires H.264 in yuv420p (not yuv444/HDR) and AAC
            # ~128 kbps. MoviePy/ffmpeg defaults can vary by source
            # clip, so force both explicitly. Also log ffprobe streams
            # after writing, so the next run's log shows the exact
            # codec/pixel-format/sample-rate IG received.
            ffmpeg_params = ["-pix_fmt", "yuv420p"],
        )
        video.close()
        narration_audio.close()
        try:
            import subprocess
            probe = subprocess.run(
                ["ffprobe", "-hide_banner", output_path],
                capture_output=True, text=True, timeout=30,
            )
            print(f"  Reel ffprobe:\n{probe.stderr.strip()}")
        except Exception as e:
            print(f"  ffprobe skipped: {e}")

        # Clean up temp clips after MoviePy has fully released file handles
        shutil.rmtree(clips_dir, ignore_errors=True)
        return True

    except ImportError:
        print("  MoviePy not installed. Run: pip install moviepy==1.0.3")
        return False
    except Exception as e:
        print(f"  Assembly error: {e}")
        return False


def make_reel():
    now        = datetime.now(timezone.utc)
    stamp      = now.strftime("%Y%m%d")
    topic_data = pick_topic()

    print(f"[{now.isoformat()}] Making Reel: {topic_data['topic']}")
    print(f"  Angle: {topic_data['angle']}\n")

    # Step 1 — Script
    print("  Step 1: Writing script with Groq...")
    script = generate_script(topic_data)
    print(f"  Script ({len(script.split())} words):\n  {script[:120]}...\n")
    if not script:
        print("  Script generation failed on all Groq models — aborting before TTS, so the run fails loudly instead of producing an empty script and no mp4.")
        return

    script_path = OUTPUT_DIR / f"reel_{stamp}_script.txt"
    script_path.write_text(
        f"Topic: {topic_data['topic']}\nAngle: {topic_data['angle']}\n\n{script}",
        encoding="utf-8"
    )

    # Step 2 — TTS (Kokoro first, gTTS fallback)
    audio_path = str(OUTPUT_DIR / f"reel_{stamp}_audio.wav")
    print("  Step 2: Generating Spanish voiceover (Kokoro TTS)...")
    audio_file = text_to_speech_kokoro(script, audio_path)

    if not audio_file:
        print("  Audio generation failed. Script saved for manual recording.")
        print(f"  Script: {script_path}")
        return

    # Step 3 — Visuals, new order 2026-10-26 (user decision):
    # 1) Actual band photos from Wikimedia Commons (freely licensed).
    # 2) Pexels stock video, ONLY if Commons has fewer than 3 usable photos.
    # YouTube downloads are DISABLED here on purpose — CI downloads
    # are bot-blocked even with cookies and ios/tv clients, and chasing
    # them further wastes every run. get_youtube_clips() stays in the
    # file, unused, in case a future PO-token/proxy solution revives it.
    print(f"\n  Step 3: Looking for actual photos of '{topic_data['topic']}'...")
    print("  YouTube footage disabled per user decision 2026-10-26 — using photos instead.")
    sources_path = OUTPUT_DIR / f"reel_{stamp}_photos.txt"
    video_urls = get_wikimedia_photos(topic_data["topic"], count=6, sources_path=str(sources_path))
    if len(video_urls) >= 3:
        print(f"  Found {len(video_urls)} actual band photo(s) on Wikimedia Commons. Sources: {sources_path}")
    else:
        if video_urls:
            print(f"  Only {len(video_urls)} usable Commons photo(s) — falling back to Pexels video, so the reel still assembles.")
        else:
            print("  No usable Commons photos — falling back to Pexels video.")
        video_urls = []
        print(f"  Step 3 fallback: Fetching Pexels clips ('{topic_data['search']}')...")
        video_urls = get_pexels_videos(topic_data["search"], count=6)
        print(f"  Found {len(video_urls)} stock clips.")

    if not video_urls:
        print("  No photos or clips found. Audio saved — edit manually in CapCut.")
        return

    # Step 4 — Assemble
    output_path = str(OUTPUT_DIR / f"reel_{stamp}.mp4")
    print(f"\n  Step 4: Assembling Reel with MoviePy...")
    ok = assemble_reel(audio_file, video_urls, output_path)

    if ok:
        mb = os.path.getsize(output_path) / 1024 / 1024
        print(f"\n  Reel ready: {output_path} ({mb:.1f} MB)")
        print(f"  Script:     {script_path}\n")

        # Step 5 — Upload to YouTube as a Short
        # CI: set GitHub secrets YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
        _yt_ci = _youtube_env_configured()
        if os.getenv("GITHUB_ACTIONS", "").lower() == "true" and not _yt_ci:
            print(
                "  Step 5: YouTube Short skipped in Actions — add secrets "
                "YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN "
                "(run locally: python make_reel.py --auth after deleting youtube_token.json)."
            )
        else:
            print("  Step 5: Uploading to YouTube as a Short...")
            yt_url = upload_youtube_short(output_path, topic_data, script)
            if yt_url:
                print(f"  YouTube Short: {yt_url}")
            else:
                print(
                    "  YouTube Short: skipped (set env YouTube OAuth trio, or youtube_client_secret.json + youtube_token.json, or run make_reel.py --auth)"
                )

        print(f"\n  Next step: publish_reel.py handles Facebook, Instagram, X and TikTok")
        print(f"  from this same reel file. YouTube Short is Step 5 above.")
        print(f"  Manual upload is only needed if a platform step fails in publish_reel.py.")
    else:
        print(f"\n  Assembly failed. Audio at: {audio_path}")


# ---------------------------------------------------------------------------
# YouTube Shorts upload
# ---------------------------------------------------------------------------

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


def _youtube_env_configured() -> bool:
    return all(
        os.getenv(k, "").strip()
        for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    )


def _credentials_from_env() -> object | None:
    """Non-interactive OAuth for CI: refresh token + client id/secret."""
    cid = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
    csec = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
    rt = os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip()
    if not (cid and csec and rt):
        return None
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = Credentials(
            token=None,
            refresh_token=rt,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=cid,
            client_secret=csec,
            scopes=[YOUTUBE_UPLOAD_SCOPE],
        )
        creds.refresh(Request())
        return creds
    except Exception as e:
        print(f"  YouTube env credentials error: {e}")
        if "invalid_grant" in str(e):
            print("  -> invalid_grant means YOUTUBE_REFRESH_TOKEN is expired/revoked. "
                  "Fix: locally delete youtube_token.json, run python make_reel.py --auth, "
                  "and update GitHub secret YOUTUBE_REFRESH_TOKEN with the new token it prints.")
        return None


def _credentials_from_files() -> object | None:
    """Local: youtube_client_secret.json + youtube_token.json (pickle)."""
    import pickle

    client_secret_file = "youtube_client_secret.json"
    token_file = "youtube_token.json"
    if not os.path.exists(client_secret_file):
        return None
    try:
        from google.auth.transport.requests import Request

        SCOPES = [YOUTUBE_UPLOAD_SCOPE]
        creds = None
        if os.path.exists(token_file):
            with open(token_file, "rb") as f:
                creds = pickle.load(f)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                print("  YouTube auth required — run: python make_reel.py --auth")
                return None
            with open(token_file, "wb") as f:
                pickle.dump(creds, f)
        return creds
    except Exception as e:
        print(f"  YouTube file credentials error: {e}")
        return None


def upload_youtube_short(video_path, topic_data, script):
    """
    Upload the assembled Reel as a YouTube Short.
    Uses YouTube Data API v3 with OAuth2.

    **GitHub Actions:** set env `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`,
    `YOUTUBE_REFRESH_TOKEN` (get refresh token via `python make_reel.py --auth` locally).

    **Local file flow:**
    1. Save OAuth client JSON as youtube_client_secret.json
    2. Run: python make_reel.py --auth  (opens browser once)
    3. Saves youtube_token.json
    """
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        creds = _credentials_from_env() or _credentials_from_files()
        if not creds:
            return None

        youtube = build("youtube", "v3", credentials=creds)

        # Build title and description
        title       = "Lo Mejor del Rock en Español: " + topic_data["topic"] + " #Shorts"
        description = script + "\n\n#RockEnEspañol #LoMejordelRockenEspañol #Shorts #" + topic_data["topic"].replace(" ", "")

        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title":       title[:100],
                    "description": description[:5000],
                    "tags":        ["rock en español", "rock latino", topic_data["topic"], "shorts"],
                    "categoryId":  "10",   # Music
                },
                "status": {
                    "privacyStatus": "public",
                    "selfDeclaredMadeForKids": False,
                },
            },
            media_body=MediaFileUpload(video_path, chunksize=-1, resumable=True),
        )

        print("  Uploading to YouTube (this may take a minute)...")
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                print(f"    Upload: {pct}%")

        video_id = response.get("id", "")
        return "https://youtube.com/shorts/" + video_id if video_id else None

    except ImportError:
        print("  YouTube upload libs not installed. Run:")
        print("  pip install google-api-python-client google-auth-oauthlib")
        return None
    except Exception as e:
        print(f"  YouTube upload error: {e}")
        return None


def run_auth():
    """One-time OAuth flow to authorize YouTube uploads. Run: python make_reel.py --auth"""
    import pickle
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        SCOPES = [YOUTUBE_UPLOAD_SCOPE]
        flow = InstalledAppFlow.from_client_secrets_file("youtube_client_secret.json", SCOPES)
        # offline + consent so Google returns a refresh_token (needed for CI / non-interactive refresh)
        creds = flow.run_local_server(
            port=0,
            access_type="offline",
            prompt="consent",
        )
        with open("youtube_token.json", "wb") as f:
            pickle.dump(creds, f)
        print("YouTube authorization complete! Token saved to youtube_token.json\n")
        if creds.refresh_token:
            print("--- Copy into GitHub Actions secret: YOUTUBE_REFRESH_TOKEN ---")
            print(creds.refresh_token)
            print("--- Also add YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET from the same OAuth client (Google Cloud Console → Credentials). ---\n")
        else:
            print(
                "WARNING: No refresh_token returned. Delete youtube_token.json and run --auth again,\n"
                "or revoke the app's access in your Google account and retry.\n"
            )
    except Exception as e:
        print(f"Auth error: {e}")


if __name__ == "__main__":
    import sys
    if "--auth" in sys.argv:
        run_auth()
    else:
        make_reel()
