from __future__ import annotations
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup
import re


def _clean(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    s = text.strip()
    if not s:
        return None
    # Cap to 300 to align with common limits elsewhere
    return s[:300]


essential_title_keys = [
    "OpportunityTitle",
    "JobTitle",
    "PositionTitle",
    "positionTitle",
    "jobTitle",
    "formattedTitle",
    "FormattedTitle",
    "title",
]


def _is_generic_title(val: str) -> bool:
    low = val.lower()
    if (
        "opportunity detail" in low
        or low in {"ukg pro", "job details", "opportunity", "job"}
        or "unsupported browser" in low
    ):
        return True
    return False


def parse_ultipro_from_html(html: str, url: str) -> Dict[str, Any]:
    """Best-effort extraction for UKG/UltiPro JobBoard pages.

    These pages are often JS-rendered. We attempt to pull a title/employer from:
    - OpenGraph/Twitter meta tags
    - Visible headings (h1/h2)
    - JSON embedded in <script> tags using common key names
    """
    soup = BeautifulSoup(html, "lxml")

    title: Optional[str] = None
    employer: Optional[str] = None

    # 1) OG/Twitter title
    for sel, attr in (("meta[property='og:title']", "content"), ("meta[name='twitter:title']", "content")):
        tag = soup.select_one(sel)
        if tag and tag.get(attr):
            cand = _clean(tag.get(attr))
            if cand and not _is_generic_title(cand):
                title = cand
                break

    # 2) Visible headings
    if not title:
        for tag in soup.find_all(["h1", "h2"]):
            cand = _clean(tag.get_text(" ", strip=True))
            if cand and not _is_generic_title(cand):
                title = cand
                break

    # 2b) Knockout/UltiPro specific markers
    if not title:
        el = soup.select_one("[data-automation='opportunity-title']")
        if el:
            cand = _clean(el.get_text(" ", strip=True))
            if cand and not _is_generic_title(cand):
                title = cand
        if not title:
            el2 = soup.find(attrs={"data-bind": re.compile(r"\\bformattedTitle\\b")})
            if el2:
                cand = _clean(el2.get_text(" ", strip=True))
                if cand and not _is_generic_title(cand):
                    title = cand

    # 2c) Raw HTML regex fallback for brittle pages
    if not title:
        # Try to capture text content between the tag and its closing counterpart.
        # Handles cases like: <span data-automation="opportunity-title">Software Engineer I</span>
        m = re.search(
            r"<[^>]*data-automation=\"opportunity-title\"[^>]*>(.*?)</[^>]+>",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if m:
            cand = _clean(re.sub(r"<[^>]+>", " ", m.group(1)))
            if cand and not _is_generic_title(cand):
                title = cand
    if not title:
        m2 = re.search(
            r"<[^>]*data-bind=\"[^\"]*formattedTitle[^\"]*\"[^>]*>(.*?)</[^>]+>",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if m2:
            cand = _clean(re.sub(r"<[^>]+>", " ", m2.group(1)))
            if cand and not _is_generic_title(cand):
                title = cand

    # 3) Script-embedded JSON-ish content
    if not title:
        # Look for common keys in JSON blobs
        patterns = [
            re.compile(r"\b(?:" + "|".join(map(re.escape, essential_title_keys)) + r")\b\s*[:=]\s*\"([^\"]{3,200})\""),
            re.compile(r"\b(?:" + "|".join(map(re.escape, essential_title_keys)) + r")\b\s*[:=]\s*'([^']{3,200})'"),
        ]
        for script in soup.find_all("script"):
            text = script.string or script.get_text("", strip=True)
            if not text:
                continue
            for pat in patterns:
                for m in pat.finditer(text):
                    cand = _clean(m.group(1))
                    if cand and not _is_generic_title(cand):
                        title = cand
                        break
                if title:
                    break
            if title:
                break

    # Employer from OG site name or JSON-ish hints
    site_name = soup.find("meta", property="og:site_name")
    if site_name and site_name.get("content"):
        employer = _clean(site_name.get("content"))

    if not employer:
        for script in soup.find_all("script"):
            text = script.string or script.get_text("", strip=True)
            if not text:
                continue
            # Look for CompanyName/hiringOrganization structures
            m = re.search(
                r'"(?:CompanyName|companyName)"\s*:\s*"([^\"]{2,200})"', text
            )
            if m:
                cand = _clean(m.group(1))
                if cand and "ultipro" not in cand.lower():
                    employer = cand
                    break
            m2 = re.search(
                r'"hiringOrganization"\s*:\s*\{[^\{\}]*?"name"\s*:\s*"([^\"]{2,200})"',
                text,
            )
            if m2:
                cand = _clean(m2.group(1))
                if cand and "ultipro" not in cand.lower():
                    employer = cand
                    break

    return {"title": title, "employer": employer}
