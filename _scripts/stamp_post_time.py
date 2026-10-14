"""Give new posts and reviews dated today the time they were committed.

Usage:
  python3 _scripts/stamp_post_time.py --staged   (used by .githooks/pre-commit)

Without a time Jekyll dates a post at midnight, and that's what link previews
(e.g. the "14h ago" on a Mastodon card) show. So when a newly added post or
review is dated today and has no time, this writes `date:` with the current
time into its front matter and re-stages it.

Left alone: posts dated in the future (they go live at the 00:05 rebuild, so
midnight is right) or in the past, posts that already have a time, and posts
that were already committed before.
"""

import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

FOLDERS = ("_posts/", "_reviews/")
EXTENSIONS = (".md", ".markdown", ".html")
FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")
FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n", re.S)
DATE_LINE_RE = re.compile(r"^date:[ \t]*(.*?)[ \t]*$", re.M)


def site_timezone():
    # Read just the one setting, so the hook doesn't need PyYAML.
    match = re.search(r"^timezone:\s*['\"]?([\w/+-]+)", Path("_config.yml").read_text(encoding="utf-8"), re.M)
    return ZoneInfo(match.group(1) if match else "UTC")


def added_posts():
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=A", "-z"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [Path(p) for p in out.split("\0") if p.startswith(FOLDERS) and p.endswith(EXTENSIONS)]


def stamp(path, now):
    text = path.read_text(encoding="utf-8")
    fm = FRONT_MATTER_RE.match(text)
    name = FILENAME_RE.match(path.name)
    if not fm or not name:
        return False

    line = DATE_LINE_RE.search(fm.group(1))
    value = line.group(1).strip("'\"") if line else ""
    if re.search(r"\d:\d\d", value):
        return False  # already has a time
    try:
        day = date.fromisoformat(value[:10] if value else name.group(1))
    except ValueError:
        return False
    if day != now.date():
        return False

    stamped = f"date: {now:%Y-%m-%d %H:%M:%S %z}"
    if line:
        body = fm.group(1)[: line.start()] + stamped + fm.group(1)[line.end():]
    else:
        body = fm.group(1) + stamped + "\n"
    path.write_text(f"---\n{body}---\n{text[fm.end():]}", encoding="utf-8")
    print(f"  dated  {path}: {now:%-I:%M %p} today")
    return True


def main(args):
    if args != ["--staged"]:
        sys.exit(__doc__)
    now = datetime.now(site_timezone()).replace(microsecond=0)
    changed = [p for p in added_posts() if p.is_file() and stamp(p, now)]
    if changed:
        subprocess.run(["git", "add", "--", *map(str, changed)], check=True)


if __name__ == "__main__":
    main(sys.argv[1:])
