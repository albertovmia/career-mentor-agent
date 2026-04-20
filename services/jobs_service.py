import aiohttp
from typing import List, Dict, Optional
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from config import settings
from utils.logger import get_logger
import asyncio

logger = get_logger("jobs_service")

# Rotating queries based on weekday (monday=0)
DEFAULT_QUERIES = [
    "Senior Analytics Engineer",          # Monday
    "Head of Digital Analytics",          # Tuesday
    "Marketing Data Scientist",           # Wednesday
    "Data Analyst AI",                    # Thursday
    "Analytics Lead Machine Learning",    # Friday
    "Digital Analytics Manager",          # Saturday
    "Data Analytics AI Consultant",       # Sunday
]

# Remote keywords for post-filtering (case-insensitive)
REMOTE_KEYWORDS = ["remot", "teletrabajo", "híbrid", "hybrid", "desde casa", "work from home"]


def _detect_remote_type(job: dict, source: str) -> str:
    """Detect remote type from job data."""
    description = (job.get("job_description") or job.get("description") or "").lower()

    if source == "remotive":
        return "Remoto"

    # Check explicit remote flag
    if job.get("job_is_remote") or job.get("is_remote"):
        return "Remoto"

    # Check for hybrid keywords
    if "híbrid" in description or "hybrid" in description:
        return "Híbrido"

    # Check for remote keywords
    if "remot" in description or "teletrabajo" in description:
        return "Remoto"

    # Check if city is present but no remote indicators
    city = job.get("job_city") or job.get("city") or ""
    if city and not any(kw in description for kw in REMOTE_KEYWORDS):
        if job.get("job_is_hybrid"):
            return "Híbrido"
        return "Presencial"

    return "No especificado"


