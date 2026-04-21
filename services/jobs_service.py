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


# ---------------------------------------------------------------------------
# Fix 1 helper: truncate strings to avoid bloating LLM context
# ---------------------------------------------------------------------------
def _truncate(s: str, max_len: int) -> str:
    if not s:
        return ""
    return s[:max_len] + "…" if len(s) > max_len else s


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


# ---------------------------------------------------------------------------
# Fix 1: Normalize to lean schema — NO description, NO _raw
# ---------------------------------------------------------------------------
def _normalize_jsearch_job(job: dict) -> dict:
    """Normalize JSearch job to lean common schema."""
    return {
        "title": _truncate(job.get("job_title") or "", 60),
        "company": _truncate(job.get("employer_name") or "", 40),
        "location": _truncate(
            f"{job.get('job_city') or ''}, {job.get('job_country') or ''}".strip(", "),
            30
        ),
        "salary": _truncate(_format_salary(
            job.get("job_min_salary"),
            job.get("job_max_salary"),
            "jsearch"
        ), 25),
        "remote_type": _detect_remote_type(job, "jsearch"),
        "url": job.get("job_apply_link") or "",
        "date_posted": job.get("job_posted_at_datetime_utc") or "",
        "source": "JSearch",
        # store only what _passes_default_filters needs (no full description)
        "_city": (job.get("job_city") or "").lower(),
        "_is_remote": bool(job.get("job_is_remote")),
        "_description_snippet": (job.get("job_description") or "")[:200].lower(),
    }


def _normalize_adzuna_job(job: dict) -> dict:
    """Normalize Adzuna job to lean common schema."""
    location = job.get("location", {})
    location_str = location.get("display_name", "") if isinstance(location, dict) else ""
    area = location.get("area", []) if isinstance(location, dict) else []

    return {
        "title": _truncate(job.get("title") or "", 60),
        "company": _truncate(
            job.get("company", {}).get("display_name", "") if isinstance(job.get("company"), dict) else str(job.get("company", "")),
            40
        ),
        "location": _truncate(location_str, 30),
        "salary": _truncate(_format_salary(
            job.get("salary_min"),
            job.get("salary_max"),
            "adzuna"
        ), 25),
        "remote_type": _detect_remote_type(job, "adzuna"),
        "url": job.get("redirect_url") or "",
        "date_posted": job.get("created") or "",
        "source": "Adzuna",
        # filtering helpers
        "_location_display": location_str.lower(),
        "_area": [str(a).lower() for a in area] if isinstance(area, list) else [],
        "_description_snippet": (job.get("description") or "")[:200].lower(),
    }


def _normalize_remotive_job(job: dict) -> dict:
    """Normalize Remotive job to lean common schema."""
    salary_raw = job.get("salary") or ""
    return {
        "title": _truncate(job.get("title") or "", 60),
        "company": _truncate(job.get("company_name") or "", 40),
        "location": _truncate(job.get("candidate_required_location") or "", 30),
        "salary": _truncate(salary_raw if salary_raw else "No especificado", 25),
        "remote_type": "Remoto",
        "url": job.get("url") or "",
        "date_posted": job.get("publication_date") or "",
        "source": "Remotive",
    }


def _passes_default_filters(job: dict) -> bool:
    """Check if job passes default filters for scheduled briefing."""
    # For JSearch
    if job.get("source") == "JSearch":
        city = job.get("_city", "")

        if not city:
            return True
        if "madrid" in city:
            return True
        if job.get("_is_remote"):
            return True
        if any(kw in job.get("_description_snippet", "") for kw in REMOTE_KEYWORDS):
            return True
        return False

    # For Adzuna
    if job.get("source") == "Adzuna":
        location_display = job.get("_location_display", "")
        description_snippet = job.get("_description_snippet", "")
        area = job.get("_area", [])

        if "madrid" in location_display:
            return True
        if any(kw in description_snippet for kw in REMOTE_KEYWORDS):
            return True
        if any("madrid" in a for a in area):
            return True
        return False

    # For Remotive - already filtered by location in _search_remotive
    return True


def _strip_filter_fields(job: dict) -> dict:
    """Remove internal filtering fields before returning to LLM."""
    return {k: v for k, v in job.items() if not k.startswith("_")}


