import aiohttp
from bs4 import BeautifulSoup
from typing import Dict, Optional
from utils.logger import get_logger
import re

logger = get_logger("learning_service")

TIPO_MAP = {
    "youtube.com": "video",
    "youtu.be": "video",
    "spotify.com": "podcast",
    "open.spotify.com": "podcast",
    "linkedin.com": "post_linkedin",
    "medium.com": "articulo",
    "substack.com": "articulo",
    "arxiv.org": "paper",
}


def detect_tipo(url: str) -> str:
    for domain, tipo in TIPO_MAP.items():
        if domain in url:
            return tipo
    return "articulo"


async def fetch_url_metadata(url: str) -> Dict:
    """Extrae título y descripción de una URL."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36"
            )
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
                allow_redirects=True
            ) as response:
                if response.status != 200:
                    return {"titulo": url, "descripcion": ""}

                html = await response.text(errors='replace')
                soup = BeautifulSoup(html, 'html.parser')

                # Título: og:title > twitter:title > <title>
                titulo = ""
                og_title = soup.find("meta", property="og:title")
                if og_title:
                    titulo = og_title.get("content", "")
                if not titulo:
                    tw_title = soup.find(
                        "meta", attrs={"name": "twitter:title"}
                    )
                    if tw_title:
                        titulo = tw_title.get("content", "")
                if not titulo and soup.title:
                    titulo = soup.title.string or ""
                titulo = titulo.strip()[:200]

                # Descripción: og:description > meta description
                desc = ""
                og_desc = soup.find("meta", property="og:description")
                if og_desc:
                    desc = og_desc.get("content", "")
                if not desc:
                    meta_desc = soup.find(
                        "meta", attrs={"name": "description"}
                    )
                    if meta_desc:
                        desc = meta_desc.get("content", "")
                desc = desc.strip()[:500]

                return {
                    "titulo": titulo or url,
                    "descripcion": desc,
                    "tipo": detect_tipo(url)
                }
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return {"titulo": url, "descripcion": "", "tipo": detect_tipo(url)}


def format_learning_list(items: list) -> str:
    """Formatea lista de items para Telegram."""
    if not items:
        return "No hay recursos de aprendizaje guardados."

    iconos = {
        "video": "🎬",
        "articulo": "📄",
        "podcast": "🎧",
        "post_linkedin": "💼",
        "libro": "📚",
        "paper": "🔬",
    }

    lines = []
    for item in items:
        icono = iconos.get(item.get("tipo", "articulo"), "📌")
        relevancia_num = item.get("relevancia", 5)
        estrellas = "⭐" * min(relevancia_num, 5)
        fecha = item.get("fecha_objetivo") or "sin fecha"
        url = item.get("url", "")
        titulo = item.get("titulo", "Sin título")
        estado = item.get("estado", "pendiente")
        item_id = item.get("id", "?")

        linea = (
            f"{icono} [{item_id}] {titulo}\n"
            f"   {estrellas} {relevancia_num}/10 · "
            f"📅 {fecha} · {estado}\n"
            f"   🔗 {url}"
        )
        lines.append(linea)

    return "\n\n".join(lines)
