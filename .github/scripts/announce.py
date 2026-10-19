"""Announce newly published blog posts and reviews on Bluesky, Mastodon and Threads,
and post notes there as posts of their own.

Subcommands (all configured through environment variables, see the workflow):
  detect    Find posts to announce and write them to $GITHUB_OUTPUT. Only
            posts and reviews with `post_to_socials: true`, and notes
            (see wants_socials), are considered:
              push      posts added by the push, unless dated in the future
              schedule  posts dated today (site timezone) that were committed
                        before today; same-day posts are left to the push run
              manual    the one post given, whatever its date
  wait      Poll each post's URL until GitHub Pages is serving it.
  bluesky   Post a link card for each post to Bluesky.
  mastodon  Post each link to Mastodon via the toot CLI.
  threads   Post each link to Threads via the Threads API.
            A note isn't a link: its words, photos, link or quote become the
            post itself, with a link back only if it's too long to fit.
            Set DRY_RUN=1 to print what would be posted instead.
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
    "_notes": ("note", "New note"),
}
EXTENSIONS = (".md", ".markdown", ".html")
NULL_SHA = "0" * 40
FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)$")

# Bluesky rejects blobs over 1,000,000 bytes; leave some headroom.
MAX_THUMB_BYTES = 950_000
MAX_DESCRIPTION = 300

THREADS_API = "https://graph.threads.net"

# Longest post each network takes, and the most photos on one
LIMITS = {"bluesky": 300, "mastodon": 500, "threads": 500}
MAX_PHOTOS = {"bluesky": 4, "mastodon": 4, "threads": 10}
DRY_RUN = bool(os.environ.get("DRY_RUN"))


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


def body(path):
    text = Path(path).read_text(encoding="utf-8")
    # The front matter can be empty: "---" straight after "---"
    match = re.match(r"---[ \t]*\n(?:.*?\n)?---[ \t]*(?:\n|$)(.*)", text, re.S)
    return (match.group(1) if match else text).strip()


def plain(markdown):
    """Markdown to the plain text a social post wants."""
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", markdown)  # [words](url) -> words (url)
    text = re.sub(r"(\*\*|__|`)", "", text)
    text = re.sub(r"\\([#*_\[\]()`])", r"\1", text)  # \# -> #
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def note_info(path, meta, name):
    photos = [(meta["image"], meta.get("alt") or "")] if meta.get("image") else []
    photos += [(p["src"], p.get("alt") or "") for p in meta.get("images") or []]
    return {
        "path": path,
        "note": True,
        # Notes keep the date in their address (permalink /note/:name)
        "url": f"{SITE_URL}/note/{Path(path).stem}",
        "title": str(meta.get("title") or name),
        "text": plain(body(path)),
        "photos": photos,
        # A video goes to socials as a link; each network shows its own preview
        "link": meta.get("link") or meta.get("video"),
        "tags": [str(t) for t in meta.get("tags") or []],
        "quote": f"“{meta['quote']}”" + (f"\n— {meta['cite']}" if meta.get("cite") else "") if meta.get("quote") else "",
    }


def note_text(post, network, link_in_text=True):
    """The note as one post: words, then quote, then link. If it's too long
    for the network, the words are cut short and the note's address added."""
    tail = "\n\n".join(x for x in (post["quote"], post["link"] if link_in_text else "") if x)
    full = "\n\n".join(x for x in (post["text"], tail) if x)
    limit = LIMITS[network]
    # Tags not already in the words go on the end as hashtags, if there's room
    hashtags = " ".join(
        "#" + re.sub(r"\W", "", t) for t in post.get("tags", [])
        if not re.search(r"#" + re.escape(re.sub(r"\W", "", t)) + r"\b", full, re.I)
    )
    if hashtags and len(full) + len(hashtags) + 2 <= limit:
        full = f"{full}\n\n{hashtags}"
    if len(full) <= limit:
        return full
    more = f"… {post['url']}"
    room = limit - len(more) - (len(tail) + 2 if tail else 0)
    words = post["text"][: max(room, 0)].rsplit(" ", 1)[0].rstrip()
    return "\n\n".join(x for x in (words + more, tail) if x)