def _dedup_key(job: dict) -> tuple:
    """Generate deduplication key: (title[:40], company[:30])."""
    title = (job.get("title") or "").lower().strip()[:40]
    company = (job.get("company") or "").lower().strip()[:30]
    return (title, company)


# ---------------------------------------------------------------------------
# Fix 2: Score jobs by Spain/remote priority
# ---------------------------------------------------------------------------
def _score_job(job: dict) -> int:
    score = 0
    loc = job.get("location", "").lower()
    rt = job.get("remote_type", "").lower()

    # Geography priority
    if "madrid" in loc:
        score += 10
    elif "españa" in loc or "spain" in loc or loc == "es":
        score += 7
    elif "europe" in loc or "europa" in loc or "emea" in loc:
        score += 4
    elif "worldwide" in loc or "world" in loc or loc == "":
        score += 2

    # Modality priority
    if rt == "remoto":
        score += 5
    elif rt == "híbrido":
        score += 4

    # Penalize presencial outside Madrid
    if rt == "presencial" and "madrid" not in loc:
        score -= 10

    return score


# ---------------------------------------------------------------------------
# Fix 3: Balance results across sources with round-robin
# ---------------------------------------------------------------------------
def _balance_sources(jsearch: list, adzuna: list, remotive: list, total: int) -> list:
    """Take results from each source in rotation until total reached."""
    sources = [list(s) for s in [jsearch, adzuna, remotive] if s]
    result = []
    i = 0
    while len(result) < total and any(sources):
        src = sources[i % len(sources)]
        if src:
            result.append(src.pop(0))
        sources = [s for s in sources if s]
        if not sources:
            break
        i += 1
    return result


