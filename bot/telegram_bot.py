from telegram import Update, Document
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from services.cv_service import (
    extract_text_from_pdf_bytes,
    download_telegram_file,
    extract_google_doc_id,
    is_google_url
)
from config import settings
from services.groq_service import mentor_service
from services.scheduler_service import create_scheduler
from memory.database import init_db
from utils.logger import get_logger

logger = get_logger("telegram_bot")


def create_app() -> Application:
    """Crea y configura la aplicación de Telegram."""
    # Inicializar BD al arrancar
    init_db()

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("clear", handle_clear))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_message
    ))
    app.add_handler(MessageHandler(
        filters.Document.PDF | filters.Document.MimeType(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
        handle_document
    ))

    scheduler = create_scheduler(app.bot)
    scheduler.start()
    logger.info("Scheduler iniciado: noticias 8:00 | formación 9:00 | ofertas 9:05 L-V")

    return app


def is_authorized(update: Update) -> bool:
    """Verifica si el usuario está en la whitelist."""
    return str(update.effective_user.id) == settings.telegram_user_id


async def handle_start(update: Update, context):
    """Limpia historial e inicia nueva sesión."""
    if not is_authorized(update):
        await update.message.reply_text("No autorizado.")
        return
    mentor_service.clear_session(update.effective_user.id)
    await update.message.reply_text(
        "Sesión reiniciada. Historial borrado.\n\n"
        "Hola Alberto, soy tu Career Mentor. "
        "Estoy aquí para ayudarte a conseguir ese puesto de "
        "AI Orchestrator antes de septiembre. ¿Empezamos?"
    )


async def handle_clear(update: Update, context):
    """Alias de /start para limpiar historial."""
    if not is_authorized(update):
        return
    mentor_service.clear_session(update.effective_user.id)
    await update.message.reply_text("✅ Historial borrado.")


async def handle_help(update: Update, context):
    """Muestra ayuda."""
    if not is_authorized(update):
        return
    await update.message.reply_text(
        "Puedo ayudarte con:\n\n"
        "• Buscar ofertas de trabajo\n"
        "• Revisar emails de reclutadores\n"
        "• Analizar tu CV (pégalo aquí)\n"
        "• Ver tu calendario\n"
        "• Sugerir contenido para LinkedIn\n"
        "• Darte un plan de acción diario\n\n"
        "Comandos:\n"
        "/start o /clear — borrar historial\n"
        "/help — esta ayuda\n\n"
        "Simplemente escríbeme en lenguaje natural."
    )


async def handle_document(update: Update, context):
    """Handler para PDFs y documentos enviados por Telegram."""
    if not is_authorized(update):
        await update.message.reply_text("No autorizado.")
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    doc = update.message.document
    file_name = doc.file_name or "documento"
    
    await update.message.reply_text(
        f"📄 Recibido '{file_name}'. Extrayendo contenido..."
    )

    try:
        # Descargar archivo desde Telegram
        file = await context.bot.get_file(doc.file_id)
        file_url = file.file_path
        
        pdf_bytes = await download_telegram_file(file_url)
        if not pdf_bytes:
            await update.message.reply_text(
                "No pude descargar el archivo. Inténtalo de nuevo."
            )
            return

        # Extraer texto
        text = extract_text_from_pdf_bytes(pdf_bytes)
        if not text:
            await update.message.reply_text(
                "No pude extraer texto del PDF. "
                "¿Puedes enviarlo como Google Doc?"
            )
            return

        # Pasar el texto al mentor como si fuera un mensaje
        cv_message = (
            f"Analiza este CV y genera recomendaciones "
            f"para adaptarlo al perfil AI Orchestrator. "
            f"Luego crea un Google Doc con el CV mejorado.\n\n"
            f"CV COMPLETO:\n{text[:8000]}"
        )
        
        response = await mentor_service.chat(
            update.effective_user.id,
            cv_message
        )

        if len(response) > 4000:
            chunks = [
                response[i:i+4000]
                for i in range(0, len(response), 4000)
            ]
            for chunk in chunks:
                await update.message.reply_text(chunk)
        else:
            await update.message.reply_text(response)

    except Exception as e:
        logger.error(f"Error en handle_document: {e}", exc_info=True)
        await update.message.reply_text(
            "Error procesando el documento. Inténtalo de nuevo."
        )


async def handle_message(update: Update, context):
    """Handler principal de mensajes."""
    if not is_authorized(update):
        await update.message.reply_text("No autorizado.")
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    try:
        response = await mentor_service.chat(
            update.effective_user.id,
            update.message.text
        )
        # Dividir mensajes largos para Telegram (límite 4096 chars)
        if len(response) > 4000:
            chunks = [
                response[i:i+4000]
                for i in range(0, len(response), 4000)
            ]
            for chunk in chunks:
                await update.message.reply_text(chunk)
        else:
            await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Error en handle_message: {e}", exc_info=True)
        await update.message.reply_text(
            "Ha ocurrido un error. Inténtalo de nuevo."
        )
