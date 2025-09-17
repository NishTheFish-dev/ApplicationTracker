from __future__ import annotations
import datetime as dt
from typing import Optional
import dateparser


def parse_date(value: Optional[str]) -> dt.date:
    """Parse a date string or return today when value is empty/None."""
    if value is None or value == "":
        return dt.date.today()
    parsed = dateparser.parse(value)
    if not parsed:
        raise ValueError(f"Could not parse date: {value}")
    return parsed.date()


def parse_optional_date(value: Optional[str]) -> Optional[dt.date]:
    if not value:
        return None
    parsed = dateparser.parse(value)
    return parsed.date() if parsed else None
