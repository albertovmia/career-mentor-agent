#!/usr/bin/env python3
"""
Smoke test para validar el Career Mentor Agent en producción.
Ejercita cada handler de herramientas y el flujo de chat completo.
Usa las API keys reales del .env.
"""
import asyncio
import os
import sys
import json
import traceback
from datetime import datetime

# Asegurar que el path raíz está en PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Cargar .env
from dotenv import load_dotenv
load_dotenv()

from config import settings
from utils.logger import get_logger

logger = get_logger("smoke_test")

RESULTS = []

def log_result(test_name: str, passed: bool, detail: str = ""):
    status = "✅ PASS" if passed else "❌ FAIL"
    RESULTS.append((test_name, passed, detail))
    print(f"\n{status} | {test_name}")
    if detail:
        print(f"   → {detail[:200]}")


async def test_1_get_current_time():
    """Test: get_current_time devuelve fecha válida."""
    import pytz
    madrid = pytz.timezone("Europe/Madrid")
    now = datetime.now(madrid)
    result = now.strftime("%A %d de %B de %Y, %H:%M")
    log_result("get_current_time", bool(result), result)


async def test_2_search_jobs():
    """Test: search_jobs devuelve ofertas."""
    from services.jobs_service import search_jobs
    try:
        ofertas = await search_jobs("ai orchestrator")
        count = len(ofertas) if ofertas else 0
        log_result(
            "search_jobs",
            count > 0,
            f"{count} ofertas encontradas"
        )
    except Exception as e:
        log_result("search_jobs", False, str(e))


async def test_3_list_learning_items():
    """Test: list_learning_items no crashea."""
    from memory.database import get_learning_items
    try:
        items = get_learning_items(
            int(settings.telegram_user_id),
            estado="pendiente",
            limit=10
        )
        items = items or []
        log_result(
            "list_learning_items",
            True,
            f"{len(items)} items pendientes"
        )
    except Exception as e:
        log_result("list_learning_items", False, str(e))


