from __future__ import annotations
import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from ..config import get_settings
from urllib.parse import urlparse
import re


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

    # Helper to decide if we should attempt a reader-proxy fallback for JS-heavy shells
    def _should_reader_fallback(body: str) -> bool:
        try:
            host = urlparse(url).netloc.lower()
        except Exception:
            host = ""
        text = (body or "").lower()
        if "ultipro.com" in host:
            # UltiPro (UKG) sites frequently ship JS shells; prefer reader when shell indicators are present
            if (
                "unsupported browser" in text
                or "data-bind=" in text
                or "ko.applybindings" in text
                or "knockout" in text
            ):
                return True
            # Even if those markers aren't present, if we don't see the opportunity title hooks, try reader
            if ("data-automation=\"opportunity-title\"" not in text) and ("formattedtitle" not in text):
                return True
        return False

    def _render_with_playwright(url: str, ua: str, timeout_ms: int = 8000) -> str | None:
        """Try to render the page with Playwright if available. Returns HTML or None.
        We keep this optional to avoid a hard dependency; the user can `pip install playwright`
        and `playwright install chromium` to enable this path.
        """
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(user_agent=ua)
                page = context.new_page()
                page.set_default_timeout(timeout_ms)
                page.goto(url, wait_until="domcontentloaded")
                # For UltiPro, wait a bit and try to detect known hooks
                try:
                    page.wait_for_selector("[data-automation='opportunity-title']", timeout=timeout_ms)
                except Exception:
                    # Still proceed; content may be elsewhere
                    pass
                content = page.content()
                context.close()
                browser.close()
                return content
        except Exception:
            return None

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
    body = resp.text
    if _should_reader_fallback(body):
        proxy_base = (settings.FETCH_PROXY_READER or "").strip() or "https://r.jina.ai"
        try:
            proxy_url = proxy_base.rstrip("/") + "/" + url
            resp_reader = requests.get(proxy_url, headers=base_headers, timeout=timeout, allow_redirects=True)
            if resp_reader.ok and resp_reader.text:
                return resp_reader.text
        except Exception:
            # Swallow errors and fall back to original body
            pass
    # As a last resort, try Playwright-rendered HTML for UltiPro pages
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        host = ""
    if "ultipro.com" in host:
        rendered = _render_with_playwright(url, ua=base_headers.get("User-Agent", ""))
        if rendered:
            return rendered
    return body
