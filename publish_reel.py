"""
publish_reel.py
---------------
Publishes the latest generated Reel video (reels/reel_YYYYMMDD.mp4) to:
  - Facebook Page Reels (Reels Publishing API)
  - Instagram Reels (IG Content Publishing API + resumable upload)
  - X video tweet (v1.1 chunked media upload + v2 tweet, user token only)
  - TikTok (Content Posting API v2, FILE_UPLOAD, chunked)

YouTube is NOT re-uploaded here: make_reel.py already uploads the same
reel as a YouTube Short in its Step 5, before this script runs. Uploading
it again here would publish a duplicate Short.

This script is designed to run in GitHub Actions right after make_reel.py.
Each platform is independent: one platform failing does not block the
others, and the log records which ones actually succeeded.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests


FB_PAGE_ID = os.getenv("FB_PAGE_ID", "").strip()
FB_PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN", "").strip()

IG_USER_ID = os.getenv("IG_USER_ID", "").strip()
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN", "").strip()

# X: two auth paths, OAuth 1.0a preferred.
# OAuth 1.0a (non-expiring, app-owner token): set GitHub secrets
#   X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
# from the app's Keys and Tokens page, OAuth 1.0a section. This is the
# path to use for @mejorrockespanol: the portal-generated owner token
# does not expire, unlike an OAuth 2.0 user token (~2h, needs refresh).
# Fallback: a user OAuth 2.0 token, NOT an app-only bearer token, which
# cannot post. Set as GitHub secret X_USER_TOKEN. Use only for a quick
# test within its 2h lifetime; it will stop working when it expires.
X_USER_TOKEN = os.getenv("X_USER_TOKEN", "").strip()
X_API_KEY = os.getenv("X_API_KEY", "").strip()
X_API_SECRET = os.getenv("X_API_SECRET", "").strip()
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN", "").strip()
X_ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET", "").strip()


def _x_auth():
    """Return (headers, auth) for X requests.

    OAuth 1.0a if all four OAuth 1.0a secrets are present, otherwise
    Bearer with X_USER_TOKEN if present, otherwise (None, None).
    Returns headers dict (may be empty) and a requests auth object.
    """
    if X_API_KEY and X_API_SECRET and X_ACCESS_TOKEN and X_ACCESS_TOKEN_SECRET:
        try:
            from requests_oauthlib import OAuth1

            return {}, OAuth1(
                X_API_KEY,
                client_secret=X_API_SECRET,
                resource_owner_key=X_ACCESS_TOKEN,
                resource_owner_secret=X_ACCESS_TOKEN_SECRET,
            )
        except ImportError:
            return {}, None
    if X_USER_TOKEN:
        return {"Authorization": f"Bearer {X_USER_TOKEN}"}, None
    return {}, None

# TikTok: Content Posting API v2. The app must be approved for Content
# Posting, otherwise init returns 403. Set as GitHub secrets.
TIKTOK_ACCESS_TOKEN = os.getenv("TIKTOK_ACCESS_TOKEN", "").strip()
TIKTOK_OPEN_ID = os.getenv("TIKTOK_OPEN_ID", "").strip()

LOG_FILE = "log.json"
REELS_DIR = Path("reels")

# Use a modern API version for Reels publishing (Meta docs reference v25.0+)
GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v25.0").strip()


@dataclass
class PublishResult:
    platform: str
    ok: bool
    id: Optional[str] = None
    error: Optional[str] = None
    skipped: bool = False


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_log(entry: dict) -> None:
    log = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, encoding="utf-8") as f:
                log = json.load(f)
        except Exception:
            log = []
    log.append(entry)
    log = log[-400:]
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def _latest_reel_path() -> Optional[Path]:
    if not REELS_DIR.exists():
        return None
    # Prefer reel_YYYYMMDD.mp4 over other artifacts
    candidates = sorted(REELS_DIR.glob("reel_*.mp4"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def _post(url: str, data: dict, timeout_s: int = 60) -> dict:
    r = requests.post(url, data=data, timeout=timeout_s)
    try:
        return r.json()
    except Exception:
        return {"error": {"message": f"Non-JSON response (status {r.status_code})", "raw": r.text[:500]}}


def _get(url: str, params: dict, timeout_s: int = 30) -> dict:
    r = requests.get(url, params=params, timeout=timeout_s)
    try:
        return r.json()
    except Exception:
        return {"error": {"message": f"Non-JSON response (status {r.status_code})", "raw": r.text[:500]}}


def publish_facebook_reel(video_path: Path, caption: str) -> PublishResult:
    """
    Facebook Page Reels Publishing API:
      1) start  POST /{page-id}/video_reels?upload_phase=start
      2) upload POST rupload URL with bytes
      3) finish POST /{page-id}/video_reels?upload_phase=finish&video_state=PUBLISHED
    """
    if not FB_PAGE_ID or not FB_PAGE_TOKEN:
        return PublishResult(platform="facebook_reel", ok=False, error="Missing FB_PAGE_ID/FB_PAGE_TOKEN")

    graph = f"https://graph.facebook.com/{GRAPH_VERSION}/{FB_PAGE_ID}/video_reels"
    start = _post(
        graph,
        data={
            "upload_phase": "start",
            "access_token": FB_PAGE_TOKEN,
        },
        timeout_s=60,
    )
    if "error" in start:
        return PublishResult(platform="facebook_reel", ok=False, error=start["error"].get("message", "start failed"))

    video_id = start.get("video_id") or start.get("id")
    upload_url = start.get("upload_url")
    if not video_id or not upload_url:
        return PublishResult(platform="facebook_reel", ok=False, error=f"Unexpected start response: {start}")

    file_size = video_path.stat().st_size
    try:
        with open(video_path, "rb") as f:
            up = requests.post(
                upload_url,
                headers={
                    "Authorization": f"OAuth {FB_PAGE_TOKEN}",
                    "offset": "0",
                    "file_size": str(file_size),
                },
                data=f,
                timeout=300,
            )
        try:
            upj = up.json()
        except Exception:
            upj = {"success": up.ok, "status": up.status_code, "raw": up.text[:500]}
        if not up.ok or (isinstance(upj, dict) and upj.get("success") is False):
            return PublishResult(platform="facebook_reel", ok=False, error=f"Upload failed: {upj}")
    except Exception as e:
        return PublishResult(platform="facebook_reel", ok=False, error=f"Upload exception: {e}")

    finish = _post(
        graph,
        data={
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": caption,
            "access_token": FB_PAGE_TOKEN,
        },
        timeout_s=60,
    )
    if "error" in finish:
        return PublishResult(platform="facebook_reel", ok=False, error=finish["error"].get("message", "finish failed"))

    reel_id = finish.get("id") or finish.get("video_id") or video_id
    return PublishResult(platform="facebook_reel", ok=True, id=str(reel_id))


def publish_instagram_reel(video_path: Path, caption: str) -> PublishResult:
    """IG Reel publish, with three different attempts, not three copies
    of the same attempt.

    Ruled out by 2026-10-26 (three runs, same error every time):
      - format: ffprobe proved h264 High, yuv420p, 1080x1920, 30 fps,
        aac LC 44100 Hz stereo 129 kb/s, 52-57s — all in spec.
      - transient container: fresh-container retry also failed twice.
      - Content-Type: sending application/octet-stream also failed.
    So the next run tries, in order, each with a fresh container, and
    only the attempt that reaches FINISHED calls media_publish, so a
    failed attempt can never publish a duplicate:
      1) single POST, original file (the method that worked once, on
         2026-10-25 21:20 UTC, and has failed ever since).
      2) re-encoded file: ffmpeg H.264 Main profile, level 4.0,
         yuv420p, +faststart (moov atom at the front, required by
         some IG processing paths), AAC 128k, single POST.
      3) chunked upload: original file in 5 MB chunks with advancing
         offset headers, instead of one 26 MB POST.
    If all three fail, the error summary says so plainly, and the
    next diagnostic is a manual upload of that exact mp4 in the
    Instagram app / an account-status check, not another code guess.
    """
    attempts = [
        ("single, original file", video_path, "single", False),
    ]
    reencoded = _reencode_for_instagram(video_path)
    if reencoded is not None:
        attempts.append(("single, re-encoded (Main/faststart)", reencoded, "single", True))
    attempts.append(("chunked, original file", video_path, "chunked", False))

    last = None
    for label, path, mode, is_temp in attempts:
        print(f"  Instagram Reel: attempt — {label}...")
        result = _publish_instagram_reel_once(path, caption, upload_mode=mode)
        if is_temp:
            try:
                os.remove(path)
            except Exception:
                pass
        if result.ok:
            return result
        last = result
        print(f"  Instagram Reel: attempt failed — {label}: {result.error}")
        time.sleep(10)
    return last if last is not None else PublishResult(
        platform="instagram_reel", ok=False, error="No IG attempt ran")


def _reencode_for_instagram(video_path: Path):
    """Re-encode a reel for IG processing: Main profile + faststart.

    Returns the temp file path, or None if ffmpeg is unavailable or
    the re-encode fails. The caller deletes the temp file.
    """
    import shutil
    import subprocess
    import tempfile
    if shutil.which("ffmpeg") is None:
        print("  Instagram Reel: ffmpeg not available, skipping re-encode attempt.")
        return None
    fd, tmp = tempfile.mkstemp(prefix="ig_reel_", suffix=".mp4")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path),
             "-c:v", "libx264", "-profile:v", "main", "-level", "4.0",
             "-pix_fmt", "yuv420p", "-r", "30",
             "-movflags", "+faststart",
             "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
             str(tmp_path)],
            capture_output=True, text=True, timeout=300,
        )
        if r.returncode != 0 or not tmp_path.exists() or tmp_path.stat().st_size == 0:
            print(f"  Instagram Reel: re-encode failed, skipping that attempt: {r.stderr[-300:]}")
            try:
                tmp_path.unlink()
            except Exception:
                pass
            return None
        print(f"  Instagram Reel: re-encoded file ready ({tmp_path.stat().st_size} bytes).")
        return tmp_path
    except Exception as e:
        print(f"  Instagram Reel: re-encode exception, skipping that attempt: {e}")
        try:
            tmp_path.unlink()
        except Exception:
            pass
        return None


def _ig_container_status(graph_base: str, container_id: str, token: str) -> str:
    """Best-effort container status after an upload failure, for diagnosis."""
    try:
        st = _get(
            f"{graph_base}/{container_id}",
            params={"fields": "status_code", "access_token": token},
            timeout_s=30,
        )
        if "error" in st:
            return f"status check error: {st['error'].get('message', 'unknown')}"
        return str(st.get("status_code", "unknown"))
    except Exception as e:
        return f"status check exception: {e}"


def _publish_instagram_reel_once(video_path: Path, caption: str, upload_mode: str = "single") -> PublishResult:
    """
    Instagram Reels publishing using resumable upload:
      1) Create container: POST /{ig-user-id}/media with media_type=REELS, upload_type=resumable
      2) Upload bytes: POST https://rupload.facebook.com/ig-api-upload/{api-version}/{container-id}
         (single POST, or 5 MB chunks if upload_mode="chunked")
      3) Poll: GET /{container-id}?fields=status_code until FINISHED
      4) Publish: POST /{ig-user-id}/media_publish
    """
    if not IG_USER_ID:
        return PublishResult(platform="instagram_reel", ok=False, error="Missing IG_USER_ID")
    token = IG_ACCESS_TOKEN or FB_PAGE_TOKEN
    if not token:
        return PublishResult(platform="instagram_reel", ok=False, error="Missing IG_ACCESS_TOKEN/FB_PAGE_TOKEN")

    graph_base = f"https://graph.facebook.com/{GRAPH_VERSION}"
    create = _post(
        f"{graph_base}/{IG_USER_ID}/media",
        data={
            "media_type": "REELS",
            "caption": caption,
            "upload_type": "resumable",
            "access_token": token,
        },
        timeout_s=60,
    )
    if "error" in create:
        return PublishResult(platform="instagram_reel", ok=False, error=create["error"].get("message", "container create failed"))

    container_id = create.get("id")
    if not container_id:
        return PublishResult(platform="instagram_reel", ok=False, error=f"Unexpected container response: {create}")

    file_size = video_path.stat().st_size
    upload_url = f"https://rupload.facebook.com/ig-api-upload/{GRAPH_VERSION}/{container_id}"
    try:
        if upload_mode == "chunked":
            # 5 MB chunks, advancing offset. If the server returns an
            # offset, trust it (resume position); otherwise advance by
            # the chunk length we just sent.
            sent = 0
            with open(video_path, "rb") as f:
                while sent < file_size:
                    chunk = f.read(5 * 1024 * 1024)
                    if not chunk:
                        break
                    up = requests.post(
                        upload_url,
                        headers={
                            "Authorization": f"OAuth {token}",
                            "offset": str(sent),
                            "file_size": str(file_size),
                            "Content-Type": "application/octet-stream",
                        },
                        data=chunk,
                        timeout=300,
                    )
                    try:
                        upj = up.json()
                    except Exception:
                        upj = {"success": up.ok, "status": up.status_code, "raw": up.text[:500]}
                    if not up.ok or (isinstance(upj, dict) and upj.get("success") is False):
                        return PublishResult(
                            platform="instagram_reel", ok=False,
                            error=f"Chunked upload failed at offset {sent}: {upj} (container status: {_ig_container_status(graph_base, container_id, token)})")
                    if isinstance(upj, dict) and isinstance(upj.get("offset"), int):
                        sent = upj["offset"]
                    else:
                        sent += len(chunk)
            if sent < file_size:
                return PublishResult(platform="instagram_reel", ok=False, error=f"Chunked upload incomplete: sent {sent} of {file_size} bytes")
        else:
            with open(video_path, "rb") as f:
                up = requests.post(
                    upload_url,
                    headers={
                        "Authorization": f"OAuth {token}",
                        "offset": "0",
                        "file_size": str(file_size),
                        "Content-Type": "application/octet-stream",
                    },
                    data=f,
                    timeout=300,
                )
            try:
                upj = up.json()
            except Exception:
                upj = {"success": up.ok, "status": up.status_code, "raw": up.text[:500]}
            if not up.ok or (isinstance(upj, dict) and upj.get("success") is False):
                return PublishResult(
                    platform="instagram_reel", ok=False,
                    error=f"Upload failed: {upj} (container status: {_ig_container_status(graph_base, container_id, token)})")
    except Exception as e:
        return PublishResult(platform="instagram_reel", ok=False, error=f"Upload exception: {e}")

    # Poll status (once per ~10s, max 5 minutes)
    status = None
    for _ in range(30):
        st = _get(
            f"{graph_base}/{container_id}",
            params={"fields": "status_code", "access_token": token},
            timeout_s=30,
        )
        if "error" in st:
            return PublishResult(platform="instagram_reel", ok=False, error=st["error"].get("message", "status check failed"))
        status = st.get("status_code")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            return PublishResult(platform="instagram_reel", ok=False, error=f"Container status: {status}")
        time.sleep(10)

    if status != "FINISHED":
        return PublishResult(platform="instagram_reel", ok=False, error=f"Timed out waiting for FINISHED (last={status})")

    pub = _post(
        f"{graph_base}/{IG_USER_ID}/media_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout_s=60,
    )
    if "error" in pub:
        return PublishResult(platform="instagram_reel", ok=False, error=pub["error"].get("message", "publish failed"))

    ig_media_id = pub.get("id")
    return PublishResult(platform="instagram_reel", ok=True, id=str(ig_media_id) if ig_media_id else None)


def _shorten(text: str, limit: int) -> str:
    """Truncate to limit chars, cutting at the last space if possible."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].strip()
    return cut if cut else text[:limit].strip()


