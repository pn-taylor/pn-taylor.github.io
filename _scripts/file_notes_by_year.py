"""Move notes into year folders, like the blog posts.

Usage:
  python3 _scripts/file_notes_by_year.py

A note at the top of _notes/ (named YYYY-MM-DD-...) moves to _notes/YYYY/.
Pages CMS is set up to save new notes there itself; this catches any that
land at the top anyway. A note's address comes from its filename, not its
folder, so moving it doesn't change the address.
"""

import re
from pathlib import Path

NOTES = Path("_notes")

for path in sorted(NOTES.glob("*.md")):
    match = re.match(r"(\d{4})-\d{2}-\d{2}-", path.name)
    if not match:
        continue
    target = NOTES / match.group(1) / path.name
    if target.exists():
        print(f"Not moving {path}: {target} already exists")
        continue
    target.parent.mkdir(exist_ok=True)
    path.rename(target)
    print(f"Moved {path} -> {target}")