def photo_bytes(src):
    """A note's photo, from the repo (/images/...) or the web."""
    if re.match(r"https?://", src):
        req = urllib.request.Request(src, headers={"User-Agent": "pntaylor.net announce"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    return Path(src.lstrip("/")).read_bytes()


def photo_url(src):
    return src if re.match(r"https?://", src) else SITE_URL + src


def post_info(path):
    meta = front_matter(path)
    match = FILENAME_RE.match(Path(path).stem)
    if not match:
        raise ValueError(f"{path} is not named YYYY-MM-DD-title.md")
    name = match.group(2)
    prefix, label = COLLECTIONS[Path(path).parts[0]]
    if prefix == "note":
        return note_info(path, meta, name)
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


def wants_socials(path):
    """Posts and reviews go out when they say `post_to_socials: true`. Notes
    go out on their own: every note you write is posted, unless it was imported
    from Pixelfed (it's already on the fediverse) or says `skip_socials: true`."""
    meta = front_matter(path)
    if Path(path).parts[0] != "_notes":
        return meta.get("post_to_socials") is True
    if meta.get("pixelfed_id") or meta.get("skip_socials") is True:
        return False
    return bool(body(path) or any(meta.get(key) for key in ("image", "images", "video", "link", "quote")))


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
            if post_date(p, tz) != today or not wants_socials(p):
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
            if not wants_socials(p):
                print(f"Skipping {p}: not set to post to socials")
            elif post_date(p, tz) > today:
                print(f"Scheduled {p}: will go live and be announced on {post_date(p, tz)}")
            else:
                posts.append(p)

    for post in map(post_info, posts):
        print(f"Will {'post' if post.get('note') else 'announce'} {post['path']} -> {post['url']}")
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


def thumbnail(image_path, data=None, size=1200):
    """A JPEG small enough for Bluesky, from a file in the repo or from bytes."""
    from PIL import Image

    if data is None:
        path = Path(str(image_path).lstrip("/"))
        if not path.is_file():
            print(f"Featured image not found, posting without thumbnail: {path}")
            return None
        data = path.read_bytes()
    path = image_path
    img = Image.open(io.BytesIO(data))
    img.thumbnail((size, size))
    img = img.convert("RGB")
    for quality in (85, 75, 65, 55, 45):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality, optimize=True)
        if buf.tell() <= MAX_THUMB_BYTES:
            return buf.getvalue()
    print(f"Featured image too large even after compression: {path}")
    return None


def bluesky():
    client = None
    if not DRY_RUN:
        from atproto import Client, client_utils, models

        client = Client()
        client.login(os.environ["BLUESKY_USERNAME"], os.environ["BLUESKY_PASSWORD"])

    for post in load_posts():
        if post.get("note"):
            bluesky_note(client, post)
            continue
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


def bluesky_rich_text(text):
    """Bluesky only makes links and hashtags clickable if told where they are."""
    from atproto import client_utils

    builder = client_utils.TextBuilder()
    pos = 0
    for match in re.finditer(r"https?://\S+|(?<!\w)#\w+", text):
        builder.text(text[pos:match.start()])
        token = match.group(0).rstrip(".,!?)")
        if token.startswith("#"):
            builder.tag(token, token[1:])
        else:
            builder.link(token, token)
        pos = match.start() + len(token)
    builder.text(text[pos:])
    return builder


def bluesky_note(client, post):
    photos = post["photos"][: MAX_PHOTOS["bluesky"]]
    # With no photos, a link gets a card instead of taking up the post's words
    card = post["link"] and not photos
    text = note_text(post, "bluesky", link_in_text=not card)
    if DRY_RUN:
        print(f"[Bluesky] {text!r} photos={[p[0] for p in photos]} card={post['link'] if card else None}")
        return
    if photos:
        images = [(thumbnail(src, photo_bytes(src), size=2000), alt) for src, alt in photos]
        images = [(data, alt) for data, alt in images if data]
        client.send_images(bluesky_rich_text(text), images=[d for d, _ in images], image_alts=[a for _, a in images])
    else:
        from atproto import models

        embed = None
        if card:
            embed = models.AppBskyEmbedExternal.Main(
                external=models.AppBskyEmbedExternal.External(uri=post["link"], title=post["link"], description="")
            )
        client.send_post(bluesky_rich_text(text), embed=embed)
    print(f"Posted note to Bluesky: {post['url']}")


def mastodon_note(post):
    import tempfile

    cmd = ["toot", "post", note_text(post, "mastodon")]
    with tempfile.TemporaryDirectory() as tmp:
        for n, (src, alt) in enumerate(post["photos"][: MAX_PHOTOS["mastodon"]]):
            # Resized like Bluesky's, so a full-size phone photo can't go over
            # the server's upload limit
            path = Path(tmp) / f"{n}.jpg"
            if not DRY_RUN:
                original = photo_bytes(src)
                path.write_bytes(thumbnail(src, original, size=2000) or original)
            cmd += ["--media", str(path), "--description", alt or " "]
        if DRY_RUN:
            print(f"[Mastodon] {cmd}")
            return
        subprocess.run(cmd, check=True)
    print(f"Posted note to Mastodon: {post['url']}")


def mastodon():
    for post in load_posts():
        if post.get("note"):
            mastodon_note(post)
            continue
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
    if not os.environ.get("THREADS_ACCESS_TOKEN") and not DRY_RUN:
        print("THREADS_ACCESS_TOKEN is not set, skipping Threads.")
        return
    for post in load_posts():
        if post.get("note"):
            threads_note(post)
            continue
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


def alt_text(alt):
    return {"alt_text": alt} if alt else {}


def threads_note(post):
    text = note_text(post, "threads")
    photos = post["photos"][: MAX_PHOTOS["threads"]]
    if DRY_RUN:
        print(f"[Threads] {text!r} photos={[photo_url(src) for src, _ in photos]}")
        return
    if len(photos) == 1:
        src, alt = photos[0]
        container = threads_call("POST", "/v1.0/me/threads", media_type="IMAGE", image_url=photo_url(src), text=text, **alt_text(alt))
    elif photos:
        # Several photos: one container each, then a carousel holding them
        children = [
            threads_call("POST", "/v1.0/me/threads", media_type="IMAGE", image_url=photo_url(src), is_carousel_item="true", **alt_text(alt))["id"]
            for src, alt in photos
        ]
        time.sleep(10)
        container = threads_call("POST", "/v1.0/me/threads", media_type="CAROUSEL", children=",".join(children), text=text)
    else:
        extra = {"link_attachment": post["link"]} if post["link"] else {}
        container = threads_call("POST", "/v1.0/me/threads", media_type="TEXT", text=text, **extra)
    time.sleep(10)
    threads_call("POST", "/v1.0/me/threads_publish", creation_id=container["id"])
    print(f"Posted note to Threads: {post['url']}")


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
