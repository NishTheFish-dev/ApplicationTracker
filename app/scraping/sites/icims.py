from __future__ import annotations
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup
from tldextract import extract as tldextract_extract
from urllib.parse import urlparse
import re


def _clean(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    s = text.strip()
    if not s:
        return None
    return s[:300]


def _is_generic_title(val: str) -> bool:
    low = val.lower()
    return (
        not val
        or low in {"portal", "job", "jobs", "careers", "career portal", "job search - jobs"}
        or "unsupported browser" in low
        or "job search" in low and "jobs" in low
    )


def _title_from_selectors(soup: BeautifulSoup) -> Optional[str]:
    # Common iCIMS structures
    selectors = [
        "div.iCIMS_Header h1",
        "section.iCIMS_Header h1",
        "div.iCIMS_JobHeader h1",
        "h1.iCIMS_JobTitle",
        "div.iCIMS_JobTitle",
        "#iCIMS_JobHeader h1",
        "#iCIMS_Content h1",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            cand = _clean(el.get_text(" ", strip=True))
            if cand and not _is_generic_title(cand):
                return cand

    # Any h1 with an iCIMS-* parent container
    for h1 in soup.find_all("h1"):
        cand = _clean(h1.get_text(" ", strip=True))
        if not cand or _is_generic_title(cand):
            continue
        parent = h1
        depth = 0
        while parent and depth < 3:
            classes = " ".join(parent.get("class") or [])
            pid = parent.get("id") or ""
            if re.search(r"\biCIMS_", classes) or re.search(r"\biCIMS_", pid):
                return cand
            parent = parent.parent
            depth += 1
    return None


def _title_from_ld_json(soup: BeautifulSoup) -> Optional[str]:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            import json
            data = json.loads(script.string or script.get_text("", strip=True))
        except Exception:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if isinstance(node, dict):
                typ = node.get("@type")
                if (isinstance(typ, list) and "JobPosting" in typ) or typ == "JobPosting":
                    title = node.get("title") or node.get("name")
                    if isinstance(title, str):
                        cand = _clean(title)
                        if cand and not _is_generic_title(cand):
                            return cand
    return None


def _title_from_url_slug(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        parts = [p for p in (parsed.path or "/").strip("/").split("/") if p]
        # Typical iCIMS pattern: /jobs/<id>/<slug>/job
        candidates = []
        for p in parts:
            if p.lower() in {"jobs", "job", "careers", "opportunitydetail"}:
                continue
            if re.fullmatch(r"\d{3,}", p):
                continue
            if re.fullmatch(r"[0-9a-fA-F\-]{12,}", p):
                continue
            candidates.append(p)
        seg: Optional[str] = None
        # Prefer segments that look like slugs with dashes/underscores
        for s in reversed(candidates):
            if "-" in s or "_" in s:
                seg = s
                break
        if seg is None and candidates:
            seg = candidates[-1]
        if seg:
            raw = seg.replace("-", " ").replace("_", " ").strip()
            if raw:
                return raw.title()[:300]
    except Exception:
        return None
    return None


def _employer_from_meta_or_ld(soup: BeautifulSoup) -> Optional[str]:
    site_name = soup.find("meta", property="og:site_name")
    if site_name and site_name.get("content"):
        cand = _clean(site_name.get("content"))
        if cand and "icims" not in cand.lower():
            # Remove common noise like "Careers", "Jobs at", etc.
            s = re.sub(r"\b(careers?|jobs?|job\s*board|recruiting|hiring)\b", "", cand, flags=re.IGNORECASE)
            s = re.sub(r"\b(at|with|by)\b", "", s, flags=re.IGNORECASE)
            s = re.sub(r"[|•·]+", " ", s)
            s = " ".join(s.split())
            if s:
                return s[:300]
    # JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            import json
            data = json.loads(script.string or script.get_text("", strip=True))
        except Exception:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if isinstance(node, dict):
                org = node.get("hiringOrganization")
                if isinstance(org, dict):
                    name = org.get("name")
                    cand = _clean(name)
                    if cand and "icims" not in cand.lower():
                        return cand
    return None


def _employer_from_host(url: str) -> Optional[str]:
    try:
        ext = tldextract_extract(url)
        sub = (ext.subdomain or "").lower()
        # e.g., careers-americas.icims.com, fieldhourly-thefreshmarket.icims.com
        toks = [t for t in re.split(r"[^a-z0-9]+", sub) if t]
        noise = {"careers", "career", "jobs", "job", "portal", "prod", "hrjobs", "internal", "external", "icims"}
        toks = [t for t in toks if t not in noise]
        if not toks:
            return None
        # Heuristic: prefer the last token (company token often appears at the end)
        token = toks[-1]
        return token.title()[:300]
    except Exception:
        return None


def parse_icims_from_html(html: str, url: str) -> Dict[str, Any]:
    """Best-effort extraction for iCIMS-hosted job pages.

    Strategy:
    - Use iCIMS-specific DOM selectors for the visible job title.
    - Fallback to JSON-LD JobPosting title if present.
    - As a last resort, derive from the URL slug.
    Employer is read from OG site_name or JSON-LD hiringOrganization name; fallback to subdomain heuristic.
    """
    soup = BeautifulSoup(html, "lxml")

    title: Optional[str] = None
    employer: Optional[str] = None

    # Title extraction
    title = _title_from_selectors(soup)
    if not title:
        title = _title_from_ld_json(soup)
    if not title:
        title = _title_from_url_slug(url)

    # Employer extraction
    employer = _employer_from_meta_or_ld(soup)
    if not employer:
        employer = _employer_from_host(url)

    return {"title": title, "employer": employer}
