"""Upload checks. Files land under MEDIA_ROOT and may be served to parents, so trust nothing."""

from django.core.exceptions import ValidationError

MAX_IMAGE_BYTES = 2 * 1024 * 1024
ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}


def clean_image(upload):
    """Return the upload if it is a real, reasonably sized image; raise ValidationError otherwise."""
    from PIL import Image, UnidentifiedImageError

    if upload.size > MAX_IMAGE_BYTES:
        raise ValidationError("Images must be 2 MB or smaller.")
    try:
        image = Image.open(upload)
        image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ValidationError("That file is not an image we can read.") from exc
    if image.format not in ALLOWED_IMAGE_FORMATS:
        raise ValidationError("Use a PNG, JPEG, WebP or GIF image.")
    upload.seek(0)
    return upload
