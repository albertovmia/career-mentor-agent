import asyncio
from bot.telegram_bot import create_app
from utils.logger import setup_logger, get_logger
from config import settings

logger = get_logger("main")


import signal
import sys

def main():
    setup_logger("career_mentor", "INFO", "career_mentor.log")
    logger.info("Iniciando Career Mentor Agent...")

    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN no configurado")
        return

    if not settings.groq_api_key:
        logger.error("GROQ_API_KEY no configurado")
        return

    app = create_app()

    def handle_shutdown(signum, frame):
        logger.info("Señal de cierre recibida. Deteniendo bot...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    import asyncio as _asyncio
    import httpx as _httpx
    # Limpiar webhook y sesiones previas para evitar Conflict
    try:
        _token = settings.telegram_bot_token
        _httpx.get(
            f"https://api.telegram.org/bot{_token}/deleteWebhook"
            f"?drop_pending_updates=true",
            timeout=5
        )
    except Exception:
        pass

    logger.info("Bot iniciado correctamente.")
    app.run_polling(
        allowed_updates=["message"],
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
