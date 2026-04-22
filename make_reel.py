"""
make_reel.py
------------
Generates a 60-second Facebook/Instagram Reel:
  1. Groq writes a short punchy script about a rock en español topic
  2. ElevenLabs converts it to Spanish voiceover audio
  3. Pexels finds relevant video clips
  4. MoviePy assembles audio + video into a 9:16 vertical Reel

Output: reels/reel_YYYYMMDD.mp4  — ready to upload to Facebook/Instagram manually

Run manually:  python make_reel.py
Runs via cron: every Wednesday at 09:00 UTC (GitHub Actions)

Requirements (add to requirements.txt):
  elevenlabs
  moviepy==1.0.3
  requests

Free tiers:
  ElevenLabs: 10,000 chars/month free — sign up at elevenlabs.io
  Pexels video: free with API key
"""

import os
import json
import random
import requests
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

GROQ_API_KEY      = os.getenv("GROQ_API_KEY")
ELEVENLABS_KEY    = os.getenv("ELEVENLABS_API_KEY")
PEXELS_KEY        = os.getenv("PEXELS_API_KEY")
ELEVENLABS_VOICE  = os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")  # default: Adam (Spanish)

OUTPUT_DIR = Path("reels")
OUTPUT_DIR.mkdir(exist_ok=True)

# Reel topics — rotated weekly
REEL_TOPICS = [
    {"topic": "Soda Stereo",           "search": "rock concert argentina",    "angle": "historia y legado"},
    {"topic": "Heroes del Silencio",   "search": "rock band spain concert",   "angle": "su increíble ascenso"},
    {"topic": "Maná",                  "search": "latin rock concert mexico", "angle": "los reyes del rock mexicano"},
    {"topic": "Café Tacvba",           "search": "alternative rock concert",  "angle": "los más originales del rock en español"},
    {"topic": "Molotov",               "search": "punk rock concert mexico",  "angle": "los más polémicos y geniales"},
    {"topic": "Gustavo Cerati",        "search": "guitarist electric guitar", "angle": "el genio detrás de Soda Stereo"},
    {"topic": "rock en español años 90", "search": "rock concert 1990s stage", "angle": "la época dorada"},
    {"topic": "Los Fabulosos Cadillacs", "search": "rock concert argentina band", "angle": "ska y rock perfectos"},
    {"topic": "Caifanes",              "search": "dark rock concert mexico",  "angle": "la banda más oscura y brillante"},
    {"topic": "Bunbury",               "search": "rock singer spain concert", "angle": "el eterno rebelde del rock"},
    {"topic": "Divididos",             "search": "rock band buenos aires",    "angle": "el rock más puro de Argentina"},
    {"topic": "La Ley",                "search": "rock band chile concert",   "angle": "el rock chileno en su mejor momento"},
]

SCRIPT_SYSTEM = """Eres el guionista de "Mejor Rock en Español" en Facebook e Instagram.
Escribe guiones cortos y apasionantes para Reels de 55-60 segundos.

REGLAS:
- Español conversacional y energético, como un narrador apasionado
- Estructura: gancho (5 seg) → datos fascinantes (40 seg) → pregunta final (10 seg)
- NUNCA copies letras de canciones
- Incluye 3-4 datos concretos e interesantes
- Termina con una pregunta que invite a comentar
- Entre 130 y 150 palabras EXACTAMENTE (para que dure ~60 segundos narrado)
- Sin indicaciones de escena, sin paréntesis, solo el texto a narrar"""


def pick_topic() -> dict:
    """Pick today's Reel topic based on week number for variety."""
    week = datetime.now(timezone.utc).isocalendar()[1]
    return REEL_TOPICS[week % len(REEL_TOPICS)]