def publish_x_video(video_path: Path, caption: str) -> PublishResult:
    """
    X video tweet, using the daily reel file (user decision 2026-10-24:
    reel/video for X, TikTok and YouTube, not the text post).
      1) INIT   POST upload.twitter.com/1.1/media/upload.json
      2) APPEND chunked, 5 MB segments (a single APPEND fails over 5 MB)
      3) FINALIZE, then poll STATUS until succeeded/failed
      4) POST api.twitter.com/2/tweets with media_ids, text <= 280 chars
    Requires OAuth 1.0a secrets, or X_USER_TOKEN as a fallback.
    Returns the tweet ID, never a media ID alone, so a logged success
    means the tweet actually exists.
    DISABLED 2026-10-25: POST /2/tweets returned 402 Payment Required
    for this app, so X is off by default. Re-enable by setting
    X_ENABLED=true in the workflow env; the OAuth code stays intact.
    """
    if os.getenv("X_ENABLED", "false").lower() in ("false", "0", "no", "off", ""):
        return PublishResult(platform="x", ok=False, skipped=True, error="X disabled (paid API, 2026-10-25)")
    headers, x_auth = _x_auth()
    if not headers and x_auth is None:
        return PublishResult(platform="x", ok=False, error="Missing X OAuth 1.0a secrets or X_USER_TOKEN")
    file_size = video_path.stat().st_size
    upload_url = "https://upload.twitter.com/1.1/media/upload.json"
    try:
        init = requests.post(
            upload_url, headers=headers, auth=x_auth, timeout=60,
            data={"command": "INIT", "total_bytes": str(file_size),
                  "media_type": "video/mp4", "media_category": "tweet_video"},
        )
        init.raise_for_status()
        media_id = init.json().get("media_id_string")
        if not media_id:
            return PublishResult(platform="x", ok=False, error=f"X media INIT returned no media_id: {init.text[:300]}")
        with open(video_path, "rb") as f:
            segment = 0
            while True:
                chunk = f.read(5 * 1024 * 1024)
                if not chunk:
                    break
                app = requests.post(
                    upload_url, headers=headers, auth=x_auth, timeout=120,
                    data={"command": "APPEND", "media_id": media_id, "segment_index": str(segment)},
                    files={"media": chunk},
                )
                app.raise_for_status()
                segment += 1
        fin = requests.post(
            upload_url, headers=headers, auth=x_auth, timeout=60,
            data={"command": "FINALIZE", "media_id": media_id},
        )
        fin.raise_for_status()
        processing = fin.json().get("processing_info")
        # Poll STATUS (max ~5 minutes); X usually finishes in seconds.
        for _ in range(30):
            if not processing:
                break
            state = processing.get("state")
            if state == "succeeded":
                break
            if state == "failed":
                return PublishResult(platform="x", ok=False, error=f"X media processing failed: {processing}")
            time.sleep(min(int(processing.get("check_after_secs", 5)), 10))
            st = requests.get(
                upload_url, headers=headers, auth=x_auth, timeout=60,
                params={"command": "STATUS", "media_id": media_id},
            )
            st.raise_for_status()
            processing = st.json().get("processing_info")
        else:
            return PublishResult(platform="x", ok=False, error="X media processing timed out")
        tweet_text = _shorten(caption, 280)
        tw = requests.post(
            "https://api.twitter.com/2/tweets",
            headers={**headers, "Content-Type": "application/json"},
            auth=x_auth,
            json={"text": tweet_text, "media": {"media_ids": [media_id]}},
            timeout=60,
        )
        tw.raise_for_status()
        tweet_id = tw.json().get("data", {}).get("id")
        if not tweet_id:
            return PublishResult(platform="x", ok=False, error=f"X tweet returned no id: {tw.text[:300]}")
        return PublishResult(platform="x", ok=True, id=str(tweet_id))
    except Exception as e:
        return PublishResult(platform="x", ok=False, error=str(e))


