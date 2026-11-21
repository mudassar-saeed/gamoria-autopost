"""Post due clips from queue.json to YouTube and Instagram.

Run by the GitHub Actions workflow. Modes:
  python scripts/post.py --check     # stdlib only: report whether anything is due
  python scripts/post.py             # post everything that is due
  python scripts/post.py --dry-run   # show what would be posted, post nothing
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "queue.json"
CONFIG = ROOT / "config.json"
PLATFORMS = ("youtube", "instagram")


# ---------- queue helpers (stdlib only) ----------

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_queue(queue):
    tmp = QUEUE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(QUEUE)


def parse_time(s):
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError(f"publish_at needs a UTC offset: {s}")
    return dt


def needs_work(item, platform, cfg, now):
    """True if this platform of this item should be attempted now."""
    p = item.get("platforms", {}).get(platform)
    if not p or p.get("status") not in ("pending", "retry"):
        return False
    if p.get("attempts", 0) >= cfg.get("max_attempts", 3):
        return False
    due = parse_time(item["publish_at"]) <= now
    if due:
        return True
    # YouTube can be uploaded early and scheduled by YouTube itself.
    return platform == "youtube" and cfg.get("youtube", {}).get("use_publish_at", False)


def work_list(queue, cfg, now):
    out = []
    for item in queue:
        for platform in PLATFORMS:
            if needs_work(item, platform, cfg, now):
                out.append((item, platform))
    return out


def set_output(name, value):
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


# ---------- YouTube ----------

def hashtags(text):
    return re.findall(r"#(\w+)", text)


def youtube_title(item):
    title = item["title"].strip()
    if "#shorts" not in title.lower():
        if len(title) + 8 <= 100:
            title += " #shorts"
    return title[:100]


def post_youtube(item, cfg, now):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    for key in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        if not os.environ.get(key):
            raise RuntimeError(f"Missing GitHub secret {key}")

    creds = Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)

    ycfg = cfg.get("youtube", {})
    status = {
        "privacyStatus": ycfg.get("privacy_status", "public"),
        "selfDeclaredMadeForKids": False,
    }
    publish_at = parse_time(item["publish_at"])
    if ycfg.get("use_publish_at") and publish_at > now:
        # YouTube publishes it at the exact time; must be uploaded as private.
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    body = {
        "snippet": {
            "title": youtube_title(item),
            "description": item["caption"][:5000],
            "tags": hashtags(item["caption"])[:30],
            "categoryId": ycfg.get("category_id", "20"),
        },
        "status": status,
    }
    media = MediaFileUpload(str(ROOT / item["video"]), mimetype="video/mp4",
                            chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = req.next_chunk()
    vid = response["id"]
    return {"id": vid, "url": f"https://youtube.com/shorts/{vid}"}


# ---------- Instagram ----------

def ig_caption(item):
    cap = item["caption"]
    tags = re.findall(r"#\w+", cap)
    if len(tags) > 30:  # Instagram rejects more than 30 hashtags
        for t in tags[30:]:
            cap = cap.replace(t, "", 1)
    return cap.strip()[:2200]


def ig_check(resp):
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text[:500]}
    if resp.status_code >= 400 or "error" in data:
        raise RuntimeError(f"Instagram API error {resp.status_code}: {data}")
    return data


def post_instagram(item, cfg):
    import requests

    ig_user = os.environ.get("IG_USER_ID")
    token = os.environ.get("IG_ACCESS_TOKEN")
    if not ig_user or not token:
        raise RuntimeError("Missing GitHub secret IG_USER_ID or IG_ACCESS_TOKEN")

    icfg = cfg.get("instagram", {})
    ver = icfg.get("api_version", "v25.0")
    mode = icfg.get("mode", "facebook")
    host = "https://graph.facebook.com" if mode == "facebook" else "https://graph.instagram.com"
    base = f"{host}/{ver}"
    caption = ig_caption(item)
    video_path = ROOT / item["video"]

    params = {
        "media_type": "REELS",
        "caption": caption,
        "share_to_feed": "true" if icfg.get("share_to_feed", True) else "false",
        "access_token": token,
    }

    if mode == "facebook":
        # Resumable upload: sends the file straight from the runner (repo can stay private).
        params["upload_type"] = "resumable"
        data = ig_check(requests.post(f"{base}/{ig_user}/media", data=params, timeout=60))
        container = data["id"]
        upload_uri = data.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{ver}/{container}"
        size = video_path.stat().st_size
        with open(video_path, "rb") as f:
            ig_check(requests.post(
                upload_uri,
                headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)},
                data=f,
                timeout=600,
            ))
    else:
        public = icfg.get("public_video_base_url", "").rstrip("/")
        if not public:
            raise RuntimeError("instagram.mode is 'instagram' but public_video_base_url is empty in config.json")
        params["video_url"] = f"{public}/{item['video']}"
        data = ig_check(requests.post(f"{base}/{ig_user}/media", data=params, timeout=60))
        container = data["id"]

    # Wait for Instagram to finish processing the video.
    deadline = time.time() + 15 * 60
    while True:
        st = ig_check(requests.get(f"{base}/{container}",
                                   params={"fields": "status_code,status", "access_token": token},
                                   timeout=60))
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram processing failed: {st}")
        if time.time() > deadline:
            raise RuntimeError(f"Instagram processing timed out: {st}")
        time.sleep(15)

    pub = ig_check(requests.post(f"{base}/{ig_user}/media_publish",
                                 data={"creation_id": container, "access_token": token},
                                 timeout=60))
    return {"id": pub["id"]}


# ---------- main ----------

def finish_item(item, cfg):
    """Delete the video once every platform is done, to keep the repo small."""
    states = [p.get("status") for p in item.get("platforms", {}).values()]
    if states and all(s in ("posted", "failed") for s in states):
        item["done"] = True
        if cfg.get("delete_video_after_post", True):
            path = ROOT / item["video"]
            if path.exists():
                path.unlink()
                item["video_deleted"] = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_json(CONFIG)
    queue = load_json(QUEUE)
    now = datetime.now(timezone.utc)
    todo = work_list(queue, cfg, now)

    if args.check:
        set_output("due", "true" if todo else "false")
        print(f"{len(todo)} upload(s) due." if todo else "Nothing due.")
        return 0

    if not todo:
        print("Nothing due.")
        return 0

    failures = 0
    for item, platform in todo:
        label = f"{item['id']} -> {platform}"
        if args.dry_run:
            print(f"[dry run] would post {label} (scheduled {item['publish_at']})")
            continue
        p = item["platforms"][platform]
        p["attempts"] = p.get("attempts", 0) + 1
        p["last_attempt"] = now.isoformat(timespec="seconds")
        video = ROOT / item["video"]
        try:
            if not video.exists():
                raise RuntimeError(f"Video file missing: {item['video']}")
            print(f"Posting {label} ...", flush=True)
            if platform == "youtube":
                result = post_youtube(item, cfg, now)
            else:
                result = post_instagram(item, cfg)
            p.update(result)
            p["status"] = "posted"
            p["posted_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            p.pop("error", None)
            print(f"  posted: {result}", flush=True)
        except Exception as e:  # keep going with the other uploads
            failures += 1
            p["error"] = str(e)[:500]
            p["status"] = "failed" if p["attempts"] >= cfg.get("max_attempts", 3) else "retry"
            print(f"  FAILED ({p['status']}): {e}", flush=True)
        finish_item(item, cfg)
        save_queue(queue)  # save after every upload so nothing is posted twice

    if failures:
        print(f"{failures} upload(s) failed. See errors in queue.json.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
