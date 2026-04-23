"""
make_reel.py
------------
Generates a 60-second Facebook/Instagram Reel — 100% free:
  1. Groq  → writes Spanish script
  2. Kokoro → converts to Spanish voiceover (free, local, no API key)
  3. Pexels → fetches video clips
  4. MoviePy → assembles 9:16 vertical Reel

Output: reels/reel_YYYYMMDD.mp4  — download from GitHub Actions artifacts,
        upload to Facebook/Instagram manually (takes ~5 minutes)

Run manually:  python make_reel.py
Runs via cron: every Wednesday at 09:00 UTC (GitHub Actions)
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

load_dotenv()

GROQ_API_KEY  = os.getenv("GROQ_API_KEY")
PEXELS_KEY    = os.getenv("PEXELS_API_KEY")

OUTPUT_DIR = Path("reels")
OUTPUT_DIR.mkdir(exist_ok=True)

# Reel topics — rotated weekly so content stays fresh
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
    week = datetime.now(timezone.utc).isocalendar()[1]
    return REEL_TOPICS[week % len(REEL_TOPICS)]


def generate_script(topic_data: dict) -> str:
    client = Groq(api_key=GROQ_API_KEY)
    prompt = (
        f"Escribe un guión de Reel de 60 segundos sobre: {topic_data['topic']}\n"
        f"Ángulo: {topic_data['angle']}\n\n"
        f"Exactamente 130-150 palabras. Solo el texto a narrar."
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


def text_to_speech_kokoro(script: str, output_path: str) -> bool:
    """
    Generate Spanish voiceover using Kokoro TTS.
    Kokoro is 100% free, open-source, runs locally — no API key needed.
    Install: pip install kokoro soundfile
    Kokoro supports Spanish with the 'es' language code.
    """
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
            print("  Kokoro returned no audio.")
            return False

        # Concatenate chunks and save as WAV
        audio = np.concatenate(audio_chunks)
        sf.write(output_path, audio, 24000)
        print(f"  Audio saved: {output_path}")
        return True

    except ImportError:
        print("  Kokoro not installed. Run: pip install kokoro soundfile")
        print("  Falling back to gTTS (Google TTS, also free)...")
        return text_to_speech_gtts(script, output_path)
    except Exception as e:
        print(f"  Kokoro error: {e}")
        print("  Falling back to gTTS...")
        return text_to_speech_gtts(script, output_path)


def text_to_speech_gtts(script: str, output_path: str) -> bool:
    """
    Fallback: Google Text-to-Speech (gTTS) — free, no API key.
    Quality is lower than Kokoro but works everywhere.
    Install: pip install gtts
    """
    try:
        from gtts import gTTS
        tts = gTTS(text=script, lang="es", slow=False)
        tts.save(output_path)
        print(f"  Audio saved via gTTS: {output_path}")
        return True
    except ImportError:
        print("  gTTS not installed. Run: pip install gtts")
        return False
    except Exception as e:
        print(f"  gTTS error: {e}")
        return False


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
                urls.append(files[0]["link"])
        return urls
    except Exception as e:
        print(f"  Pexels video error: {e}")
        return []


def download_file(url: str, path: str) -> bool:
    try:
        r = requests.get(url, timeout=60, stream=True)
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"  Download error: {e}")
        return False


def assemble_reel(audio_path: str, video_urls: list, output_path: str) -> bool:
    try:
        from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips

        TARGET_W, TARGET_H = 1080, 1920

        audio    = AudioFileClip(audio_path)
        duration = audio.duration + 1.0
        print(f"  Audio duration: {duration:.1f}s")

        clips = []
        with tempfile.TemporaryDirectory() as tmpdir:
            for i, url in enumerate(video_urls):
                tmp = os.path.join(tmpdir, f"clip_{i}.mp4")
                if not download_file(url, tmp):
                    continue
                try:
                    clip = VideoFileClip(tmp)
                    # Crop to 9:16
                    ratio = clip.w / clip.h
                    target = TARGET_W / TARGET_H
                    if ratio > target:
                        new_w = int(clip.h * target)
                        clip  = clip.crop(x1=(clip.w - new_w) // 2, width=new_w)
                    else:
                        new_h = int(clip.w / target)
                        clip  = clip.crop(y1=(clip.h - new_h) // 2, height=new_h)
                    clip = clip.resize((TARGET_W, TARGET_H))
                    clip = clip.subclip(0, min(clip.duration, 10.0))
                    clips.append(clip)
                except Exception as e:
                    print(f"    Clip {i} error: {e}")

            if not clips:
                print("  No valid clips.")
                audio.close()
                return False

            # Loop clips until we have enough duration
            while sum(c.duration for c in clips) < duration:
                clips.extend(clips[:])
            clips = clips[:20]

            video = concatenate_videoclips(clips, method="compose")
            video = video.subclip(0, min(duration, video.duration))
            video = video.set_audio(audio)
            video.write_videofile(
                output_path,
                fps         = 30,
                codec       = "libx264",
                audio_codec = "aac",
                bitrate     = "4000k",
                verbose     = False,
                logger      = None,
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

    print(f"[{now.isoformat()}] Making Reel: {topic_data['topic']}")
    print(f"  Angle: {topic_data['angle']}\n")

    # Step 1 — Script
    print("  Step 1: Writing script with Groq...")
    script = generate_script(topic_data)
    print(f"  Script ({len(script.split())} words):\n  {script[:120]}...\n")

    script_path = OUTPUT_DIR / f"reel_{stamp}_script.txt"
    script_path.write_text(
        f"Topic: {topic_data['topic']}\nAngle: {topic_data['angle']}\n\n{script}",
        encoding="utf-8"
    )

    # Step 2 — TTS (Kokoro first, gTTS fallback)
    audio_path = str(OUTPUT_DIR / f"reel_{stamp}_audio.wav")
    print("  Step 2: Generating Spanish voiceover (Kokoro TTS)...")
    audio_ok = text_to_speech_kokoro(script, audio_path)

    if not audio_ok:
        print("  Audio generation failed. Script saved for manual recording.")
        print(f"  Script: {script_path}")
        return

    # Step 3 — Video clips
    print(f"\n  Step 3: Fetching Pexels clips ('{topic_data['search']}')...")
    video_urls = get_pexels_videos(topic_data["search"], count=6)
    print(f"  Found {len(video_urls)} clips.")

    if not video_urls:
        print("  No clips found. Audio saved — edit manually in CapCut.")
        return

    # Step 4 — Assemble
    output_path = str(OUTPUT_DIR / f"reel_{stamp}.mp4")
    print(f"\n  Step 4: Assembling Reel with MoviePy...")
    ok = assemble_reel(audio_path, video_urls, output_path)

    if ok:
        mb = os.path.getsize(output_path) / 1024 / 1024
        print(f"\n  Reel ready: {output_path} ({mb:.1f} MB)")
        print(f"  Script:     {script_path}")
        print(f"\n  To post:")
        print(f"  1. Download reel_{stamp}.mp4 from GitHub Actions artifacts")
        print(f"  2. Open Facebook app → Reel → upload the file")
        print(f"  3. Use the script text as your caption")
    else:
        print(f"\n  Assembly failed. Audio at: {audio_path}")


if __name__ == "__main__":
    make_reel()