def publish_tiktok_video(video_path: Path, caption: str) -> PublishResult:
    """
    TikTok video post, using the daily reel file.
    Content Posting API v2, FILE_UPLOAD:
      1) POST /v2/post/publish/video/init/ with title (<=150 chars)
      2) PUT the file to upload_url, chunked at 5 MB, with Content-Range
      3) Upload completion publishes the direct post; publish_id is logged
    Requires TIKTOK_ACCESS_TOKEN and a TikTok app approved for Content
    Posting, otherwise init returns 403. TIKTOK_OPEN_ID identifies the
    account in setup; the API itself authenticates via the token.
    """
    if not TIKTOK_ACCESS_TOKEN:
        return PublishResult(platform="tiktok", ok=False, error="Missing TIKTOK_ACCESS_TOKEN")
    if not TIKTOK_OPEN_ID:
        print("  TikTok note: TIKTOK_OPEN_ID not set — continuing with token auth only")
    file_size = video_path.stat().st_size
    chunk_size = 5 * 1024 * 1024
    total_chunks = (file_size + chunk_size - 1) // chunk_size or 1
    try:
        init = requests.post(
            "https://open.tiktokapis.com/v2/post/publish/video/init/",
            headers={"Authorization": f"Bearer {TIKTOK_ACCESS_TOKEN}",
                     "Content-Type": "application/json; charset=UTF-8"},
            json={
                "post_info": {
                    "title": _shorten(caption, 150),
                    "privacy_level": "PUBLIC_TO_EVERYONE",
                    "disable_comment": False,
                    "disable_duet": False,
                    "disable_stitch": False,
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": file_size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": total_chunks,
                },
            },
            timeout=60,
        )
        init_data = init.json()
        if init.status_code >= 400 or init_data.get("error"):
            return PublishResult(platform="tiktok", ok=False, error=f"TikTok init failed: {init_data}")
        upload_url = init_data.get("data", {}).get("upload_url")
        publish_id = init_data.get("data", {}).get("publish_id")
        if not upload_url:
            return PublishResult(platform="tiktok", ok=False, error=f"TikTok init returned no upload_url: {init_data}")
        with open(video_path, "rb") as f:
            offset = 0
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                end = offset + len(chunk) - 1
                up = requests.put(
                    upload_url, data=chunk, timeout=300,
                    headers={"Content-Type": "video/mp4",
                             "Content-Range": f"bytes {offset}-{end}/{file_size}"},
                )
                if up.status_code >= 400:
                    return PublishResult(platform="tiktok", ok=False, error=f"TikTok upload failed: {up.text[:300]}")
                offset += len(chunk)
        return PublishResult(platform="tiktok", ok=True, id=str(publish_id) if publish_id else None)
    except Exception as e:
        return PublishResult(platform="tiktok", ok=False, error=str(e))