def generate_script(topic_data: dict) -> str:
    """Use Groq to write a 60-second Reel script."""
    client = Groq(api_key=GROQ_API_KEY)

    prompt = (
        f"Escribe un guión de Reel de 60 segundos sobre: {topic_data['topic']}\n"
        f"Ángulo: {topic_data['angle']}\n\n"
        f"Recuerda: entre 130 y 150 palabras exactamente. "
        f"Solo el texto a narrar, sin indicaciones de escena."
    )

    completion = client.chat.completions.create(
        model       = "llama-3.3-70b-versatile",
        messages    = [
            {"role": "system", "content": SCRIPT_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        temperature = 0.85,
        max_tokens  = 400,
    )

    return completion.choices[0].message.content.strip()


def text_to_speech(script: str, output_path: str) -> bool:
    """
    Convert script to audio using ElevenLabs API.
    Returns True on success, False on failure.
    """
    if not ELEVENLABS_KEY:
        print("  ELEVENLABS_API_KEY not set — skipping audio generation.")
        return False

    try:
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE}",
            headers={
                "xi-api-key":   ELEVENLABS_KEY,
                "Content-Type": "application/json",
            },
            json={
                "text":           script,
                "model_id":       "eleven_multilingual_v2",
                "voice_settings": {
                    "stability":        0.5,
                    "similarity_boost": 0.75,
                    "style":            0.3,
                    "use_speaker_boost": True,
                },
            },
            timeout=60,
        )
        r.raise_for_status()

        with open(output_path, "wb") as f:
            f.write(r.content)

        print(f"  Audio saved: {output_path}")
        return True

    except Exception as e:
        print(f"  ElevenLabs error: {e}")
        return False


def get_pexels_videos(query: str, count: int = 5) -> list[str]:
    """
    Fetch video clip URLs from Pexels.
    Returns list of direct video URLs.
    """
    if not PEXELS_KEY:
        print("  PEXELS_API_KEY not set — no video clips.")
        return []

    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": PEXELS_KEY},
            params={
                "query":       query,
                "per_page":    15,
                "orientation": "portrait",   # 9:16 vertical for Reels
                "size":        "medium",
            },
            timeout=15,
        )
        r.raise_for_status()
        videos = r.json().get("videos", [])

        urls = []
        for v in random.sample(videos, min(count, len(videos))):
            # Pick the smallest HD file to keep things fast
            files = sorted(
                [f for f in v["video_files"] if f.get("quality") in ("hd", "sd")],
                key=lambda x: x.get("width", 0),
            )
            if files:
                urls.append(files[0]["link"])

        return urls

    except Exception as e:
        print(f"  Pexels video error: {e}")
        return []


def download_file(url: str, path: str) -> bool:
    """Download a file from URL to local path."""
    try:
        r = requests.get(url, timeout=60, stream=True)
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"  Download error: {e}")
        return False


