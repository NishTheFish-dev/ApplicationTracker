from __future__ import annotations
import json
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup
from tldextract import extract as tldextract_extract
from .sites.greenhouse import parse_greenhouse_from_url


def _extract_source_site(url: str) -> str:
    ext = tldextract_extract(url)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}"
    return url


def parse_job_from_html(html: str, url: str) -> dict:
    """Extract job fields.

    Strategy:
    1) Greenhouse API when the URL includes a gh_jid (e.g., Waymo careers).
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

    # 3) Heuristic fallback
    title = None
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)[:300]
    if not title:
        ogt = soup.find("meta", property="og:title")
        if ogt and ogt.get("content"):
            title = ogt["content"][:300]

    employer = None
    site_name = soup.find("meta", property="og:site_name")
    if site_name and site_name.get("content"):
        employer = site_name["content"][:300]

    return {
        "title": title,
        "employer": employer,
        "date_posted": None,
        "location": None,
        "source_site": _extract_source_site(url),
    }
