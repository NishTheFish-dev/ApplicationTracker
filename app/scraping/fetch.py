from __future__ import annotations
import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from ..config import get_settings


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=4))
def fetch_url(url: str) -> str:
    settings = get_settings()
    headers = {
        "User-Agent": settings.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    resp = requests.get(url, headers=headers, timeout=settings.REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.text
