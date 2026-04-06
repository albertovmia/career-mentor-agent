import aiohttp
from typing import List, Dict
from config import settings
from utils.logger import get_logger

logger = get_logger("jobs_service")

TARGET_QUERIES = [
    "AI Orchestrator",
    "Augmented Analyst",
    "LLM Engineer remote",
    "AI Engineer remote",
    "Digital Analytics Manager",
    "Data Analytics AI",
    "Prompt Engineer",
    "Marketing Analytics"
]


async def search_jobs(query: str = None, limit: int = 10) -> Dict:
    """Busca ofertas en JSearch."""
    INVALID_QUERIES = [
        "nuevas", "trabajo", "empleo", "oferta", "ofertas",
        "buscar", "encuentra", "dame", "muéstrame", "ver",
        "busca", "new", "latest"
    ]
    if query:
        q_clean = query.lower().strip()
        if q_clean in INVALID_QUERIES or len(q_clean) < 4:
            logger.warning(
                f"Query inválida '{query}', usando targets por defecto"
            )
            query = None

    if not settings.rapidapi_key:
        return {"error": "RAPIDAPI_KEY no configurada", "ofertas": []}

    # Ignorar queries con ciudad que rompen JSearch.
    # Usar siempre las queries objetivo predefinidas.
    # Si se pasa query manual, limpiarla de ciudades.
    CITIES_TO_REMOVE = [
        "madrid", "barcelona", "spain", "españa",
        "remote", "remoto", "en madrid", "en barcelona"
    ]
    if query:
        clean_query = query.lower()
        for city in CITIES_TO_REMOVE:
            clean_query = clean_query.replace(city, "").strip()
        clean_query = clean_query.strip(" ,")
        queries = [clean_query] if clean_query else TARGET_QUERIES[:3]
    else:
        queries = TARGET_QUERIES[:3]
    all_jobs = []

    headers = {
        "X-RapidAPI-Key": settings.rapidapi_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
    }

    async with aiohttp.ClientSession() as session:
        for q in queries:
            try:
                params = {
                    "query": q,
                    "page": "1",
                    "num_pages": "2",
                    "date_posted": "week"
                }
                async with session.get(
                    "https://jsearch.p.rapidapi.com/search",
                    headers=headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        jobs = data.get("data", [])
                        logger.info(f"JSearch '{q}': {len(jobs)} ofertas")

                        for job in jobs:
                            # Defensivo: todos los campos pueden ser None
                            titulo = job.get("job_title") or ""
                            empresa = job.get("employer_name") or ""
                            url = job.get("job_apply_link") or ""
                            ciudad = job.get("job_city") or "Remote"
                            pais = job.get("job_country") or ""
                            ubicacion = f"{ciudad}, {pais}".strip(", ")

                            if not titulo or not url:
                                continue  # Saltar ofertas sin título o URL

                            job_is_remote = bool(job.get("job_is_remote"))
                            job_is_hybrid = bool(job.get("job_is_hybrid"))
                            ubic_lower = ubicacion.lower()

                            if job_is_remote:
                                allowed_remote = ["spain", "españa", "madrid", "barcelona", "europe"]
                                if not any(loc in ubic_lower for loc in allowed_remote):
                                    continue
                            
                            if job_is_hybrid:
                                if "madrid" not in ubic_lower:
                                    continue

                            all_jobs.append({
                                "titulo": titulo,
                                "empresa": empresa,
                                "url": url,
                                "ubicacion": ubicacion,
                                "remoto": job_is_remote,
                                "descripcion": (job.get("job_description") or "")[:500],
                                "skills": job.get("job_required_skills") or [],
                                "salario_min": job.get("job_min_salary"),
                                "salario_max": job.get("job_max_salary"),
                                "fuente": "jsearch"
                            })
            except Exception as e:
                logger.error(f"Error JSearch '{q}': {e}")

    # Eliminar duplicados por URL
    seen = set()
    unique_jobs = []
    for job in all_jobs:
        if job["url"] not in seen and job["url"]:
            seen.add(job["url"])
            unique_jobs.append(job)

    logger.info(f"Total ofertas únicas: {len(unique_jobs)}")
    return {
        "total": len(unique_jobs),
        "ofertas": unique_jobs[:limit],
        "formatted": _format_jobs(unique_jobs[:5])
    }


def _format_jobs(jobs: List[Dict]) -> str:
    if not jobs:
        return (
            "No encontré ofertas esta semana con las búsquedas actuales. "
            "Prueba con una keyword específica como 'AI Engineer' o "
            "'Digital Analytics'."
        )
    response = f"🎯 {len(jobs)} ofertas encontradas:\n\n"
    for i, job in enumerate(jobs, 1):
        remoto_icon = (
            "🌍 Remoto" if job.get("remoto")
            else f"📍 {job.get('ubicacion', 'N/A')}"
        )
        response += f"{i}. {job['titulo']}\n"
        response += f"   🏢 {job['empresa']}\n"
        response += f"   {remoto_icon}\n"
        if job.get("salario_min"):
            try:
                response += f"   💰 desde {int(job['salario_min']):,}€/año\n"
            except (ValueError, TypeError):
                pass
        if job.get("url"):
            response += f"   🔗 {job['url'][:80]}\n"
        response += "\n"
    return response
