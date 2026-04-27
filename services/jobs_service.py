import aiohttp
from typing import List, Dict, Optional
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from utils.logger import get_logger
import asyncio
import re


logger = get_logger("jobs_service")


# Rotating queries based on weekday (monday=0)
DEFAULT_QUERIES = [
    "Senior Analytics Engineer",        # Monday
    "Head of Digital Analytics",        # Tuesday
    "Marketing Data Scientist",         # Wednesday
    "Data Analyst Machine Learning",    # Thursday
    "Digital Analytics Lead",           # Friday
    "Data Science Manager",             # Saturday
    "Analytics Engineer",               # Sunday
]

# Remote keywords for post-filtering (case-insensitive)
REMOTE_KEYWORDS = ["remot", "teletrabajo", "híbrid", "hybrid", "desde casa", "work from home"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _truncate(s: str, max_len: int) -> str:
    if not s:
        return ""
    return s[:max_len] + "…" if len(s) > max_len else s


def _detect_remote_type(job: dict, source: str) -> str:
    description = (job.get("job_description") or job.get("description") or "").lower()

    if source == "remotive":
        return "Remoto"

    if job.get("job_is_remote") or job.get("is_remote"):
        return "Remoto"

    if "híbrid" in description or "hybrid" in description:
        return "Híbrido"

    if "remot" in description or "teletrabajo" in description:
        return "Remoto"

    city = job.get("job_city") or job.get("city") or ""
    if city and not any(kw in description for kw in REMOTE_KEYWORDS):
        if job.get("job_is_hybrid"):
            return "Híbrido"
        return "Presencial"

    return "No especificado"


def _format_salary(salary_min: Optional[float], salary_max: Optional[float], source: str) -> str:
    if not salary_min and not salary_max:
        return "No especificado"

    if source == "jsearch":
        min_k = int(salary_min // 1000) if salary_min else None
        max_k = int(salary_max // 1000) if salary_max else None
        if min_k and max_k:
            return f"{min_k}k€ - {max_k}k€"
        elif min_k:
            return f"desde {min_k}k€"
        elif max_k:
            return f"hasta {max_k}k€"
    else:
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
# Normalize functions
# ---------------------------------------------------------------------------
def _normalize_jsearch_job(job: dict) -> dict:
    return {
        "title": _truncate(job.get("job_title") or "", 60),
        "company": _truncate(job.get("employer_name") or "", 40),
        "location": _truncate(
            f"{job.get('job_city') or ''}, {job.get('job_country') or ''}".strip(", "),
            35
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
        # internal fields for _passes_default_filters (stripped before LLM)
        "_city": (job.get("job_city") or "").lower(),
        "_is_remote": bool(job.get("job_is_remote")),
        "_description_snippet": (job.get("job_description") or "")[:200].lower(),
    }


def _normalize_adzuna_job(job: dict) -> dict:
    location = job.get("location", {})
    location_str = location.get("display_name", "") if isinstance(location, dict) else ""
    area = location.get("area", []) if isinstance(location, dict) else []

    return {
        "title": _truncate(job.get("title") or "", 60),
        "company": _truncate(
            job.get("company", {}).get("display_name", "") if isinstance(job.get("company"), dict) else str(job.get("company", "")),
            40
        ),
        "location": _truncate(location_str, 35),
        "salary": _truncate(_format_salary(
            job.get("salary_min"),
            job.get("salary_max"),
            "adzuna"
        ), 25),
        "remote_type": _detect_remote_type(job, "adzuna"),
        "url": job.get("redirect_url") or "",
        "date_posted": job.get("created") or "",
        "source": "Adzuna",
        "_location_display": location_str.lower(),
        "_area": [str(a).lower() for a in area] if isinstance(area, list) else [],
        "_description_snippet": (job.get("description") or "")[:200].lower(),
    }


def _normalize_remotive_job(job: dict) -> dict:
    salary_raw = job.get("salary") or ""
    return {
        "title": _truncate(job.get("title") or "", 60),
        "company": _truncate(job.get("company_name") or "", 40),
        "location": _truncate(job.get("candidate_required_location") or "", 35),
        "salary": _truncate(salary_raw if salary_raw else "No especificado", 25),
        "remote_type": "Remoto",
        "url": job.get("url") or "",
        "date_posted": job.get("publication_date") or "",
        "source": "Remotive",
    }


def _passes_default_filters(job: dict) -> bool:
    """Pre-filter using internal fields (before strip). Only for scheduled mode."""
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

    # Remotive: already location-filtered in _search_remotive
    return True


def _strip_filter_fields(job: dict) -> dict:
    """Remove internal _ fields before returning to LLM."""
    return {k: v for k, v in job.items() if not k.startswith("_")}


def _dedup_key(job: dict) -> tuple:
    title = (job.get("title") or "").lower().strip()[:40]
    company = (job.get("company") or "").lower().strip()[:30]
    return (title, company)


# ---------------------------------------------------------------------------
# FIX: _is_spain_compatible — remote_type has PRIORITY over company location
#
# ROOT CAUSE of the bug: the old filter checked location string for "united states"
# and excluded ALL jobs with US company location, including fully remote roles
# that can be worked from Madrid. JSearch with country_code=ES still returns
# many US-based companies advertising remote roles.
#
# NEW LOGIC:
#   - remote_type == "Remoto"  → ALWAYS compatible (workable from anywhere)
#   - remote_type == "Híbrido" → only if office is in Spain
#   - remote_type == "Presencial" → only if location is Spain/Madrid
#   - remote_type == "No especificado" → exclude only hard non-Spain cities
# ---------------------------------------------------------------------------
def _is_spain_compatible(job: dict) -> bool:
    loc = job.get("location", "").lower()
    rt = job.get("remote_type", "").lower()

    # Remoto: always compatible — can be worked from Spain regardless of company location
    if rt == "remoto":
        return True

    # Híbrido: only if office is in Spain
    if rt == "híbrido":
        return any(k in loc for k in [
            "madrid", "españa", "spain", "barcelona",
            "valencia", "sevilla", "bilbao", "zaragoza"
        ])

    # Presencial: only Spain/Madrid
    if rt == "presencial":
        return any(k in loc for k in ["madrid", "españa", "spain", "barcelona"])

    # No especificado: exclude only if explicit foreign city present
    if rt in ("no especificado", ""):
        hard_exclude = [
            "new york", "san francisco", "los angeles", "chicago",
            "london", "paris", "berlin", "amsterdam", "rome",
            "toronto", "sydney", "melbourne", "singapore"
        ]
        if any(k in loc for k in hard_exclude):
            return False
        return True  # benefit of the doubt

    return True


def _score_job(job: dict) -> int:
    """Score jobs: Madrid hybrid > Spain remote > Europe remote > Worldwide remote > US remote."""
    score = 0
    loc = job.get("location", "").lower()
    rt = job.get("remote_type", "").lower()

    # Geography score
    if "madrid" in loc:
        score += 10
    elif any(k in loc for k in ["españa", "spain", "barcelona"]):
        score += 7
    elif any(k in loc for k in ["europe", "europa", "emea"]):
        score += 4
    elif loc in ("", "worldwide", "world") or "remote" in loc:
        score += 2
    else:
        score += 1  # unknown geography, keep but low priority

    # Modality score
    if rt == "remoto":
        score += 5
    elif rt == "híbrido":
        score += 4

    return score


# ---------------------------------------------------------------------------
# Balance sources round-robin
# ---------------------------------------------------------------------------
def _balance_sources(jsearch: list, adzuna: list, remotive: list, total: int) -> list:
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
# Compact LLM output
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
    try:
        from config import settings
        rapidapi_key = settings.rapidapi_key
    except Exception:
        logger.warning("JSearch: no settings available")
        return []

    if not rapidapi_key:
        logger.warning("JSearch no configurado: RAPIDAPI_KEY vacío")
        return []

    headers = {
        "X-RapidAPI-Key": rapidapi_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
    }

    params = {
        "query": query,
        "page": "1",
        "num_pages": "2",
        "country_code": "es",
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

    return all_jobs[:5]


async def _search_adzuna(query: str, location: str = None, salary_min: int = None) -> List[dict]:
    try:
        from config import settings
        adzuna_app_id = settings.adzuna_app_id
        adzuna_app_key = settings.adzuna_app_key
    except Exception:
        logger.warning("Adzuna: no settings available")
        return []

    if not adzuna_app_id or not adzuna_app_key:
        logger.warning("Adzuna no configurado: ADZUNA_APP_ID o ADZUNA_APP_KEY vacíos")
        return []

    ADZUNA_QUERY_MAP = {
        "ai orchestrator": "artificial intelligence",
        "llm engineer": "machine learning engineer",
        "agentic ai developer": "AI developer",
        "analytics engineer ai": "data engineer",
        "head of ai": "data science manager",
        "digital analytics manager": "digital analytics",
        "data analytics ai consultant": "data analytics",
        "senior analytics engineer": "analytics engineer",
        "marketing data scientist": "data scientist marketing",
        "head of digital analytics": "digital analytics manager",
        "data analyst machine learning": "data analyst",
        "digital analytics lead": "digital analytics",
        "data science manager": "data science manager",
    }
    adzuna_query = ADZUNA_QUERY_MAP.get(query.lower().strip(), query)

    params = {
        "app_id": adzuna_app_id,
        "app_key": adzuna_app_key,
        "what": adzuna_query,
        "results_per_page": 10,
        "sort_by": "date",
        "content-type": "application/json"
    }

    if salary_min is None:
        params["salary_min"] = 40000

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
                    logger.info(f"Adzuna '{adzuna_query}': {len(jobs)} ofertas")
                    for job in jobs:
                        if job.get("title") and job.get("redirect_url"):
                            all_jobs.append(_normalize_adzuna_job(job))
                else:
                    logger.warning(f"Adzuna error: {response.status}")
    except Exception as e:
        logger.error(f"Error Adzuna '{adzuna_query}': {e}")

    return all_jobs[:5]


async def _search_remotive(query: str, location_hint: str = None) -> List[dict]:
    params = {
        "search": query,
        "limit": 15
    }

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
                        location = (job.get("candidate_required_location") or "").lower()
                        location_ok = any(loc in location for loc in allowed_locations)
                        if location_hint:
                            location_ok = location_ok or location_hint.lower() in location
                        if location_ok:
                            all_jobs.append(_normalize_remotive_job(job))
                else:
                    logger.warning(f"Remotive error: {response.status}")
    except Exception as e:
        logger.error(f"Error Remotive '{query}': {e}")

    return all_jobs[:5]


# ---------------------------------------------------------------------------
# Main search functions
# ---------------------------------------------------------------------------
async def search_jobs(query: str = None, limit: int = 8) -> dict:
    """Scheduled briefing search. Uses rotating queries if no query provided."""
    if query is None:
        query = DEFAULT_QUERIES[datetime.now(ZoneInfo("Europe/Madrid")).weekday()]

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

    # Apply _passes_default_filters BEFORE stripping internal fields
    jsearch_jobs = [j for j in jsearch_jobs if _passes_default_filters(j)]
    adzuna_jobs = [j for j in adzuna_jobs if _passes_default_filters(j)]

    # Strip internal fields
    jsearch_jobs = [_strip_filter_fields(j) for j in jsearch_jobs]
    adzuna_jobs = [_strip_filter_fields(j) for j in adzuna_jobs]
    # remotive has no internal fields to strip

    # Apply Spain compatibility filter (uses remote_type as priority — see fix above)
    jsearch_jobs = [j for j in jsearch_jobs if _is_spain_compatible(j)]
    adzuna_jobs = [j for j in adzuna_jobs if _is_spain_compatible(j)]
    remotive_jobs = [j for j in remotive_jobs if _is_spain_compatible(j)]

    # Balance sources round-robin
    balanced = _balance_sources(jsearch_jobs, adzuna_jobs, remotive_jobs, total=limit * 2)

    # Deduplicate
    seen = set()
    unique_jobs = []
    for job in balanced:
        key = _dedup_key(job)
        if key not in seen:
            seen.add(key)
            unique_jobs.append(job)

    # Sort by Spain/remote score
    unique_jobs.sort(key=_score_job, reverse=True)
    top_jobs = unique_jobs[:limit]

    if not top_jobs:
        return {
            "result": "Sin ofertas encontradas hoy.",
            "jobs_count": 0,
            "sources_used": []
        }

    sources_used = list(dict.fromkeys(job["source"] for job in top_jobs))

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
    """Custom job search with user-specified parameters. No default post-filters."""
    LIMIT = 10

    if sources is None:
        sources = ["jsearch", "adzuna", "remotive"]

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

    results_raw = await asyncio.gather(*tasks, return_exceptions=True)

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

    # Strip internal fields
    for name in per_source:
        per_source[name] = [_strip_filter_fields(j) for j in per_source[name]]

    # Remote-only filter
    if remote_only:
        for name in per_source:
            per_source[name] = [
                j for j in per_source[name]
                if j.get("remote_type") in ["Remoto", "Híbrido"]
            ]

    # Salary filter
    if salary_min:
        def passes_salary(job: dict) -> bool:
            salary_str = job.get("salary", "")
            if "No especificado" in salary_str:
                return True
            numbers = re.findall(r'(\d+)', salary_str.replace(".", ""))
            if numbers:
                return int(numbers[0]) >= salary_min
            return True

        for name in per_source:
            per_source[name] = [j for j in per_source[name] if passes_salary(j)]

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

    unique_jobs.sort(key=_score_job, reverse=True)
    top_jobs = unique_jobs[:LIMIT]

    if not top_jobs:
        return {
            "result": f"No se encontraron ofertas para '{query}' con los filtros especificados.",
            "jobs_count": 0,
            "sources_used": []
        }

    sources_used = list(dict.fromkeys(job["source"] for job in top_jobs))

    return {
        "result": _format_jobs_for_llm(top_jobs, sources_used),
        "jobs_count": len(top_jobs),
        "sources_used": sources_used
    }


def _format_jobs(jobs: List[Dict]) -> str:
    """Legacy format function kept for backward compatibility."""
    if not jobs:
        return (
            "No encontré ofertas con los criterios especificados. "
            "Prueba con otros términos o ajusta los filtros."
        )

    response = f"🎯 {len(jobs)} ofertas encontradas:\n\n"
    for i, job in enumerate(jobs, 1):
        remote_icon = "🌍" if job.get("remote_type") == "Remoto" else "📍"
        response += f"{i}. {job['title']}\n"
        response += f"   🏢 {job.get('company', 'N/A')}\n"
        response += f"   {remote_icon} {job.get('remote_type', 'N/A')} — {job.get('location', 'N/A')}\n"
        salary = job.get("salary")
        if salary and "No especificado" not in salary:
            response += f"   💰 {salary}\n"
        url = job.get("url", "")
        if url:
            response += f"   🔗 {url[:80]}\n"
        response += f"   📎 Fuente: {job.get('source', '')}\n\n"

    return response
