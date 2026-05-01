"""
publish_reel.py
---------------
Publishes the latest generated Reel video (reels/reel_YYYYMMDD.mp4) to:
  - Facebook Page Reels (Reels Publishing API)
  - Instagram Reels (IG Content Publishing API + resumable upload)

This script is designed to run in GitHub Actions right after make_reel.py.
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
    """
    Instagram Reels publishing using resumable upload:
      1) Create container: POST /{ig-user-id}/media with media_type=REELS, upload_type=resumable
      2) Upload bytes: POST https://rupload.facebook.com/ig-api-upload/{api-version}/{container-id}
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
        with open(video_path, "rb") as f:
            up = requests.post(
                upload_url,
                headers={
                    "Authorization": f"OAuth {token}",
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
            return PublishResult(platform="instagram_reel", ok=False, error=f"Upload failed: {upj}")
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

    _append_log(
        {
            "post_id": f"reel_{stamp}",
            "post_type": "reel",
            "reel_path": str(reel_path),
            "fb_reel_id": fb_res.id,
            "ig_reel_id": ig_res.id,
            "status": "published" if (fb_res.ok or ig_res.ok) else "failed",
            "errors": {"facebook": fb_res.error, "instagram": ig_res.error},
            "executed_at": now,
        }
    )


if __name__ == "__main__":
    main()

