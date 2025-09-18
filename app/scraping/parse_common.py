from __future__ import annotations
import json
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup
from tldextract import extract as tldextract_extract
from .sites.greenhouse import parse_greenhouse_from_url
from .sites.ultipro import parse_ultipro_from_html
from urllib.parse import urlparse
import re
import requests
from ..config import get_settings


def _extract_source_site(url: str) -> str:
    ext = tldextract_extract(url)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}"
    return url


def parse_job_from_html(html: str, url: str) -> dict:
    """Extract job fields.

    Strategy:
    1) Greenhouse API when the URL includes a gh_jid
    2) schema.org JSON-LD JobPosting in the HTML.
    3) Heuristic fallback from HTML tags.

    Returns a dict with at least: title, employer.
    """
    # 1) Greenhouse JSON API, if applicable
    gh = parse_greenhouse_from_url(url)
    if gh and (gh.get("title") or gh.get("employer")):
        return {
            "title": gh.get("title"),
            "employer": gh.get("employer"),
            "date_posted": None,
            "location": None,
            "source_site": _extract_source_site(url),
        }
    soup = BeautifulSoup(html, "lxml")
    employer_hint: Optional[str] = None

    # 2) JSON-LD JobPosting
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            json_text = script.string or script.get_text("", strip=True)
            data = json.loads(json_text)
        except Exception:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            typ = node.get("@type")
            if isinstance(typ, list):
                if "JobPosting" not in typ:
                    continue
            elif typ != "JobPosting":
                continue

            title = node.get("title") or node.get("name")
            employer = None
            org = node.get("hiringOrganization")
            if isinstance(org, dict):
                employer = org.get("name")
            date_posted = node.get("datePosted")
            location = None
            job_location = node.get("jobLocation")
            if isinstance(job_location, dict):
                addr = job_location.get("address")
                if isinstance(addr, dict):
                    location = (
                        addr.get("addressLocality")
                        or addr.get("addressRegion")
                        or addr.get("addressCountry")
                    )
            return {
                "title": (title[:300] if isinstance(title, str) else title),
                "employer": (employer[:300] if isinstance(employer, str) else employer),
                "date_posted": date_posted,
                "location": (location[:255] if isinstance(location, str) else location),
                "source_site": _extract_source_site(url),
            }

    # 2b) UltiPro/UKG Pro JobBoard pages often render via JS; try site-specific extraction
    try:
        ext = tldextract_extract(url)
        if ext.domain == "ultipro":
            up = parse_ultipro_from_html(html, url)
            if up.get("title"):
                return {
                    "title": up.get("title"),
                    "employer": up.get("employer"),
                    "date_posted": None,
                    "location": None,
                    "source_site": _extract_source_site(url),
                }
            if up.get("employer"):
                employer_hint = up.get("employer")

            # Forced reader-proxy refetch if title missing
            settings = get_settings()
            proxy_base = (settings.FETCH_PROXY_READER or "").strip() or "https://r.jina.ai"
            try:
                proxy_url = proxy_base.rstrip("/") + "/" + url
                resp_reader = requests.get(
                    proxy_url,
                    headers={"User-Agent": settings.USER_AGENT},
                    timeout=settings.REQUEST_TIMEOUT_SECONDS,
                    allow_redirects=True,
                )
                if resp_reader.ok and resp_reader.text:
                    up2 = parse_ultipro_from_html(resp_reader.text, url)
                    if up2.get("title"):
                        return {
                            "title": up2.get("title"),
                            "employer": up2.get("employer") or employer_hint,
                            "date_posted": None,
                            "location": None,
                            "source_site": _extract_source_site(url),
                        }
                    if up2.get("employer") and not employer_hint:
                        employer_hint = up2.get("employer")
            except Exception:
                pass
    except Exception:
        # Non-fatal: fall back to heuristics
        pass

    # 3) Heuristic fallback
    title = None
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)[:300]
    if not title:
        ogt = soup.find("meta", property="og:title")
        if ogt and ogt.get("content"):
            title = ogt["content"][:300]

    # 3a) Fallback to <title> tag if still missing
    if not title and soup.title and soup.title.string:
        full_title = (soup.title.get_text(strip=True) or "")[:300]
        # Try to split common patterns like "Job Title - Company" or "Job Title | Company"
        for sep in [" | ", " - ", " – ", " — "]:
            if sep in full_title:
                candidate = full_title.split(sep)[0].strip()
                if candidate:
                    title = candidate[:300]
                    break
        if not title and full_title:
            title = full_title

    employer = None
    site_name = soup.find("meta", property="og:site_name")
    if site_name and site_name.get("content"):
        employer = site_name["content"][:300]

    # 3b) If employer still missing, infer from hostname (e.g., careers.caterpillar.com -> Caterpillar)
    if not employer:
        ext = tldextract_extract(url)
        if ext.domain:
            employer = ext.domain.title()[:300]

    # 3b-2) Apply UltiPro employer hint if one was found earlier
    if not employer and employer_hint:
        employer = employer_hint[:300]

    # 3c) If title still missing (e.g., proxy-reader text), derive from URL slug
    if not title:
        parsed = urlparse(url)
        parts = [p for p in (parsed.path or "/").strip("/").split("/") if p]
        # Remove common non-title segments
        skip = {
            "jobs",
            "job",
            "jobboard",
            "opportunitydetail",
            "careers",
            "en",
            "en-us",
            "en_us",
            "en-US",
            "en_US",
        }
        def _is_id_segment(seg: str) -> bool:
            return bool(re.fullmatch(r"[rR]?\d{4,}", seg))
        def _is_guid_like(seg: str) -> bool:
            # UUID pattern or long hex-with-dashes tokens
            if re.fullmatch(r"[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", seg):
                return True
            compact = re.sub(r"[-_]", "", seg)
            return len(compact) >= 16 and re.fullmatch(r"[0-9a-fA-F]+", compact) is not None
        def _is_upper_alnum_token(seg: str) -> bool:
            # Ignore tenant-ish tokens like VER1018VALLC: upper alnum, fairly long, letters+digits
            s = re.sub(r"[^A-Za-z0-9]", "", seg)
            if len(s) >= 6 and s.upper() == s:
                has_alpha = re.search(r"[A-Za-z]", s) is not None
                has_digit = re.search(r"[0-9]", s) is not None
                return has_alpha and has_digit
            return False
        candidates = [
            p for p in parts
            if p.lower() not in skip and not _is_id_segment(p) and not _is_guid_like(p) and not _is_upper_alnum_token(p)
        ]
        seg: Optional[str] = None
        for s in reversed(candidates):
            if "-" in s or "_" in s:
                seg = s
                break
        if seg is None and candidates:
            seg = candidates[-1]
        if seg:
            raw = seg.replace("-", " ").replace("_", " ").strip()
            if raw:
                title = raw.title()[:300]

    return {
        "title": title,
        "employer": employer,
        "date_posted": None,
        "location": None,
        "source_site": _extract_source_site(url),
    }
