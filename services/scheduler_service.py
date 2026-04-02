import asyncio
import re
import json
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot
from groq import AsyncGroq
from config import settings
from memory.database import get_overdue_learning_items
from services.news_service import (
    get_all_news, format_news_for_llm, format_news_for_telegram
)
from services.jobs_service import search_jobs
from utils.logger import get_logger
import pytz

logger = get_logger("scheduler")
madrid_tz = pytz.timezone('Europe/Madrid')

WEEKDAYS = "mon-fri"


async def send_news_briefing(bot: Bot):
    """8:00 L-V — Noticias de IA filtradas por el LLM."""
    if not settings.telegram_user_id:
        return
    user_id = int(settings.telegram_user_id)
    try:
        all_news = await get_all_news()
        if not all_news:
            logger.info("Sin noticias disponibles hoy")
            return

        groq_client = AsyncGroq(api_key=settings.groq_api_key)
        news_text = format_news_for_llm(all_news)

        filter_prompt = f"""Eres un filtro de noticias para Alberto,
profesional de Digital Analytics en transición hacia AI Orchestrator.

Aquí tienes las últimas noticias de IA:

{news_text}

Selecciona MÁXIMO 3 noticias que sean más relevantes para alguien que:
- Quiere convertirse en AI Orchestrator / Augmented Analyst
- Está aprendiendo: LLM, RAG, LangChain, AI Agents, Python
- Trabaja en Digital Analytics actualmente

Responde SOLO con un JSON array con los índices de las noticias
seleccionadas (ej: [1, 4, 7]). Sin explicación, solo el JSON."""

        response = await groq_client.chat.completions.create(
            model=settings.groq_model,
            messages=[{"role": "user", "content": filter_prompt}],
            max_tokens=100,
            temperature=0.2
        )

        raw = response.choices[0].message.content or "[]"
        match = re.search(r'\[[\d,\s]+\]', raw)
        if not match:
            logger.warning(f"LLM no devolvió JSON válido: {raw}")
            return

        indices = json.loads(match.group())
        selected = [
            all_news[i - 1]
            for i in indices
            if 1 <= i <= len(all_news)
        ][:3]

        if not selected:
            logger.info("LLM no seleccionó noticias relevantes hoy")
            return

        mensaje = format_news_for_telegram(selected)
        await bot.send_message(
            chat_id=user_id,
            text=mensaje,
            parse_mode="Markdown"
        )
        logger.info(f"News briefing enviado: {len(selected)} noticias")

    except Exception as e:
        logger.error(f"Error en news briefing: {e}")


async def send_morning_briefing(bot: Bot):
    """9:00 L-V — Formación vencida."""
    if not settings.telegram_user_id:
        return
    user_id = int(settings.telegram_user_id)
    try:
        from memory.database import get_learning_items
        overdue = get_overdue_learning_items(user_id)
        pending = get_learning_items(user_id, estado="pendiente", limit=5)

        if not overdue and not pending:
            await bot.send_message(
                chat_id=user_id,
                text=(
                    "☀️ Buenos días Alberto. "
                    "No tienes recursos de formación pendientes. "
                    "¡Añade uno nuevo cuando quieras!"
                )
            )
            return

        lines = ["☀️ *Buenos días Alberto.* Tu formación de hoy:\n"]

        if overdue:
            lines.append(f"⚠️ *{len(overdue)} vencido(s):*")
            for item in overdue[:3]:
                lines.append(
                    f"• [{item['id']}] {item['titulo']} "
                    f"(vencía {item['fecha_objetivo']})"
                )

        if pending:
            lines.append(f"\n📚 *Próximos pendientes:*")
            for item in pending[:3]:
                fecha = item.get('fecha_objetivo') or 'sin fecha'
                lines.append(
                    f"• [{item['id']}] {item['titulo']} "
                    f"· 📅 {fecha} · ⭐{item.get('relevancia',5)}/10"
                )

        lines.append(
            "\n¿Quieres empezar con alguno o reprogramar?"
        )
        await bot.send_message(
            chat_id=user_id,
            text="\n".join(lines)
        )
        logger.info(f"Morning briefing enviado: {len(overdue)} items")
    except Exception as e:
        logger.error(f"Error en morning briefing: {e}")


async def send_jobs_briefing(bot: Bot):
    """9:05 L-V — Ofertas nuevas."""
    if not settings.telegram_user_id:
        return
    user_id = int(settings.telegram_user_id)
    try:
        result = await search_jobs(limit=5)
        ofertas = result.get("ofertas", [])

        if not ofertas:
            await bot.send_message(
                chat_id=user_id,
                text=(
                    "💼 No encontré ofertas nuevas relevantes hoy. "
                    "Te aviso si aparece algo."
                )
            )
            return

        lines = [
            f"💼 *{len(ofertas)} ofertas relevantes hoy:*\n"
        ]
        for i, job in enumerate(ofertas, 1):
            remoto = "🌍 Remoto" if job.get("remoto") else (
                f"📍 {job.get('ubicacion', 'N/A')}"
            )
            lines.append(
                f"{i}. *{job['titulo']}*\n"
                f"   🏢 {job['empresa']} · {remoto}\n"
                f"   🔗 {job['url'][:70]}"
            )

        lines.append(
            "\n¿Quieres que analice alguna de estas ofertas "
            "contra tu CV?"
        )

        await bot.send_message(
            chat_id=user_id,
            text="\n\n".join(lines),
            parse_mode="Markdown"
        )
        logger.info(f"Jobs briefing enviado: {len(ofertas)} ofertas")

    except Exception as e:
        logger.error(f"Error en jobs briefing: {e}", exc_info=True)
        try:
            await bot.send_message(
                chat_id=user_id,
                text="💼 No pude cargar las ofertas de hoy. Lo reintentaré mañana."
            )
        except Exception:
            pass


def create_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Crea y configura el scheduler con todos los jobs."""
    scheduler = AsyncIOScheduler(timezone=madrid_tz)

    # 8:00 L-V — Noticias de IA
    scheduler.add_job(
        send_news_briefing,
        trigger=CronTrigger(
            day_of_week=WEEKDAYS,
            hour=8, minute=0,
            timezone=madrid_tz
        ),
        args=[bot],
        id="news_briefing",
        replace_existing=True
    )

    # 9:00 L-V — Formación vencida
    scheduler.add_job(
        send_morning_briefing,
        trigger=CronTrigger(
            day_of_week=WEEKDAYS,
            hour=9, minute=0,
            timezone=madrid_tz
        ),
        args=[bot],
        id="morning_briefing",
        replace_existing=True
    )

    # 9:05 L-V — Ofertas del día
    scheduler.add_job(
        send_jobs_briefing,
        trigger=CronTrigger(
            day_of_week=WEEKDAYS,
            hour=9, minute=5,
            timezone=madrid_tz
        ),
        args=[bot],
        id="jobs_briefing",
        replace_existing=True
    )

    logger.info(
        "Scheduler configurado: "
        "noticias 8:00 L-V | formación 9:00 L-V | ofertas 9:05 L-V"
    )
    return scheduler