def build_caption(script_path: Optional[Path]) -> str:
    """
    Keep captions short-ish for Reels; use the reel script if present.
    """
    base = ""
    if script_path and script_path.exists():
        try:
            txt = script_path.read_text(encoding="utf-8").strip()
            # script file includes headers; keep only the body
            parts = txt.split("\n\n", 1)
            base = parts[1].strip() if len(parts) == 2 else txt
        except Exception:
            base = ""
    if not base:
        base = "🎸 Lo Mejor del Rock en Español. ¿Cuál es tu favorita?"
    # Reels captions can be long, but keep it reasonable for cross-posting.
    footer = "\n\n#RockEnEspañol #RockLatino #LoMejordelRockenEspañol"
    out = (base.strip() + footer).strip()
    return out[:2100]


def main() -> None:
    now = _utcnow_iso()
    reel_path = _latest_reel_path()
    if not reel_path:
        print("No reel mp4 found in reels/. Run make_reel.py first.")
        return

    # Find matching script file
    stamp = reel_path.stem.replace("reel_", "")
    script_path = REELS_DIR / f"reel_{stamp}_script.txt"
    caption = build_caption(script_path if script_path.exists() else None)

    print(f"[{now}] Publishing reel: {reel_path}")
    print(f"  Caption preview: {caption[:90]}...")

    fb_res = publish_facebook_reel(reel_path, caption)
    print("  Facebook Reel : " + ("OK id=" + str(fb_res.id) if fb_res.ok else "FAILED " + str(fb_res.error)))

    ig_res = publish_instagram_reel(reel_path, caption)
    print("  Instagram Reel: " + ("OK id=" + str(ig_res.id) if ig_res.ok else "FAILED " + str(ig_res.error)))

    # Reel/video destinations (user decision 2026-10-24). YouTube is
    # handled by make_reel.py Step 5 and is intentionally not repeated here.
    x_res = publish_x_video(reel_path, caption)
    print("  X Video       : " + ("SKIPPED (disabled)" if x_res.skipped else "OK tweet id=" + str(x_res.id) if x_res.ok else "FAILED " + str(x_res.error)))

    tiktok_res = publish_tiktok_video(reel_path, caption)
    print("  TikTok Video  : " + ("OK publish_id=" + str(tiktok_res.id) if tiktok_res.ok else "FAILED " + str(tiktok_res.error)))

    print("  YouTube Short : uploaded by make_reel.py Step 5, not here — check that step's log for its URL")

    _append_log(
        {
            "post_id": f"reel_{stamp}",
            "post_type": "reel",
            "reel_path": str(reel_path),
            "fb_reel_id": fb_res.id,
            "ig_reel_id": ig_res.id,
            "x_tweet_id": x_res.id,
            "tiktok_publish_id": tiktok_res.id,
            "status": "published" if (fb_res.ok or ig_res.ok or x_res.ok or tiktok_res.ok) else "failed",
            "errors": {"facebook": fb_res.error, "instagram": ig_res.error,
                       "x": None if x_res.skipped else x_res.error, "tiktok": tiktok_res.error},
            "executed_at": now,
        }
    )


if __name__ == "__main__":
    main()

