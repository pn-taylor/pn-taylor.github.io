"""Announce newly published blog posts and reviews on Bluesky, Mastodon and Threads.

Subcommands (all configured through environment variables, see the workflow):
  detect    Find posts to announce and write them to $GITHUB_OUTPUT. Only
            posts and reviews with `post_to_socials: true` are considered:
              push      posts added by the push, unless dated in the future
              schedule  posts dated today (site timezone) that were committed
                        before today; same-day posts are left to the push run
              manual    the one post given, whatever its date
  wait      Poll each post's URL until GitHub Pages is serving it.
  bluesky   Post a link card for each post to Bluesky.
  mastodon  Post each link to Mastodon via the toot CLI.
  threads   Post each link to Threads via the Threads API.
  refresh-threads
            Swap the Threads access token for a fresh 60-day one and save it
            back to the repo's THREADS_ACCESS_TOKEN secret with the gh CLI.
"""

import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

SITE_URL = "https://www.pntaylor.net"
# Collection folder -> (URL prefix, label the announcement starts with)
COLLECTIONS = {
    "_posts": ("blog", "New blog post"),
    "_reviews": ("review", "New review"),
}
EXTENSIONS = (".md", ".markdown", ".html")
NULL_SHA = "0" * 40
FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)$")

# Bluesky rejects blobs over 1,000,000 bytes; leave some headroom.
MAX_THUMB_BYTES = 950_000
MAX_DESCRIPTION = 300

THREADS_API = "https://graph.threads.net"


def front_matter(path):
    text = Path(path).read_text(encoding="utf-8")
    match = re.match(r"---\s*\n(.*?)\n---\s*$", text, re.S | re.M)
    return (yaml.safe_load(match.group(1)) or {}) if match else {}


def slugify(value):
    # Matches Jekyll's default slugify mode: runs of non-alphanumerics become
    # a single hyphen, trimmed and lowercased.
    return re.sub(r"[\W_]+", "-", str(value)).strip("-").lower()


def stars(rating):
    # "★★★★☆ 4/5"; half ratings round down on the stars, the number is exact.
    full = max(0, min(5, int(float(rating))))
    return f"{'★' * full}{'☆' * (5 - full)} {float(rating):g}/5"


def post_info(path):
    meta = front_matter(path)
    match = FILENAME_RE.match(Path(path).stem)
    if not match:
        raise ValueError(f"{path} is not named YYYY-MM-DD-title.md")
    name = match.group(2)
    prefix, label = COLLECTIONS[Path(path).parts[0]]
    rating = meta.get("rating")
    return {
        "path": path,
        "url": f"{SITE_URL}/{prefix}/{slugify(meta.get('slug') or name)}",
        "title": str(meta.get("title") or name),
        "label": label,
        "rating": stars(rating) if rating is not None else "",
        "excerpt": str(meta.get("excerpt") or meta.get("verdict") or "").strip(),
        "image": meta.get("cover") or meta.get("featured_image"),
    }


def site_timezone():
    config = yaml.safe_load(Path("_config.yml").read_text(encoding="utf-8")) or {}
    return ZoneInfo(config.get("timezone") or "UTC")


def post_date(path, tz):
    # Jekyll uses a front matter `date:` if there is one, else the filename.
    value = front_matter(path).get("date")
    if isinstance(value, datetime):
        return (value.astimezone(tz) if value.tzinfo else value).date()
    if isinstance(value, date):
        return value
    if value:
        return date.fromisoformat(str(value)[:10])
    match = FILENAME_RE.match(Path(path).stem)
    if not match:
        raise ValueError(f"{path} is not named YYYY-MM-DD-title.md")
    return date.fromisoformat(match.group(1))