def assemble_reel(audio_path: str, video_urls: list[str], output_path: str) -> bool:
    """
    Assemble final Reel using MoviePy.
    Stacks video clips vertically (9:16), overlays audio, outputs MP4.
    """
    try:
        from moviepy.editor import (
            VideoFileClip, AudioFileClip, concatenate_videoclips,
            ColorClip, CompositeVideoClip
        )
        import tempfile

        # Target dimensions for Reels (9:16 vertical)
        TARGET_W = 1080
        TARGET_H = 1920

        # Get audio duration to know how long the reel should be
        audio     = AudioFileClip(audio_path)
        duration  = audio.duration + 1.0   # 1 second buffer at end

        print(f"  Audio duration: {duration:.1f}s")

        # Download and prepare video clips
        clips     = []
        tmp_files = []

        with tempfile.TemporaryDirectory() as tmpdir:
            for i, url in enumerate(video_urls):
                tmp_path = os.path.join(tmpdir, f"clip_{i}.mp4")
                if download_file(url, tmp_path):
                    try:
                        clip = VideoFileClip(tmp_path)

                        # Crop to 9:16 aspect ratio
                        clip_ratio  = clip.w / clip.h
                        target_ratio = TARGET_W / TARGET_H

                        if clip_ratio > target_ratio:
                            # Wider than target — crop sides
                            new_w = int(clip.h * target_ratio)
                            x1    = (clip.w - new_w) // 2
                            clip  = clip.crop(x1=x1, width=new_w)
                        else:
                            # Taller than target — crop top/bottom
                            new_h = int(clip.w / target_ratio)
                            y1    = (clip.h - new_h) // 2
                            clip  = clip.crop(y1=y1, height=new_h)

                        clip = clip.resize((TARGET_W, TARGET_H))

                        # Use up to 10 seconds from each clip
                        clip_duration = min(clip.duration, 10.0)
                        clip = clip.subclip(0, clip_duration)

                        clips.append(clip)
                    except Exception as e:
                        print(f"    Clip {i} error: {e}")

            if not clips:
                print("  No valid video clips — cannot assemble Reel.")
                audio.close()
                return False

            # Repeat clips if needed to fill audio duration
            while sum(c.duration for c in clips) < duration:
                clips.extend(clips[:])
            clips = clips[:20]   # safety cap

            # Concatenate and trim to audio duration
            video = concatenate_videoclips(clips, method="compose")
            video = video.subclip(0, min(duration, video.duration))
            video = video.set_audio(audio)

            # Export
            video.write_videofile(
                output_path,
                fps          = 30,
                codec        = "libx264",
                audio_codec  = "aac",
                bitrate      = "4000k",
                verbose      = False,
                logger       = None,
            )

            video.close()
            audio.close()

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

    print(f"[{now.isoformat()}] Making Reel for: {topic_data['topic']}")
    print(f"  Angle: {topic_data['angle']}\n")

    # Step 1 — Generate script
    print("  Step 1: Writing script with Groq...")
    script = generate_script(topic_data)
    word_count = len(script.split())
    print(f"  Script ready ({word_count} words):\n")
    print(f"  ---\n  {script[:200]}...\n  ---\n")

    # Save script as text file for reference
    script_path = OUTPUT_DIR / f"reel_{stamp}_script.txt"
    script_path.write_text(
        f"Topic: {topic_data['topic']}\n"
        f"Angle: {topic_data['angle']}\n\n"
        f"{script}",
        encoding="utf-8"
    )
    print(f"  Script saved: {script_path}")

    # Step 2 — Text to speech
    audio_path = str(OUTPUT_DIR / f"reel_{stamp}_audio.mp3")
    print("\n  Step 2: Generating Spanish voiceover with ElevenLabs...")
    audio_ok = text_to_speech(script, audio_path)

    if not audio_ok:
        print("\n  Audio generation failed or skipped.")
        print("  Script is saved — you can record voiceover manually.")
        print(f"  Script file: {script_path}")
        return

    # Step 3 — Get video clips from Pexels
    print(f"\n  Step 3: Fetching video clips from Pexels ('{topic_data['search']}')...")
    video_urls = get_pexels_videos(topic_data["search"], count=6)
    print(f"  Found {len(video_urls)} video clips.")

    if not video_urls:
        print("  No video clips found. Audio saved — edit manually in CapCut.")
        print(f"  Audio: {audio_path}")
        return

    # Step 4 — Assemble Reel
    output_path = str(OUTPUT_DIR / f"reel_{stamp}.mp4")
    print(f"\n  Step 4: Assembling 9:16 Reel with MoviePy...")
    success = assemble_reel(audio_path, video_urls, output_path)

    if success:
        size_mb = os.path.getsize(output_path) / 1024 / 1024
        print(f"\n  Reel ready: {output_path} ({size_mb:.1f} MB)")
        print(f"\n  NEXT STEPS:")
        print(f"  1. Download {output_path} from GitHub Actions artifacts")
        print(f"  2. Open Facebook app on your phone")
        print(f"  3. Create Reel → upload the .mp4 file")
        print(f"  4. Add caption from script file: {script_path}")
        print(f"  5. Post!")
    else:
        print(f"\n  Assembly failed. Audio available at: {audio_path}")
        print(f"  You can use CapCut or any video editor to combine manually.")


if __name__ == "__main__":
    make_reel()