# ---------------------------------------------------------------------------
# Fix 5: Compact LLM summary string
# ---------------------------------------------------------------------------
def _format_jobs_for_llm(jobs: list, sources_used: list) -> str:
    if not jobs:
        return "Sin ofertas encontradas hoy."

    lines = [f"Ofertas ({len(jobs)}) | Fuentes: {', '.join(sources_used)}\n"]
    for i, j in enumerate(jobs, 1):
        salary = j["salary"] if j["salary"] != "No especificado" else "—"
        lines.append(
            f"{i}. {j['title']} @ {j['company']}\n"
            f"   📍{j['location']} · {j['remote_type']} · 💶{salary}\n"
            f"   🔗{j['url']}\n"
            f"   [{j['source']}] {j['date_posted']}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Source search functions
# ---------------------------------------------------------------------------
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

    # Fix 4: Slice to top 5 before returning
    return all_jobs[:5]


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

    # Fix 4: Slice to top 5 before returning
    return all_jobs[:5]


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

    # Fix 4: Slice to top 5 before returning
    return all_jobs[:5]


async def search_jobs(query: str = None) -> dict:
    """Search jobs from all sources for scheduled briefing.

    Uses rotating queries based on weekday if no query provided.
    Returns top 5 results after deduplication, balancing and scoring.
    """
    LIMIT = 5

    # Use rotating query if none provided
    if query is None:
        query = DEFAULT_QUERIES[datetime.now(ZoneInfo("Europe/Madrid")).weekday()]

    # Fix 4: Fetch from all sources in parallel (each already sliced to [:5])
    results_raw = await asyncio.gather(
        _search_jsearch(query),
        _search_adzuna(query),
        _search_remotive(query),
        return_exceptions=True
    )

    jsearch_jobs, adzuna_jobs, remotive_jobs = [], [], []
    sources_list = [jsearch_jobs, adzuna_jobs, remotive_jobs]
    source_labels = ["JSearch", "Adzuna", "Remotive"]

    for i, result in enumerate(results_raw):
        if isinstance(result, Exception):
            logger.error(f"Error en fuente {source_labels[i]}: {result}")
        elif isinstance(result, list):
            sources_list[i].extend(result)

    # Apply default post-filters (scheduled mode only)
    jsearch_jobs = [j for j in jsearch_jobs if _passes_default_filters(j)]
    adzuna_jobs = [j for j in adzuna_jobs if _passes_default_filters(j)]
    # remotive: already location-filtered in _search_remotive

    # Strip internal filter fields before further processing
    jsearch_jobs = [_strip_filter_fields(j) for j in jsearch_jobs]
    adzuna_jobs = [_strip_filter_fields(j) for j in adzuna_jobs]

    # Fix 3: Balance sources
    balanced = _balance_sources(jsearch_jobs, adzuna_jobs, remotive_jobs, total=LIMIT * 2)

    # Deduplicate
    seen = set()
    unique_jobs = []
    for job in balanced:
        key = _dedup_key(job)
        if key not in seen:
            seen.add(key)
            unique_jobs.append(job)

    # Fix 2: Sort by Spain/remote score (date as tiebreaker)
    unique_jobs.sort(
        key=lambda x: (_score_job(x), x.get("date_posted") or ""),
        reverse=True
    )

    top_jobs = unique_jobs[:LIMIT]

    if not top_jobs:
        return {
            "result": "Sin ofertas encontradas hoy.",
            "jobs_count": 0,
            "sources_used": []
        }

    sources_used = list(dict.fromkeys(job["source"] for job in top_jobs))

    # Fix 5: Return compact string
    return {
        "result": _format_jobs_for_llm(top_jobs, sources_used),
        "jobs_count": len(top_jobs),
        "sources_used": sources_used
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
    LIMIT = 10

    if sources is None:
        sources = ["jsearch", "adzuna", "remotive"]

    # Build search tasks based on selected sources
    tasks = []
    source_names = []

    if "jsearch" in sources:
        tasks.append(_search_jsearch(query))
        source_names.append("JSearch")

    if "adzuna" in sources:
        tasks.append(_search_adzuna(query, location=location, salary_min=salary_min))
        source_names.append("Adzuna")

    if "remotive" in sources:
        tasks.append(_search_remotive(query, location_hint=location))
        source_names.append("Remotive")

    # Execute all searches in parallel (each already sliced to [:5])
    results_raw = await asyncio.gather(*tasks, return_exceptions=True)

    # Separate by source for balancing
    per_source: dict = {}
    for idx, name in enumerate(source_names):
        result = results_raw[idx]
        if isinstance(result, Exception):
            logger.error(f"Error en fuente {name}: {result}")
            per_source[name] = []
        elif isinstance(result, list):
            per_source[name] = result
        else:
            per_source[name] = []

    # Strip internal filter fields
    for name in per_source:
        per_source[name] = [_strip_filter_fields(j) for j in per_source[name]]

    # Apply remote-only filter per source
    if remote_only:
        for name in per_source:
            per_source[name] = [
                j for j in per_source[name]
                if j.get("remote_type") in ["Remoto", "Híbrido"]
            ]

    # Salary filter per source
    if salary_min:
        import re

        def passes_salary(job: dict) -> bool:
            salary_str = job.get("salary", "")
            if "No especificado" in salary_str:
                return True
            numbers = re.findall(r'(\d+)', salary_str.replace(".", ""))
            if numbers:
                first_num = int(numbers[0])
                return first_num >= salary_min
            return True

        for name in per_source:
            per_source[name] = [j for j in per_source[name] if passes_salary(j)]

    # Fix 3: Balance sources
    js = per_source.get("JSearch", [])
    az = per_source.get("Adzuna", [])
    rm = per_source.get("Remotive", [])
    balanced = _balance_sources(js, az, rm, total=LIMIT * 2)

    # Deduplicate
    seen = set()
    unique_jobs = []
    for job in balanced:
        key = _dedup_key(job)
        if key not in seen:
            seen.add(key)
            unique_jobs.append(job)

    # Fix 2: Sort by Spain/remote score (date as tiebreaker)
    unique_jobs.sort(
        key=lambda x: (_score_job(x), x.get("date_posted") or ""),
        reverse=True
    )

    top_jobs = unique_jobs[:LIMIT]

    if not top_jobs:
        return {
            "result": f"No se encontraron ofertas para '{query}' con los filtros especificados.",
            "jobs_count": 0,
            "sources_used": []
        }

    sources_used = list(dict.fromkeys(job["source"] for job in top_jobs))

    # Fix 5: Return compact string
    return {
        "result": _format_jobs_for_llm(top_jobs, sources_used),
        "jobs_count": len(top_jobs),
        "sources_used": sources_used
    }


def _format_jobs(jobs: List[Dict]) -> str:
    """Format jobs for display (kept for any internal callers)."""
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