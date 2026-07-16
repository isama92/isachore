"""Avatar storage: decode, validate, square-crop, resize and store uploaded
profile pictures on disk (under <storage_dir>/avatars).

Re-encoding every upload to a single format (webp) means a disguised or
malformed file never reaches disk in its original form, metadata is stripped,
and stored files are size-bounded regardless of the input dimensions.
"""

import secrets
from io import BytesIO
from pathlib import Path

from PIL import Image

from app.core.config import settings


def avatars_dir() -> Path:
    """Absolute-ish path to the avatars folder, created on demand. Read at call
    time so tests can point settings.storage_dir at a tmp dir."""
    directory = Path(settings.storage_dir) / "avatars"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _process(data: bytes) -> bytes:
    """Decode, square-crop, resize and re-encode to webp. Raises ValueError if
    the bytes are not a usable image (including decompression bombs)."""
    try:
        with Image.open(BytesIO(data)) as probe:
            probe.verify()  # cheap integrity check; leaves the image unusable
        with Image.open(BytesIO(data)) as img:
            # Reject oversized images from the header before we allocate the
            # decoded bitmap: the byte cap only bounds the compressed upload, so
            # a small highly-compressed file could otherwise decode to hundreds
            # of MB of RGB.
            width, height = img.size
            if width * height > settings.avatar_max_pixels:
                raise ValueError("Image dimensions too large")
            img = img.convert("RGB")
            side = min(img.size)
            left = (img.width - side) // 2
            top = (img.height - side) // 2
            img = img.crop((left, top, left + side, top + side))
            img = img.resize((settings.avatar_px, settings.avatar_px))
            out = BytesIO()
            img.save(out, format="WEBP", quality=85)
            return out.getvalue()
    except Exception as exc:
        # Decoding untrusted bytes can fail in many ways (UnidentifiedImageError,
        # OSError, ValueError, SyntaxError on a corrupt-but-recognised header,
        # DecompressionBombError, ...). Any failure means "not a usable image" ->
        # a clean 400, never a 500. The try block only does image work, so this
        # can't mask an unrelated bug.
        raise ValueError("Not a valid image") from exc


def store_avatar(data: bytes) -> str:
    """Process and write an avatar, returning its (random) filename."""
    processed = _process(data)
    filename = f"{secrets.token_hex(16)}.webp"
    (avatars_dir() / filename).write_bytes(processed)
    return filename


def delete_avatar(filename: str | None) -> None:
    """Best-effort removal of a stored avatar; a missing file is not an error."""
    if not filename:
        return
    (avatars_dir() / filename).unlink(missing_ok=True)
