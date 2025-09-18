from __future__ import annotations
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup
import re


def _clean(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    s = " ".join(text.split()).strip()
    if not s:
        return None
    return s[:300]


def _bad_employer(val: str) -> bool:
    low = val.strip().lower()
    return low in {"linkedin", "jobs", "job", "hiring"}


def parse_linkedin_from_html(html: str, url: str) -> Dict[str, Any]:
    """Extract title and employer from a LinkedIn job page.

    Strategy:
    1) JSON-LD JobPosting if present
    2) Visible DOM selectors commonly used by LinkedIn job pages
    3) Script blobs (e.g., companyName, hiringOrganization.name)
    """
    soup = BeautifulSoup(html, "lxml")

    title: Optional[str] = None
    employer: Optional[str] = None

    # 1) JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = script.string or script.get_text("", strip=True)
            if not data:
                continue
            # Avoid strict JSON parsing; try simple regexes first
            m = re.search(r'"@type"\s*:\s*"JobPosting"', data)
            if not m:
                continue
            # Extract title and employer
            m_title = re.search(r'"title"\s*:\s*"([^\"]{2,200})"', data)
            if m_title and not title:
                title = _clean(m_title.group(1))
            m_org = re.search(r'"hiringOrganization"\s*:\s*\{[^\{\}]*?"name"\s*:\s*"([^\"]{2,200})"', data)
            if m_org and not employer:
                employer = _clean(m_org.group(1))
        except Exception:
            continue
        if title and employer:
            break

    # 2) Visible DOM selectors (current and legacy UIs)
    if not employer:
        sels = [
            ".jobs-unified-top-card__company-name a",
            "a.topcard__org-name-link",
            ".topcard__org-name-link",
            ".topcard__flavor--black-link",
            "a[data-control-name='jobdetails_topcard_company_url']",
            "a[data-tracking-control-name*='topcard-org-name']",
            "a[href*='/company/'][data-tracking-control-name]",
            "a[href*='/company/'][data-control-name]",
        ]
        for sel in sels:
            el = soup.select_one(sel)
            if el:
                cand = _clean(el.get_text(" ", strip=True))
                if cand and not _bad_employer(cand):
                    employer = cand
                    break
    if not title:
        sels_t = [
            "h1.jobs-unified-top-card__job-title",
            "h1.top-card-layout__title",
            "h1.t-24",
            "h1",
        ]
        for sel in sels_t:
            el = soup.select_one(sel)
            if el:
                cand = _clean(el.get_text(" ", strip=True))
                if cand:
                    title = cand
                    break

    # 3) Script blobs
    if not employer:
        patterns = [
            re.compile(r'"companyName"\s*:\s*"([^\"]{2,200})"'),
            re.compile(r'"companyNameLocalized"\s*:\s*"([^\"]{2,200})"'),
            re.compile(r'"hiringOrganization"\s*:\s*\{[^\{\}]*?"name"\s*:\s*"([^\"]{2,200})"'),
        ]
        for script in soup.find_all("script"):
            text = script.string or script.get_text("", strip=True)
            if not text:
                continue
            for pat in patterns:
                m = pat.search(text)
                if m:
                    cand = _clean(m.group(1))
                    if cand and not _bad_employer(cand):
                        employer = cand
                        break
            if employer:
                break

    # De-emphasize LinkedIn as employer if it's just the host brand
    if employer and _bad_employer(employer):
        employer = None

    return {"title": title, "employer": employer}
