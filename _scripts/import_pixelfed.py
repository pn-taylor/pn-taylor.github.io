"""Copy Pixelfed posts onto the site as notes.

Usage:
  python3 _scripts/import_pixelfed.py

Each public Pixelfed post becomes _notes/YYYY-MM-DD-some-words.md, with its
photos copied to images/notes/pixelfed/ so they stay on the site whatever
happens to the Pixelfed post. Posts already imported (matched by `pixelfed_id`
in a note's front matter) are skipped, so it's safe to run again and only picks
up new ones. A note still pointing at a photo on Pixelfed gets its own copy.
Run _scripts/shrink_images.py afterwards, or let the pre-commit hook do it.

Uses the endpoint Pixelfed's own profile page reads, which needs no login.
"""

import json
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

INSTANCE = "https://pixelfed.social"
ACCOUNT_ID = "425849081745450241"  # @pntaylor@pixelfed.social
NOTES = Path("_notes")
IMAGES = Path("images/notes/pixelfed")
TIMEZONE = ZoneInfo("Australia/Canberra")
PAGE_SIZE = 24  # The most Pixelfed allows per request
USER_AGENT = "pntaylor.net notes import (https://www.pntaylor.net)"


def get(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def fetch_posts():
    """Every public post, newest first."""
    base = f"{INSTANCE}/api/pixelfed/v1/accounts/{ACCOUNT_ID}/statuses?limit={PAGE_SIZE}"
    posts, url = [], base
    while True:
        page = json.loads(get(url))
        if not isinstance(page, list) or not page:
            return posts
        posts += page
        url = f"{base}&max_id={page[-1]['id']}"
        time.sleep(1)


def imported_ids():
    found = set()
    for path in NOTES.glob("*.md"):
        match = re.search(r'^pixelfed_id: "?(\d+)"?$', path.read_text(), re.M)
        if match:
            found.add(match.group(1))
    return found


def caption_and_tags(post):
    """The caption as Markdown, and its hashtags as site tags (lower case, like
    the blog's). A block of hashtags at the end comes off the caption, since the
    note shows its tags anyway, unless the first is part of the sentence
    ("here in #canberra", "in sunny #Canberra")."""
    text = (post.get("content_text") or "").replace("\r", "").strip()
    tags = list(dict.fromkeys(tag.lower() for tag in re.findall(r"(?<!\w)#(\w+)", text)))
    kept = re.match(r"(.*\b(?:in|at|of|on|from|to|around|near|over|by)(?:\s+\w+)?\s+#\w+)(\s*#\w+)*\s*$", text, re.I | re.S)
    text = kept.group(1) if kept else re.sub(r"(\s*#\w+)+\s*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    # A line starting with a hashtag would become a Markdown heading
    return re.sub(r"^#", r"\\#", text, flags=re.M), tags


def title_and_slug(text):
    """A short title from the caption's first sentence; a hashtag in it keeps
    its word ("#Floriade" -> "Floriade")."""
    words = re.sub(r"\\?#(\w+)", r"\1", text).replace("\n", " ")
    first = re.split(r"(?<=[.!?])\s", words.strip(), maxsplit=1)[0].strip(" .!?")
    if not first:
        return "Photo", "photo"
    title = first if len(first) <= 60 else first[:60].rsplit(" ", 1)[0] + "…"
    slug = "-".join(re.findall(r"[a-z0-9]+", first.lower())[:5]) or "photo"
    return title, slug


def save_photo(url, name):
    """Copy a photo from Pixelfed; returns its address on the site."""
    ext = Path(url.split("?")[0]).suffix.lower()
    # shrink_images.py converts anything that isn't really a JPEG or PNG
    path = IMAGES / f"{name}{ext if ext in ('.jpg', '.jpeg', '.png') else '.jpg'}"
    if not path.exists():
        IMAGES.mkdir(parents=True, exist_ok=True)
        path.write_bytes(get(url))
    return "/" + path.as_posix()


def photos(post):
    """[(photo address on the site, alt text), ...]"""
    images = [m for m in post.get("media_attachments", []) if m.get("type") == "image"]
    return [
        (save_photo(media["url"], f"{post['id']}-{n}"), (media.get("description") or "").strip())
        for n, media in enumerate(images, 1)
    ]


def localise_existing():
    """Give notes that still point at photos on Pixelfed their own copies."""
    for path in sorted(NOTES.glob("*.md")):
        text = path.read_text()
        match = re.search(r'^pixelfed_id: "?(\d+)"?$', text, re.M)
        remote = re.findall(r"^(?:image:|  - src:) (https?://\S+)$", text, re.M)
        if not match or not remote:
            continue
        for n, url in enumerate(remote, 1):
            text = text.replace(url, save_photo(url, f"{match.group(1)}-{n}"), 1)
        path.write_text(text)
        print(f"Copied {len(remote)} photo{'s' if len(remote) > 1 else ''} for {path}")


def write_note(post, found):
    created = datetime.fromisoformat(post["created_at"].replace("Z", "+00:00")).astimezone(TIMEZONE)
    text, tags = caption_and_tags(post)
    title, slug = title_and_slug(text)
    path = NOTES / f"{created:%Y-%m-%d}-{slug}.md"
    n = 2
    while path.exists():
        path = NOTES / f"{created:%Y-%m-%d}-{slug}-{n}.md"
        n += 1

    # json.dumps gives a double-quoted string, which is also valid YAML
    lines = ["---", f"title: {json.dumps(title, ensure_ascii=False)}", f"date: {created:%Y-%m-%d %H:%M:%S %z}"]
    if len(found) == 1:
        lines += [f"image: {found[0][0]}", f"alt: {json.dumps(found[0][1], ensure_ascii=False)}"]
    else:
        lines.append("images:")
        for src, alt in found:
            lines += [f"  - src: {src}", f"    alt: {json.dumps(alt, ensure_ascii=False)}"]
    if tags:
        lines.append(f"tags: [{', '.join(tags)}]")
    lines += [f"source: {post['url']}", f'pixelfed_id: "{post["id"]}"', "---", "", text, ""]
    path.write_text("\n".join(lines))
    return path


def main():
    localise_existing()
    done = imported_ids()
    added = 0
    for post in reversed(fetch_posts()):
        if post["id"] in done or post.get("visibility") != "public":
            continue
        found = photos(post)
        if not found:
            continue
        print(f"Added {write_note(post, found)} ({len(found)} photo{'s' if len(found) > 1 else ''})")
        added += 1
    print(f"{added} new note{'s' if added != 1 else ''} from Pixelfed")


if __name__ == "__main__":
    sys.exit(main())
