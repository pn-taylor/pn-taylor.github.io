"""Resize and recompress large images so pages load quickly.

Usage:
  python3 _scripts/shrink_images.py [FILE ...]   shrink the given files
  python3 _scripts/shrink_images.py              shrink everything under images/
  python3 _scripts/shrink_images.py --staged     shrink staged images and re-stage
                                                 them (used by .githooks/pre-commit)

An image is processed when its longest edge is over MAX_EDGE or the file is
over MAX_BYTES. Files keep their names, so posts don't need changing. EXIF
metadata (including phone GPS location) is dropped; the colour profile is kept.
A file is only replaced if the new version is smaller.
"""

import io
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageOps

MAX_EDGE = 2000
MAX_BYTES = 1_000_000
JPEG_QUALITY = 82
EXTENSIONS = {".jpg", ".jpeg", ".png"}


def shrink(path):
    old_size = path.stat().st_size
    with Image.open(path) as img:
        if max(img.size) <= MAX_EDGE and old_size <= MAX_BYTES:
            return False
        fmt = img.format
        icc = img.info.get("icc_profile")
        img = ImageOps.exif_transpose(img)
        img.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)

        buf = io.BytesIO()
        if fmt == "JPEG":
            img = img.convert("RGB")
            img.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True, icc_profile=icc)
        else:
            img.save(buf, "PNG", optimize=True, icc_profile=icc)

    if buf.tell() >= old_size:
        print(f"  kept   {path} (already as small as it gets)")
        return False
    path.write_bytes(buf.getvalue())
    print(f"  shrunk {path}: {old_size / 1e6:.1f} MB -> {buf.tell() / 1e6:.2f} MB")
    if fmt == "PNG" and buf.tell() > MAX_BYTES:
        print(f"         still over {MAX_BYTES / 1e6:.0f} MB; a photo saved as PNG would be much smaller as JPEG")
    return True


def staged_images():
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=AM", "-z"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [Path(p) for p in out.split("\0") if p]


def main(args):
    staged = args == ["--staged"]
    if staged:
        paths = staged_images()
    elif args:
        paths = [Path(a) for a in args]
    else:
        paths = sorted(Path("images").rglob("*"))

    changed = [p for p in paths if p.suffix.lower() in EXTENSIONS and p.is_file() and shrink(p)]

    if staged and changed:
        subprocess.run(["git", "add", "--", *map(str, changed)], check=True)
        print(f"Shrunk and re-staged {len(changed)} image(s).")


if __name__ == "__main__":
    main(sys.argv[1:])
