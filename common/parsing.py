"""Forgiving parsers for request data. A bad number is a message, never a 500."""

import re
from decimal import Decimal, InvalidOperation

HEX_COLOUR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def to_int(value, default=None, minimum=None, maximum=None):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    if minimum is not None and number < minimum:
        number = minimum
    if maximum is not None and number > maximum:
        number = maximum
    return number


def to_decimal(value, default=None):
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return default


def is_hex_colour(value):
    return bool(HEX_COLOUR_RE.match(value or ""))


def open_workbook(uploaded):
    """Load an uploaded .xlsx, turning any parse failure into a readable ValueError."""
    from zipfile import BadZipFile

    from openpyxl import load_workbook

    try:
        return load_workbook(uploaded, read_only=True, data_only=True)
    except (BadZipFile, KeyError, OSError, ValueError) as exc:
        raise ValueError("That file is not a valid Excel workbook (.xlsx).") from exc
