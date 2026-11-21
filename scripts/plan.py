"""Add clips to the posting queue, list it, or remove items. Runs on your PC.

Examples (run from the autopost folder):
  python scripts/plan.py add "D:\\Automation\\clips\\out\\01_xqc_bike_flying.mp4" --at "2026-11-21 19:00"
  python scripts/plan.py add "D:\\Automation\\clips\\out\\01_xqc_bike_flying.mp4" --auto
  python scripts/plan.py add-all "D:\\Automation\\clips\\out" --auto
  python scripts/plan.py list
  python scripts/plan.py remove 01_xqc_bike_flying

Then: git add -A && git commit -m "queue clips" && git push
"""
import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "queue.json"
CONFIG = ROOT / "config.json"
VIDEOS = ROOT / "videos"


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(queue):
    with open(QUEUE, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)
        f.write("\n")


def local_tz(cfg):
    off = cfg.get("utc_offset", "+05:00")
    sign = -1 if off.startswith("-") else 1
    h, m = off.lstrip("+-").split(":")
    return timezone(sign * timedelta(hours=int(h), minutes=int(m)))


def read_post_text(mp4):
    """Read the clipper's <name>.txt: title, hashtags, credit line."""
    txt = mp4.with_suffix(".txt")
    title, tags, credit, other = None, [], None, []
    if txt.exists():
        for line in txt.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            if title is None:
                title = line
            elif line.startswith("#"):
                tags += line.split()
            elif line.lower().startswith("credit"):
                credit = line
            else:
                other.append(line)
    if not title:
        title = mp4.stem.split("_", 1)[-1].replace("_", " ")
    return title, tags, credit, other


def build_caption(title, tags, credit, other, cfg):
    parts = [title]
    if other:
        parts.append("\n".join(other))
    if credit:
        parts.append(credit)
    if cfg.get("channel_cta"):
        parts.append(cfg["channel_cta"])
    if "#shorts" not in [t.lower() for t in tags]:
        tags.append("#shorts")
    parts.append(" ".join(dict.fromkeys(tags)))  # de-duplicate, keep order
    return "\n\n".join(parts)


def next_free_slot(queue, cfg, tz):
    taken = {item["publish_at"] for item in queue}
    slots = sorted(cfg.get("auto_slots", ["19:00"]))
    now = datetime.now(tz) + timedelta(minutes=10)
    day = now.date()
    for _ in range(365):
        for s in slots:
            h, m = map(int, s.split(":"))
            t = datetime(day.year, day.month, day.day, h, m, tzinfo=tz)
            if t > now and t.isoformat() not in taken:
                return t
        day += timedelta(days=1)
    raise RuntimeError("No free slot found")


def add_one(mp4, queue, cfg, args, tz):
    mp4 = Path(mp4)
    if mp4.suffix.lower() != ".mp4":
        mp4 = mp4.with_suffix(".mp4")
    if not mp4.exists():
        print(f"Not found: {mp4}")
        return False
    item_id = mp4.stem
    if any(i["id"] == item_id for i in queue):
        print(f"Already queued: {item_id}")
        return False

    if args.at:
        when = datetime.strptime(args.at, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    else:
        when = next_free_slot(queue, cfg, tz)

    title, tags, credit, other = read_post_text(mp4)
    if args.title:
        title = args.title
    platforms = args.platforms.split(",") if args.platforms else cfg.get("default_platforms", ["youtube", "instagram"])

    VIDEOS.mkdir(exist_ok=True)
    dest = VIDEOS / mp4.name
    shutil.copy2(mp4, dest)
    size_mb = dest.stat().st_size / 1e6
    if size_mb > 95:
        print(f"Warning: {mp4.name} is {size_mb:.0f} MB. GitHub rejects files over 100 MB.")

    queue.append({
        "id": item_id,
        "video": f"videos/{mp4.name}",
        "title": title,
        "caption": build_caption(title, tags, credit, other, cfg),
        "publish_at": when.isoformat(),
        "platforms": {p: {"status": "pending"} for p in platforms},
    })
    print(f"Queued {item_id} for {when:%a %d %b %Y %H:%M} ({', '.join(platforms)})")
    return True


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add")
    a.add_argument("mp4")
    a.add_argument("--at", help='local time, "YYYY-MM-DD HH:MM"')
    a.add_argument("--auto", action="store_true", help="use the next free slot from config.json")
    a.add_argument("--title")
    a.add_argument("--platforms", help="youtube,instagram")

    aa = sub.add_parser("add-all")
    aa.add_argument("folder")
    aa.add_argument("--auto", action="store_true", default=True)
    aa.add_argument("--platforms")

    sub.add_parser("list")
    r = sub.add_parser("remove")
    r.add_argument("id")

    args = ap.parse_args()
    cfg = load(CONFIG)
    queue = load(QUEUE)
    tz = local_tz(cfg)

    if args.cmd == "add":
        if not args.at and not args.auto:
            ap.error('give --at "YYYY-MM-DD HH:MM" or --auto')
        if add_one(args.mp4, queue, cfg, args, tz):
            save(queue)

    elif args.cmd == "add-all":
        args.at, args.title = None, None
        added = 0
        for mp4 in sorted(Path(args.folder).glob("*.mp4")):
            added += add_one(mp4, queue, cfg, args, tz)
        if added:
            save(queue)
        print(f"{added} clip(s) queued.")

    elif args.cmd == "list":
        if not queue:
            print("Queue is empty.")
        for i in sorted(queue, key=lambda x: x["publish_at"]):
            when = datetime.fromisoformat(i["publish_at"]).astimezone(tz)
            st = ", ".join(f"{k}: {v.get('status')}" for k, v in i["platforms"].items())
            print(f"{when:%a %d %b %H:%M}  {i['id']:<32} {st}")
            for k, v in i["platforms"].items():
                if v.get("error"):
                    print(f"    {k} error: {v['error'][:160]}")

    elif args.cmd == "remove":
        keep = [i for i in queue if i["id"] != args.id]
        if len(keep) == len(queue):
            print(f"No item {args.id}")
            return 1
        gone = next(i for i in queue if i["id"] == args.id)
        vid = ROOT / gone["video"]
        if vid.exists():
            vid.unlink()
        save(keep)
        print(f"Removed {args.id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