def first_committed(path, tz):
    out = subprocess.run(
        ["git", "log", "--diff-filter=A", "--format=%cI", "--", path],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    return datetime.fromisoformat(out[-1]).astimezone(tz).date() if out else None


def load_posts():
    return [post_info(path) for path in json.loads(os.environ["POSTS"])]


def git_added_posts(before, after):
    if before and before != NULL_SHA and subprocess.run(
        ["git", "cat-file", "-e", f"{before}^{{commit}}"], capture_output=True
    ).returncode == 0:
        cmd = ["git", "diff", "-M", "--name-only", "--diff-filter=A", "-z", before, after]
    else:
        # First push to the branch, or history was rewritten: fall back to
        # what the head commit itself added.
        cmd = ["git", "diff-tree", "--no-commit-id", "--root", "-r", "-M", "--name-only", "--diff-filter=A", "-z", after]
    out = subprocess.run(cmd + ["--", *COLLECTIONS], capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p.endswith(EXTENSIONS)]


def detect():
    manual = os.environ.get("MANUAL_POST", "").strip()
    if manual:
        if not Path(manual).is_file():
            sys.exit(f"Post not found: {manual}")
        posts = [manual]
    elif os.environ.get("EVENT") == "schedule":
        tz = site_timezone()
        today = datetime.now(tz).date()
        print(f"Looking for posts scheduled for {today}")
        posts = []
        found = (p for d in COLLECTIONS for p in Path(d).rglob("*") if p.suffix in EXTENSIONS)
        for p in sorted(str(p) for p in found):
            if post_date(p, tz) != today or front_matter(p).get("post_to_socials") is not True:
                continue
            committed = first_committed(p, tz)
            if committed is None or committed >= today:
                print(f"Skipping {p}: pushed today, so the push run announced it")
            else:
                posts.append(p)
    else:
        tz = site_timezone()
        today = datetime.now(tz).date()
        added = git_added_posts(os.environ.get("BEFORE", ""), os.environ["AFTER"])
        posts = []
        for p in sorted(added):
            if front_matter(p).get("post_to_socials") is not True:
                print(f"Skipping {p}: post_to_socials is not true")
            elif post_date(p, tz) > today:
                print(f"Scheduled {p}: will go live and be announced on {post_date(p, tz)}")
            else:
                posts.append(p)

    for post in map(post_info, posts):
        print(f"Will announce {post['path']} -> {post['url']}")
    if not posts:
        print("No new posts to announce.")

    with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
        fh.write(f"posts={json.dumps(posts)}\n")


def wait():
    deadline = time.time() + int(os.environ.get("WAIT_SECONDS", "900"))
    pending = {post["url"] for post in load_posts()}
    while pending:
        for url in sorted(pending):
            try:
                with urllib.request.urlopen(url, timeout=15) as resp:
                    if resp.status == 200:
                        print(f"Live: {url}")
                        pending.discard(url)
            except (urllib.error.URLError, TimeoutError) as err:
                print(f"Not live yet: {url} ({err})")
        if pending:
            if time.time() > deadline:
                sys.exit(f"Gave up waiting for: {', '.join(sorted(pending))}")
            time.sleep(30)


def truncate(text, limit):
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def thumbnail(image_path):
    from PIL import Image

    path = Path(str(image_path).lstrip("/"))
    if not path.is_file():
        print(f"Featured image not found, posting without thumbnail: {path}")
        return None
    img = Image.open(path)
    img.thumbnail((1200, 1200))
    img = img.convert("RGB")
    for quality in (85, 75, 65, 55, 45):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality, optimize=True)
        if buf.tell() <= MAX_THUMB_BYTES:
            return buf.getvalue()
    print(f"Featured image too large even after compression: {path}")
    return None


def bluesky():
    from atproto import Client, client_utils, models

    client = Client()
    client.login(os.environ["BLUESKY_USERNAME"], os.environ["BLUESKY_PASSWORD"])

    for post in load_posts():
        thumb = None
        if post["image"]:
            data = thumbnail(post["image"])
            if data:
                thumb = client.upload_blob(data).blob

        embed = models.AppBskyEmbedExternal.Main(
            external=models.AppBskyEmbedExternal.External(
                uri=post["url"],
                title=post["title"],
                description=truncate(post["excerpt"], MAX_DESCRIPTION),
                thumb=thumb,
            )
        )
        text = client_utils.TextBuilder().text(f"{post['label']}: ").link(post["title"], post["url"])
        if post["rating"]:
            text.text(f" {post['rating']}")
        client.send_post(text, embed=embed)
        print(f"Posted to Bluesky: {post['url']}")


def mastodon():
    for post in load_posts():
        # Mastodon builds the link preview itself from the page's metadata.
        rating = f" {post['rating']}" if post["rating"] else ""
        subprocess.run(["toot", "post", f"{post['label']}: {post['title']}{rating}\n\n{post['url']}"], check=True)
        print(f"Posted to Mastodon: {post['url']}")


def threads_call(method, path, **params):
    params["access_token"] = os.environ["THREADS_ACCESS_TOKEN"]
    query = urllib.parse.urlencode(params)
    url = f"{THREADS_API}{path}"
    if method == "GET":
        req = urllib.request.Request(f"{url}?{query}")
    else:
        req = urllib.request.Request(url, data=query.encode(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as err:
        sys.exit(f"Threads API {path} failed: {err.code} {err.read().decode(errors='replace')}")


def threads():
    if not os.environ.get("THREADS_ACCESS_TOKEN"):
        print("THREADS_ACCESS_TOKEN is not set, skipping Threads.")
        return
    for post in load_posts():
        # Threads builds the link card itself from the page's metadata.
        rating = f" {post['rating']}" if post["rating"] else ""
        container = threads_call(
            "POST", "/v1.0/me/threads",
            media_type="TEXT",
            text=f"{post['label']}: {post['title']}{rating}\n\n{post['url']}",
            link_attachment=post["url"],
        )
        # Meta recommends a short pause before publishing a new container.
        time.sleep(10)
        threads_call("POST", "/v1.0/me/threads_publish", creation_id=container["id"])
        print(f"Posted to Threads: {post['url']}")


def refresh_threads():
    if not os.environ.get("GH_TOKEN"):
        sys.exit("SECRETS_WRITE_TOKEN is not set, so the refreshed token can't be saved.")
    result = threads_call("GET", "/refresh_access_token", grant_type="th_refresh_token")
    token = result["access_token"]
    print(f"::add-mask::{token}")
    expires = datetime.now(site_timezone()) + timedelta(seconds=int(result["expires_in"]))
    print(f"New token is valid until {expires:%Y-%m-%d %H:%M %Z} ({int(result['expires_in']) // 86400} days).")
    subprocess.run(
        ["gh", "secret", "set", "THREADS_ACCESS_TOKEN", "--repo", os.environ["REPO"]],
        input=token, text=True, check=True,
    )
    print("Saved refreshed Threads token.")


if __name__ == "__main__":
    commands = {
        "detect": detect, "wait": wait, "bluesky": bluesky, "mastodon": mastodon,
        "threads": threads, "refresh-threads": refresh_threads,
    }
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"usage: {sys.argv[0]} {{{','.join(commands)}}}")
    commands[sys.argv[1]]()
