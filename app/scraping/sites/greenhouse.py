from __future__ import annotations
import json
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse, parse_qs

import requests
from tldextract import extract as tldextract_extract

from ...config import get_settings


def _candidate_board_tokens(hostname: str) -> List[str]:
    ext = tldextract_extract(hostname)
    domain = ext.domain or ""
    candidates = []
    if domain:
        candidates.append(domain)
        # Heuristic: many companies use "with<name>" domains but the GH board token is the company name
        if domain.startswith("with") and len(domain) > 4:
            candidates.append(domain[4:])
    # Deduplicate preserving order
    seen = set()
    uniq: List[str] = []
    for t in candidates:
        if t and t not in seen:
            uniq.append(t)
            seen.add(t)
    return uniq


def _fetch_greenhouse_job(job_id: str, board_token: str) -> Optional[Dict[str, Any]]:
    settings = get_settings()
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}"
    headers = {"User-Agent": settings.USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=settings.REQUEST_TIMEOUT_SECONDS)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not isinstance(data, dict) or "title" not in data:
            return None
        return data
    except Exception:
        return None


def _pretty_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    # Replace common separators and title-case
    t = token.replace("-", " ").replace("_", " ").strip()
    return t.title() if t else None


def parse_greenhouse_from_url(url: str) -> Optional[Dict[str, Any]]:
    """If URL references a Greenhouse-hosted job (via gh_jid), return parsed fields.

    Returns a dict with minimally: title, employer
    """
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    job_ids = qs.get("gh_jid") or qs.get("gh_src")
    job_id_qs = job_ids[0] if job_ids else None

    # 1) Direct Greenhouse URL with path token/id, e.g. /{token}/jobs/{id}
    token_path: Optional[str] = None
    job_id_path: Optional[str] = None
    try:
        host = (parsed.hostname or "").lower()
        if "greenhouse.io" in host:
            parts = [p for p in (parsed.path or "/").strip("/").split("/") if p]
            # Pattern: /{token}/jobs/{id}[/*]
            if len(parts) >= 3 and parts[1] == "jobs" and parts[2].isdigit():
                token_path = parts[0]
                job_id_path = parts[2]
    except Exception:
        pass

    if token_path and job_id_path:
        gh = _fetch_greenhouse_job(job_id_path, token_path)
        if gh:
            title = gh.get("title")
            employer = gh.get("company_name") or _pretty_token(token_path)
            return {
                "title": (title[:300] if isinstance(title, str) else title),
                "employer": (employer[:300] if isinstance(employer, str) else employer),
            }

    # 2) Fallback: gh_jid in query with heuristic tokens from hostname
    if not job_id_qs:
        return None

    tokens = _candidate_board_tokens(parsed.hostname or "")
    for token in tokens:
        gh = _fetch_greenhouse_job(job_id_qs, token)
        if gh:
            title = gh.get("title")
            employer = gh.get("company_name") or _pretty_token(token)
            return {
                "title": (title[:300] if isinstance(title, str) else title),
                "employer": (employer[:300] if isinstance(employer, str) else employer),
            }
    return None