def _format_salary(salary_min: Optional[float], salary_max: Optional[float], source: str) -> str:
    """Format salary based on source."""
    if not salary_min and not salary_max:
        return "No especificado"

    if source == "jsearch":
        # JSearch: use k format
        min_k = int(salary_min // 1000) if salary_min else None
        max_k = int(salary_max // 1000) if salary_max else None
        if min_k and max_k:
            return f"{min_k}k€ - {max_k}k€"
        elif min_k:
            return f"desde {min_k}k€"
        elif max_k:
            return f"hasta {max_k}k€"
    else:
        # Adzuna/Remotive: full format
        min_val = int(salary_min) if salary_min else None
        max_val = int(salary_max) if salary_max else None
        if min_val and max_val:
            return f"{min_val:,}€ - {max_val:,}€".replace(",", ".")
        elif min_val:
            return f"desde {min_val:,}€".replace(",", ".")
        elif max_val:
            return f"hasta {max_val:,}€".replace(",", ".")

    return "No especificado"


def _normalize_jsearch_job(job: dict) -> dict:
    """Normalize JSearch job to common schema."""
    return {
        "title": job.get("job_title") or "",
        "company": job.get("employer_name") or "",
        "location": f"{job.get('job_city') or ''}, {job.get('job_country') or ''}".strip(", "),
        "salary": _format_salary(
            job.get("job_min_salary"),
            job.get("job_max_salary"),
            "jsearch"
        ),
        "remote_type": _detect_remote_type(job, "jsearch"),
        "url": job.get("job_apply_link") or "",
        "date_posted": job.get("job_posted_at_datetime_utc") or "",
        "source": "JSearch",
        "_raw": job  # Keep raw data for post-filtering
    }


def _normalize_adzuna_job(job: dict) -> dict:
    """Normalize Adzuna job to common schema."""
    location = job.get("location", {})
    location_str = location.get("display_name", "") if isinstance(location, dict) else ""

    return {
        "title": job.get("title") or "",
        "company": job.get("company", {}).get("display_name", "") if isinstance(job.get("company"), dict) else str(job.get("company", "")),
        "location": location_str,
        "salary": _format_salary(
            job.get("salary_min"),
            job.get("salary_max"),
            "adzuna"
        ),
        "remote_type": _detect_remote_type(job, "adzuna"),
        "url": job.get("redirect_url") or "",
        "date_posted": job.get("created") or "",
        "source": "Adzuna",
        "_raw": job
    }


def _normalize_remotive_job(job: dict) -> dict:
    """Normalize Remotive job to common schema."""
    return {
        "title": job.get("title") or "",
        "company": job.get("company_name") or "",
        "location": job.get("candidate_required_location") or "",
        "salary": job.get("salary") or "No especificado",
        "remote_type": "Remoto",  # Remotive is 100% remote
        "url": job.get("url") or "",
        "date_posted": job.get("publication_date") or "",
        "source": "Remotive",
        "_raw": job
    }


def _passes_default_filters(job: dict) -> bool:
    """Check if job passes default filters for scheduled briefing.

    Keep result if ANY of these is true:
    - job_city is None or empty string
    - job_city.lower() contains "madrid"
    - job_is_remote == True
    - job_description.lower() contains remote keywords
    """
    raw = job.get("_raw", job)

    # For JSearch
    if job.get("source") == "JSearch":
        city = (raw.get("job_city") or "").lower()
        description = (raw.get("job_description") or "").lower()

        # Empty city = no location restriction
        if not city:
            return True

        # Madrid in city
        if "madrid" in city:
            return True

        # Remote flag
        if raw.get("job_is_remote"):
            return True

        # Remote keywords in description
        if any(kw in description for kw in REMOTE_KEYWORDS):
            return True

        return False

    # For Adzuna (default mode only)
    if job.get("source") == "Adzuna":
        location = raw.get("location", {})
        location_display = (location.get("display_name", "") or "").lower() if isinstance(location, dict) else ""
        description = (raw.get("description") or "").lower()
        area = location.get("area", []) if isinstance(location, dict) else []

        # Madrid in display name
        if "madrid" in location_display:
            return True

        # Remote keywords
        if any(kw in description for kw in REMOTE_KEYWORDS):
            return True

        # Madrid in area list
        if isinstance(area, list) and any("madrid" in str(a).lower() for a in area):
            return True

        return False

    # For Remotive - already filtered by location in _search_remotive
    return True


def _dedup_key(job: dict) -> tuple:
    """Generate deduplication key: (title[:40], company[:30])."""
    title = (job.get("title") or "").lower().strip()[:40]
    company = (job.get("company") or "").lower().strip()[:30]
    return (title, company)


async def _search_jsearch(query: str) -> List[dict]:
    """Search JSearch API with fixed query params."""
    if not settings.rapidapi_key:
        logger.warning("JSearch no configurado: RAPIDAPI_KEY vacío")
        return []

    headers = {
        "X-RapidAPI-Key": settings.rapidapi_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
    }

    params = {
        "query": query,
        "page": "1",
        "num_pages": "2",
        "country_code": "es",  # Spain
        "date_posted": "3days",
        "employment_types": "FULLTIME"
    }

    all_jobs = []

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://jsearch.p.rapidapi.com/search",
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    jobs = data.get("data", [])
                    logger.info(f"JSearch '{query}': {len(jobs)} ofertas")

                    for job in jobs:
                        if job.get("job_title") and job.get("job_apply_link"):
                            all_jobs.append(_normalize_jsearch_job(job))
                else:
                    logger.warning(f"JSearch error: {response.status}")
    except Exception as e:
        logger.error(f"Error JSearch '{query}': {e}")

    return all_jobs


async def _search_adzuna(query: str, location: str = None, salary_min: int = None) -> List[dict]:
    """Search Adzuna API.

    Args:
        query: Search query (job title/keywords)
        location: Optional location filter (custom search only)
        salary_min: Optional minimum salary filter

    For default scheduled calls: no location param, national scope with post-filtering.
    For custom calls: use location and salary_min if provided.
    """
    if not settings.adzuna_app_id or not settings.adzuna_app_key:
        logger.warning("Adzuna no configurado: ADZUNA_APP_ID o ADZUNA_APP_KEY vacíos")
        return []

    params = {
        "app_id": settings.adzuna_app_id,
        "app_key": settings.adzuna_app_key,
        "what": query,
        "results_per_page": 10,
        "sort_by": "date",
        "content-type": "application/json"
    }

    # Default scheduled mode: salary_min = 40000, no location
    if salary_min is None:
        params["salary_min"] = 40000

    # Custom mode: add location and custom salary
    if location:
        params["where"] = location
    if salary_min is not None:
        params["salary_min"] = salary_min

    all_jobs = []

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.adzuna.com/v1/api/jobs/es/search/1",
                params=params,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    jobs = data.get("results", [])
                    logger.info(f"Adzuna '{query}': {len(jobs)} ofertas")

                    for job in jobs:
                        if job.get("title") and job.get("redirect_url"):
                            all_jobs.append(_normalize_adzuna_job(job))
                else:
                    logger.warning(f"Adzuna error: {response.status}")
    except Exception as e:
        logger.error(f"Error Adzuna '{query}': {e}")

    return all_jobs


async def _search_remotive(query: str, location_hint: str = None) -> List[dict]:
    """Search Remotive API (no auth required).

    Args:
        query: Search query
        location_hint: Optional location hint for additional filtering

    Remotive jobs are 100% remote by definition.
    Post-filter for candidate_required_location containing:
    worldwide, europe, spain, españa, emea, or empty string
    """
    params = {
        "search": query,
        "limit": 15
    }

    # Allowed locations (case-insensitive)
    allowed_locations = ["worldwide", "europe", "spain", "españa", "emea", ""]

    all_jobs = []

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://remotive.com/api/remote-jobs",
                params=params,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    jobs = data.get("jobs", [])
                    logger.info(f"Remotive '{query}': {len(jobs)} ofertas")

                    for job in jobs:
                        if not job.get("title") or not job.get("url"):
                            continue

                        # Filter by location
                        location = (job.get("candidate_required_location") or "").lower()

                        # Include if location matches allowed list or location_hint
                        location_ok = any(loc in location for loc in allowed_locations)
                        if location_hint:
                            location_ok = location_ok or location_hint.lower() in location

                        if location_ok:
                            all_jobs.append(_normalize_remotive_job(job))
                else:
                    logger.warning(f"Remotive error: {response.status}")
    except Exception as e:
        logger.error(f"Error Remotive '{query}': {e}")

    return all_jobs


async def search_jobs(query: str = None) -> dict:
    """Search jobs from all sources for scheduled briefing.

    Uses rotating queries based on weekday if no query provided.
    Returns top 8 results after deduplication and sorting.
    """
    # Use rotating query if none provided
    if query is None:
        query = DEFAULT_QUERIES[datetime.now(ZoneInfo("Europe/Madrid")).weekday()]

    # Fetch from all sources in parallel
    results_raw = await asyncio.gather(
        _search_jsearch(query),
        _search_adzuna(query),
        _search_remotive(query),
        return_exceptions=True
    )

    # Flatten and filter exceptions
    all_jobs = []
    for result in results_raw:
        if isinstance(result, Exception):
            logger.error(f"Error en fuente: {result}")
        elif isinstance(result, list):
            all_jobs.extend(result)

    # Apply default post-filters (only for scheduled mode)
    filtered_jobs = [job for job in all_jobs if _passes_default_filters(job)]

    # Deduplicate
    seen = set()
    unique_jobs = []
    for job in filtered_jobs:
        key = _dedup_key(job)
        if key not in seen:
            seen.add(key)
            unique_jobs.append(job)

    # Sort by date_posted descending
    unique_jobs.sort(key=lambda x: x.get("date_posted") or "", reverse=True)

    # Return top 8
    top_jobs = unique_jobs[:8]

    if not top_jobs:
        return {
            "jobs": [],
            "message": "No se encontraron ofertas hoy.",
            "total": 0,
            "sources_used": []
        }

    sources_used = list(set(job["source"] for job in top_jobs))

    return {
        "jobs": top_jobs,
        "total": len(unique_jobs),
        "sources_used": sources_used,
        "formatted": _format_jobs(top_jobs)
    }


async def search_jobs_custom(
    query: str,
    location: str = None,
    salary_min: int = None,
    remote_only: bool = False,
    sources: List[str] = None
) -> dict:
    """Custom job search with user-specified parameters.

    Args:
        query: Job title or keywords (required)
        location: City or region (optional)
        salary_min: Minimum annual salary in EUR (optional)
        remote_only: If True, keep only remote/hybrid jobs
        sources: List of sources to query ["jsearch", "adzuna", "remotive"]
                 Default: all three

    Returns top 10 results without default post-filters.
    """
    if sources is None:
        sources = ["jsearch", "adzuna", "remotive"]

    # Build search tasks based on selected sources
    tasks = []
    source_names = []

    if "jsearch" in sources:
        tasks.append(_search_jsearch(query))
        source_names.append("JSearch")

    if "adzuna" in sources:
        # For custom search, pass location and salary_min
        tasks.append(_search_adzuna(query, location=location, salary_min=salary_min))
        source_names.append("Adzuna")

    if "remotive" in sources:
        tasks.append(_search_remotive(query, location_hint=location))
        source_names.append("Remotive")

    # Execute all searches in parallel
    results_raw = await asyncio.gather(*tasks, return_exceptions=True)

    # Flatten and filter exceptions
    all_jobs = []
    for result in results_raw:
        if isinstance(result, Exception):
            logger.error(f"Error en fuente: {result}")
        elif isinstance(result, list):
            all_jobs.extend(result)

    # Apply custom filters (NOT default post-filters)
    filtered_jobs = all_jobs

    # Remote-only filter
    if remote_only:
        filtered_jobs = [
            job for job in filtered_jobs
            if job.get("remote_type") in ["Remoto", "Híbrido"]
        ]

    # Salary filter (keep if salary_min >= requested OR salary not specified)
    if salary_min:
        def passes_salary(job: dict) -> bool:
            salary_str = job.get("salary", "")
            if "No especificado" in salary_str:
                return True
            # Extract first number from salary string
            import re
            numbers = re.findall(r'(\d+)', salary_str.replace(".", ""))
            if numbers:
                first_num = int(numbers[0])
                return first_num >= salary_min
            return True

        filtered_jobs = [job for job in filtered_jobs if passes_salary(job)]

    # Deduplicate
    seen = set()
    unique_jobs = []
    for job in filtered_jobs:
        key = _dedup_key(job)
        if key not in seen:
            seen.add(key)
            unique_jobs.append(job)

    # Sort by date_posted descending
    unique_jobs.sort(key=lambda x: x.get("date_posted") or "", reverse=True)

    # Return top 10
    top_jobs = unique_jobs[:10]

    if not top_jobs:
        return {
            "jobs": [],
            "message": f"No se encontraron ofertas para '{query}' con los filtros especificados.",
            "total": 0,
            "sources_used": []
        }

    sources_used = list(set(job["source"] for job in top_jobs))

    return {
        "jobs": top_jobs,
        "total": len(unique_jobs),
        "sources_used": sources_used,
        "formatted": _format_jobs(top_jobs)
    }


def _format_jobs(jobs: List[Dict]) -> str:
    """Format jobs for display."""
    if not jobs:
        return (
            "No encontré ofertas con los criterios especificados. "
            "Prueba con otros términos o ajusta los filtros."
        )

    response = f"🎯 {len(jobs)} ofertas encontradas:\n\n"
    for i, job in enumerate(jobs, 1):
        remote_icon = "🌍" if job.get("remote_type") == "Remoto" else "📍"
        remote_str = job.get("remote_type", "N/A")
        location = job.get("location", "N/A")

        response += f"{i}. {job['title']}\n"
        response += f"   🏢 {job.get('company', 'N/A')}\n"
        response += f"   {remote_icon} {remote_str}"
        if location and location != ",":
            response += f" — {location}"
        response += "\n"

        salary = job.get("salary")
        if salary and "No especificado" not in salary:
            response += f"   💰 {salary}\n"

        url = job.get("url", "")
        if url:
            response += f"   🔗 {url[:80]}\n"

        source = job.get("source", "")
        if source:
            response += f"   📎 Fuente: {source}\n"

        response += "\n"

    return response