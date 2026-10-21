"""Resize and recompress large images so pages load quickly, and make sure
each image really is the format its extension says.

Usage:
  python3 _scripts/shrink_images.py [FILE ...]   shrink the given files
  python3 _scripts/shrink_images.py              shrink everything under images/

An image is processed when its longest edge is over MAX_EDGE or the file is
over MAX_BYTES. Files keep their names, so posts don't need changing. A file is
only replaced if the new version is smaller.

Every image also loses its EXIF and XMP metadata (camera details, and the GPS
location a phone photo carries), whatever its size; the colour profile is
kept. A JPEG that needs nothing else is re-saved with its own compression
settings, so it looks the same.

An image whose contents don't match its extension (e.g. an AVIF or WebP saved
as .jpg) is always converted to the right format, since browsers cope but link
previews on Mastodon and friends don't. Files Pillow can't read at all (e.g.
HEIC) are reported and the run fails.
"""

import io
import sys
from pathlib import Path

from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError

MAX_EDGE = 2000
MAX_BYTES = 1_000_000
JPEG_QUALITY = 82
# Extension -> the format the file must actually be
EXTENSIONS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG"}


def has_metadata(img):
    return bool(img.getexif()) or any(key in img.info for key in ("xmp", "XML:com.adobe.xmp", "exif"))


def strip(path, img):
    """Re-save an image without its metadata, otherwise unchanged."""
    buf = io.BytesIO()
    icc = img.info.get("icc_profile")
    if img.format == "JPEG":
        img.save(buf, "JPEG", quality="keep", subsampling="keep", qtables="keep", icc_profile=icc)
    else:
        img.save(buf, "PNG", optimize=True, icc_profile=icc)
    path.write_bytes(buf.getvalue())
    print(f"  strip  {path}: removed photo metadata")
    return True


def shrink(path):
    old_size = path.stat().st_size
    fmt = EXTENSIONS[path.suffix.lower()]
    with Image.open(path) as img:
        mislabelled = img.format != fmt
        metadata = has_metadata(img)
        # A sideways phone photo is only upright thanks to its EXIF orientation,
        # so dropping that means turning the pixels too (the full path below)
        rotated = img.getexif().get(ExifTags.Base.Orientation, 1) != 1
        if not mislabelled and max(img.size) <= MAX_EDGE and old_size <= MAX_BYTES:
            if not metadata:
                return False
            if not rotated:
                return strip(path, img)
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
    if buf.tell() >= old_size and not metadata:
        print(f"  kept   {path} (already as small as it gets)")
        return False
    path.write_bytes(buf.getvalue())
    print(f"  shrunk {path}: {old_size / 1e6:.1f} MB -> {buf.tell() / 1e6:.2f} MB")
    if fmt == "PNG" and buf.tell() > MAX_BYTES:
        print(f"         still over {MAX_BYTES / 1e6:.0f} MB; a photo saved as PNG would be much smaller as JPEG")
    return True


def main(args):
    if args:
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

    if unreadable:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
