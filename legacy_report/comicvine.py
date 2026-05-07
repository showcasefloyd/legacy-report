import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional

import httpx

from legacy_report.config import get_api_key, get_config
from legacy_report.db import get_session
from legacy_report.models import ComicVineCache

BASE_URL = "https://comicvine.gamespot.com/api"
_HEADERS = {"User-Agent": "LegacyReport/1.0"}


def _cache_key(endpoint: str, params: dict) -> str:
    raw = endpoint + json.dumps(params, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_cached(key: str) -> Optional[dict]:
    from sqlmodel import select

    for session in get_session():
        cached = session.exec(
            select(ComicVineCache).where(ComicVineCache.cache_key == key)
        ).first()
        if cached is None:
            return None
        config = get_config()
        ttl = timedelta(hours=config.get("cache_ttl_hours", 24))
        if datetime.utcnow() - cached.fetched_at > ttl:
            return None
        return json.loads(cached.response_json)


def _store_cache(key: str, data: dict) -> None:
    from sqlmodel import select

    config = get_config()
    for session in get_session():
        existing = session.exec(
            select(ComicVineCache).where(ComicVineCache.cache_key == key)
        ).first()
        if existing:
            existing.response_json = json.dumps(data)
            existing.fetched_at = datetime.utcnow()
            session.add(existing)
        else:
            entry = ComicVineCache(
                cache_key=key,
                response_json=json.dumps(data),
                ttl_hours=config.get("cache_ttl_hours", 24),
            )
            session.add(entry)
        session.commit()


def _fetch(endpoint: str, params: dict) -> dict:
    key = _cache_key(endpoint, params)
    cached = _get_cached(key)
    if cached is not None:
        return cached

    api_key = get_api_key()
    request_params = {**params, "api_key": api_key, "format": "json"}
    url = f"{BASE_URL}/{endpoint}/"

    with httpx.Client(headers=_HEADERS, timeout=15.0) as client:
        response = client.get(url, params=request_params)
        response.raise_for_status()
        data = response.json()

    _store_cache(key, data)
    return data


def search_volumes(query: str) -> list:
    """Search ComicVine for series/volumes by title."""
    data = _fetch(
        "volumes",
        {
            "filter": f"name:{query}",
            "field_list": "id,name,start_year,publisher,description,count_of_issues",
        },
    )
    return data.get("results", [])


def get_issues_for_volume(volume_id: str, offset: int = 0, limit: int = 100) -> dict:
    """Get one page of issues for a given ComicVine volume ID."""
    data = _fetch(
        "issues",
        {
            "filter": f"volume:{volume_id}",
            "field_list": "id,name,issue_number,cover_date,description,person_credits,image",
            "sort": "cover_date:asc",
            "limit": limit,
            "offset": offset,
        },
    )
    return {
        "results": data.get("results", []),
        "total": data.get("number_of_total_results", 0),
        "offset": offset,
        "limit": limit,
    }


def calculate_lgy_number(selected_volume: dict, issue_number: str) -> Optional[str]:
    """Estimate the Legacy (LGY) number for an issue.

    Strategy:
      1. Search ComicVine for all volumes sharing the same title.
      2. Filter to the same publisher.
      3. Sort chronologically by start_year.
      4. Sum count_of_issues for every volume that started *before* the
         selected one; add the current (integer) issue number.

    Returns a string LGY number, or None if it cannot be determined
    (e.g. non-numeric issue number, no related volumes found).
    """
    title: str = selected_volume.get("name", "")
    publisher_name: str = (selected_volume.get("publisher") or {}).get("name", "")
    current_volume_id: str = str(selected_volume["id"])

    try:
        current_issue_int = int(float(issue_number))
    except (ValueError, TypeError):
        return None  # non-numeric issue — can't sum

    all_volumes = search_volumes(title)

    # Keep only volumes from the same publisher with the same title
    related = [
        v for v in all_volumes
        if (v.get("publisher") or {}).get("name", "") == publisher_name
        and v.get("name", "").lower() == title.lower()
    ]

    # Sort oldest-first
    related.sort(key=lambda v: int(v.get("start_year") or 0))

    # Sum issue counts for volumes that came before the selected one
    prior_issues = 0
    for vol in related:
        if str(vol["id"]) == current_volume_id:
            break
        prior_issues += int(vol.get("count_of_issues") or 0)

    return str(prior_issues + current_issue_int)


def validate_api_key(key: str) -> bool:
    """Test an API key with a lightweight call. Returns True if valid."""
    try:
        url = f"{BASE_URL}/types/"
        with httpx.Client(headers=_HEADERS, timeout=10.0) as client:
            response = client.get(url, params={"api_key": key, "format": "json"})
            return response.status_code == 200
    except Exception:
        return False
