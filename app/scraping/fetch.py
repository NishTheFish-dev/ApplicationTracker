from __future__ import annotations
import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from ..config import get_settings
from urllib.parse import urlparse


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=4))
def fetch_url(url: str) -> str:
    settings = get_settings()
    # Use a modern browser-like header set
    base_headers = {
        "User-Agent": settings.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    timeout = settings.REQUEST_TIMEOUT_SECONDS

    # First attempt: direct GET
    resp = requests.get(url, headers=base_headers, timeout=timeout, allow_redirects=True)
    if resp.status_code == 403:
        # Some sites (Akamai/Cloudflare) require initial cookies from the root and/or a Referer
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}/"
        with requests.Session() as s:
            s.headers.update(base_headers)
            try:
                # Prime cookies from the root domain
                s.get(base, timeout=timeout, allow_redirects=True)
            except Exception:
                pass
            headers2 = dict(base_headers)
            headers2["Referer"] = base
            resp2 = s.get(url, headers=headers2, timeout=timeout, allow_redirects=True)
            if resp2.ok:
                return resp2.text

        # If still blocked and a proxy-reader is configured, try that as a last resort
        proxy_base = (settings.FETCH_PROXY_READER or "").strip()
        if proxy_base:
            # Many reader services accept the original URL appended as path, e.g.
            #   https://r.jina.ai/https://example.com/page
            proxy_url = proxy_base.rstrip("/") + "/" + url
            resp3 = requests.get(proxy_url, headers=base_headers, timeout=timeout, allow_redirects=True)
            resp3.raise_for_status()
            return resp3.text

    resp.raise_for_status()
    return resp.text
