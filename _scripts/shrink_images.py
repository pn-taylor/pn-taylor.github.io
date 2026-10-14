"""Resize and recompress large images so pages load quickly, and make sure
each image really is the format its extension says.

Usage:
  python3 _scripts/shrink_images.py [FILE ...]   shrink the given files
  python3 _scripts/shrink_images.py              shrink everything under images/
  python3 _scripts/shrink_images.py --staged     shrink staged images and re-stage
                                                 them (used by .githooks/pre-commit)

An image is processed when its longest edge is over MAX_EDGE or the file is
over MAX_BYTES. Files keep their names, so posts don't need changing. EXIF
metadata (including phone GPS location) is dropped; the colour profile is kept.
A file is only replaced if the new version is smaller.

An image whose contents don't match its extension (e.g. an AVIF or WebP saved
as .jpg) is always converted to the right format, since browsers cope but link
previews on Mastodon and friends don't. Files Pillow can't read at all (e.g.
HEIC) are reported, and in --staged mode the commit is stopped.
"""

import io
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_EDGE = 2000
MAX_BYTES = 1_000_000
JPEG_QUALITY = 82
# Extension -> the format the file must actually be
EXTENSIONS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG"}


def shrink(path):
    old_size = path.stat().st_size
    fmt = EXTENSIONS[path.suffix.lower()]
    with Image.open(path) as img:
        mislabelled = img.format != fmt
        if not mislabelled and max(img.size) <= MAX_EDGE and old_size <= MAX_BYTES:
            return False
        actual = img.format
        icc = img.info.get("icc_profile")
        img = ImageOps.exif_transpose(img)
        img.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)

        buf = io.BytesIO()
        if fmt == "JPEG":
            if img.mode in ("RGBA", "LA", "P"):
                # JPEG has no transparency: flatten onto white.
                img = img.convert("RGBA")
                bg = Image.new("RGB", img.size, "white")
                bg.paste(img, mask=img.getchannel("A"))
                img = bg
            img = img.convert("RGB")
            img.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True, icc_profile=icc)
        else:
            if img.mode not in ("1", "L", "LA", "P", "RGB", "RGBA", "I", "I;16"):
                img = img.convert("RGBA")
            img.save(buf, "PNG", optimize=True, icc_profile=icc)

    if mislabelled:
        path.write_bytes(buf.getvalue())
        print(f"  fixed  {path}: was really {actual}, converted to {fmt} ({buf.tell() / 1e6:.2f} MB)")
        return True
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

    changed, unreadable = [], []
    for p in paths:
        if p.suffix.lower() not in EXTENSIONS or not p.is_file():
            continue
        try:
            if shrink(p):
                changed.append(p)
        except UnidentifiedImageError:
            print(f"  ERROR  {p}: not a readable image (HEIC? corrupt?); re-export it as a real {p.suffix} file")
            unreadable.append(p)

    if staged and changed:
        subprocess.run(["git", "add", "--", *map(str, changed)], check=True)
        print(f"Fixed and re-staged {len(changed)} image(s).")
    if unreadable:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