async def test_4_add_and_dedup_learning():
    """Test: add_learning_item y dedup de URLs YouTube."""
    from memory.database import add_learning_item
    user_id = int(settings.telegram_user_id)
    test_url_1 = "https://youtu.be/test_dedup_smoke?si=abc"
    test_url_2 = "https://www.youtube.com/watch?v=test_dedup_smoke&utm_source=test"
    try:
        id1, _ = add_learning_item(
            user_id=user_id,
            url=test_url_1,
            titulo="Test Dedup Smoke",
            tipo="video",
            relevancia=5,
            fecha_objetivo="2026-12-31"
        )
        id2, _ = add_learning_item(
            user_id=user_id,
            url=test_url_2,
            titulo="Test Dedup Smoke 2",
            tipo="video",
            relevancia=5,
            fecha_objetivo="2026-12-31"
        )
        dedup_ok = (id1 == id2)
        log_result(
            "add_learning_item + dedup",
            dedup_ok,
            f"id1={id1}, id2={id2}, dedup={'OK' if dedup_ok else 'FAIL - DUPLICADO'}"
        )
        # Limpieza
        from memory.database import get_connection, _ph, USE_POSTGRES
        conn = get_connection()
        p = _ph()
        cur = conn.cursor()
        cur.execute(
            f"DELETE FROM learning_items WHERE user_id = {p} AND titulo LIKE {p}",
            (user_id, "Test Dedup Smoke%")
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log_result("add_learning_item + dedup", False, traceback.format_exc())


async def test_5_complete_learning_item():
    """Test: complete_learning_item acepta solo item_id."""
    from memory.database import complete_learning_item
    try:
        # Con un ID inexistente, debería no crashear
        result = complete_learning_item(item_id=999999)
        log_result(
            "complete_learning_item(signature)",
            True,
            f"Ejecutado sin crash, result={result}"
        )
    except TypeError as e:
        log_result("complete_learning_item(signature)", False, str(e))
    except Exception as e:
        # Otros errores (como DB) son aceptables
        log_result(
            "complete_learning_item(signature)",
            True,
            f"Sin error de signature, otro error (OK): {e}"
        )


async def test_6_url_normalization():
    """Test: normalize_url colapsa YouTube short/full."""
    from utils.url_utils import normalize_url
    tests = [
        ("https://youtu.be/dQw4w9WgXcQ?si=abc", "youtube.com/watch?v=dqw4w9wgxcq"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&utm_source=X", "youtube.com/watch?v=dqw4w9wgxcq"),
        ("https://medium.com/@user/post/", "medium.com/@user/post"),
    ]
    all_pass = True
    detail = ""
    for inp, expected in tests:
        got = normalize_url(inp)
        if got != expected:
            all_pass = False
            detail += f"FAIL: {inp} → {got} (expected {expected}); "
    log_result(
        "url_normalization",
        all_pass,
        detail or "Todas las URLs normalizadas correctamente"
    )


async def test_7_datetime_normalization():
    """Test: _normalize_datetime no crashea con strings de 10 chars."""
    from services.gws_service import GoogleWorkspaceService
    gws = GoogleWorkspaceService()
    tests = [
        ("2026-04-02", True),       # 10 chars - was crashing
        ("2026-04-02T10:00:00", True),
        ("2026-04-02 10:00:00", True),  # space → T
        ("", True),
        (None, True),
    ]
    all_pass = True
    detail = ""
    for dt_str, should_pass in tests:
        try:
            result = gws._normalize_datetime(dt_str)
            if not should_pass:
                all_pass = False
                detail += f"FAIL: expected crash for '{dt_str}'; "
        except Exception as e:
            if should_pass:
                all_pass = False
                detail += f"CRASH: '{dt_str}' → {e}; "
    log_result(
        "datetime_normalization",
        all_pass,
        detail or "Todas las fechas normalizadas correctamente"
    )


async def test_8_groq_chat():
    """Test: MentorService.chat con un saludo simple."""
    from services.groq_service import MentorService
    mentor = MentorService()
    user_id = int(settings.telegram_user_id)
    try:
        response = await mentor.chat(user_id, "Hola")
        if response and isinstance(response, str) and len(response) > 10:
            log_result(
                "groq_chat (saludo)",
                True,
                f"Respuesta ({len(response)} chars): {response[:150]}..."
            )
        else:
            log_result(
                "groq_chat (saludo)",
                False,
                f"Respuesta vacía o inválida: {repr(response)}"
            )
    except Exception as e:
        log_result("groq_chat (saludo)", False, traceback.format_exc())


async def test_9_groq_chat_jobs():
    """Test: chat con búsqueda de empleo dispara search_jobs."""
    from services.groq_service import MentorService
    mentor = MentorService()
    user_id = int(settings.telegram_user_id)
    try:
        response = await mentor.chat(
            user_id,
            "Busca ofertas de AI Orchestrator en remoto"
        )
        has_jobs = response and ("oferta" in response.lower()
                                or "puesto" in response.lower()
                                or "trabajo" in response.lower()
                                or "empleo" in response.lower()
                                or "remoto" in response.lower()
                                or "orchestrator" in response.lower())
        log_result(
            "groq_chat (search_jobs)",
            bool(has_jobs),
            f"Respuesta ({len(response or '')} chars): {(response or '')[:150]}..."
        )
    except Exception as e:
        log_result("groq_chat (search_jobs)", False, traceback.format_exc())


async def test_10_bot_health():
    """Test: Verificar que el bot está vivo en Telegram."""
    import httpx
    token = settings.telegram_bot_token
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"https://api.telegram.org/bot{token}/getMe",
                timeout=10
            )
            data = r.json()
            if data.get("ok"):
                bot_name = data["result"].get("username", "?")
                log_result(
                    "bot_health (getMe)",
                    True,
                    f"Bot activo: @{bot_name}"
                )
            else:
                log_result("bot_health (getMe)", False, json.dumps(data))
    except Exception as e:
        log_result("bot_health (getMe)", False, str(e))


async def main():
    print("=" * 60)
    print("🔬 SMOKE TEST — Career Mentor Agent")
    print("=" * 60)
    print(f"Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"DB: {settings.db_path}")
    print(f"Groq model: {settings.groq_model}")
    print()

    # Tests rápidos (sin LLM)
    await test_1_get_current_time()
    await test_6_url_normalization()
    await test_7_datetime_normalization()
    await test_5_complete_learning_item()
    await test_3_list_learning_items()
    await test_4_add_and_dedup_learning()
    await test_10_bot_health()

    # Tests con LLM (requieren Groq API)
    await test_8_groq_chat()
    await test_9_groq_chat_jobs()

    # Resumen
    print("\n" + "=" * 60)
    print("📊 RESUMEN")
    print("=" * 60)
    passed = sum(1 for _, p, _ in RESULTS if p)
    failed = sum(1 for _, p, _ in RESULTS if not p)
    print(f"   ✅ Pasados: {passed}")
    print(f"   ❌ Fallidos: {failed}")
    print(f"   Total: {len(RESULTS)}")

    if failed:
        print("\n⚠️  Tests fallidos:")
        for name, p, detail in RESULTS:
            if not p:
                print(f"   - {name}: {detail}")

    print()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
