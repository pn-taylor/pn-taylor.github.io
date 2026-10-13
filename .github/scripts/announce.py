"""Announce newly published blog posts on Bluesky and Mastodon.

Subcommands (all configured through environment variables, see the workflow):
  detect    Find posts added by this push (or the one given manually) that
            have `post_to_socials: true`, and write them to $GITHUB_OUTPUT.
  wait      Poll each post's URL until GitHub Pages is serving it.
  bluesky   Post a link card for each post to Bluesky.
  mastodon  Post each link to Mastodon via the toot CLI.
"""

import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

SITE_URL = "https://www.pntaylor.net"
POSTS_DIR = "_posts"
NULL_SHA = "0" * 40
FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)$")

# Bluesky rejects blobs over 1,000,000 bytes; leave some headroom.
MAX_THUMB_BYTES = 950_000
MAX_DESCRIPTION = 300


def front_matter(path):
    text = Path(path).read_text(encoding="utf-8")
    match = re.match(r"---\s*\n(.*?)\n---\s*$", text, re.S | re.M)
    return (yaml.safe_load(match.group(1)) or {}) if match else {}


def slugify(value):
    # Matches Jekyll's default slugify mode: runs of non-alphanumerics become
    # a single hyphen, trimmed and lowercased.
    return re.sub(r"[\W_]+", "-", str(value)).strip("-").lower()


def post_info(path):
    meta = front_matter(path)
    match = FILENAME_RE.match(Path(path).stem)
    if not match:
        raise ValueError(f"{path} is not named YYYY-MM-DD-title.md")
    name = match.group(2)
    return {
        "path": path,
        "url": f"{SITE_URL}/blog/{slugify(meta.get('slug') or name)}",
        "title": str(meta.get("title") or name),
        "excerpt": str(meta.get("excerpt") or "").strip(),
        "image": meta.get("featured_image"),
    }


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
    out = subprocess.run(cmd + ["--", POSTS_DIR], capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p.endswith((".md", ".markdown", ".html"))]


def detect():
    manual = os.environ.get("MANUAL_POST", "").strip()
    if manual:
        if not Path(manual).is_file():
            sys.exit(f"Post not found: {manual}")
        posts = [manual]
    else:
        added = git_added_posts(os.environ.get("BEFORE", ""), os.environ["AFTER"])
        posts = [p for p in added if front_matter(p).get("post_to_socials") is True]
        for p in sorted(set(added) - set(posts)):
            print(f"Skipping {p}: post_to_socials is not true")

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
        text = client_utils.TextBuilder().text("New blog post: ").link(post["title"], post["url"])
        client.send_post(text, embed=embed)
        print(f"Posted to Bluesky: {post['url']}")


def mastodon():
    for post in load_posts():
        # Mastodon builds the link preview itself from the page's metadata.
        subprocess.run(["toot", "post", f"New blog post: {post['title']}\n\n{post['url']}"], check=True)
        print(f"Posted to Mastodon: {post['url']}")


if __name__ == "__main__":
    commands = {"detect": detect, "wait": wait, "bluesky": bluesky, "mastodon": mastodon}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"usage: {sys.argv[0]} {{{','.join(commands)}}}")
    commands[sys.argv[1]]()
