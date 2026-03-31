import io
import re
import aiohttp
from typing import Optional, Dict
from utils.logger import get_logger

logger = get_logger("cv_service")


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Extrae texto de un PDF en memoria usando pymupdf."""
    try:
        import fitz  # pymupdf
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        full_text = "\n".join(text_parts).strip()
        logger.info(f"PDF extraído: {len(full_text)} caracteres")
        return full_text
    except Exception as e:
        logger.error(f"Error extrayendo PDF: {e}")
        return ""


def extract_google_doc_id(url: str) -> Optional[str]:
    """Extrae el ID de un Google Docs o Slides desde la URL."""
    patterns = [
        r"/document/d/([a-zA-Z0-9_-]+)",
        r"/presentation/d/([a-zA-Z0-9_-]+)",
        r"/spreadsheets/d/([a-zA-Z0-9_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def is_google_url(text: str) -> bool:
    """Detecta si el texto contiene un link de Google Docs/Slides."""
    return bool(re.search(
        r"docs\.google\.com/(document|presentation|spreadsheets)",
        text
    ))


async def download_telegram_file(
    file_url: str
) -> Optional[bytes]:
    """Descarga un archivo de Telegram."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                file_url,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    return await response.read()
                logger.error(
                    f"Error descargando archivo: {response.status}"
                )
                return None
    except Exception as e:
        logger.error(f"Error en download_telegram_file: {e}")
        return None


def generate_cv_doc_content(
    cv_text: str,
    analysis: Dict,
    profile: Dict
) -> str:
    """
    Genera el contenido estructurado para el CV mejorado.
    Devuelve texto formateado para insertar en Google Docs.
    """
    skills_detectadas = analysis.get("skills_detectadas", [])
    skills_faltantes = analysis.get("skills_faltantes", [])
    
    content = f"""CV MEJORADO — {profile.get('nombre', 'Alberto')}
Orientado a: {profile.get('objetivo', 'AI Orchestrator / Augmented Analyst')}
Generado por Career Mentor

═══════════════════════════════════════

RESUMEN EJECUTIVO
─────────────────
Profesional de Digital Analytics con experiencia en atribución 
multicanal, ETL y visualización de datos (Looker, GA4). 
Actualmente en transición hacia roles de IA aplicada, 
incorporando LLMs y agentes de IA a flujos de análisis digital.
No busco un cambio de sector sino una evolución natural: 
usar IA para hacer mejor lo que ya sé hacer.

SKILLS TÉCNICAS
───────────────
✅ Consolidadas:
{chr(10).join(f'• {s}' for s in profile.get('skills_actuales', []))}

🔄 En desarrollo (objetivo AI Orchestrator):
{chr(10).join(f'• {s}' for s in profile.get('skills_objetivo', []))}

📌 Skills detectadas en tu CV actual:
{chr(10).join(f'• {s}' for s in skills_detectadas) or '• (ninguna de las objetivo detectadas)'}

⚠️  Skills prioritarias a añadir:
{chr(10).join(f'• {s}' for s in skills_faltantes[:5])}

NARRATIVA RECOMENDADA PARA LINKEDIN/CV
───────────────────────────────────────
"{profile.get('narrativa_linkedin', '')}"

EXPERIENCIA — CÓMO REFORMULARLA
────────────────────────────────
Para cada puesto anterior, añade una línea de impacto con IA:
- "Implementé análisis automatizado con Python reduciendo X horas"
- "Diseñé pipeline de datos que alimenta decisiones de campaña"
- "Exploré integración de LLMs para automatizar reporting"

PRÓXIMOS PASOS RECOMENDADOS
────────────────────────────
1. Añadir proyecto personal de IA al CV (ej: este agente)
2. Certificación: DeepLearning.AI - AI For Everyone o similar
3. Reformular headline LinkedIn: 
   "Digital Analytics → AI-Augmented Analyst"
4. Añadir sección "Proyectos de IA" con career-mentor-agent

═══════════════════════════════════════
Match actual con perfil objetivo: {analysis.get('porcentaje_match_objetivo', 0)}%
Generado el: {__import__('datetime').datetime.now().strftime('%d/%m/%Y %H:%M')}
"""
    return content
