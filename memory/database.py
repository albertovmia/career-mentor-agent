"""
Memoria persistente.
Usa PostgreSQL si DATABASE_URL está disponible (Railway).
Usa SQLite como fallback (desarrollo local).
"""

import json
import os
from typing import List, Dict, Optional
from utils.logger import get_logger

logger = get_logger("database")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    logger.info("Usando PostgreSQL para memoria persistente")
else:
    import sqlite3
    logger.info("Usando SQLite para memoria persistente")


def get_connection():
    if USE_POSTGRES:
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url)
    else:
        db_path = os.environ.get("DB_PATH", "./data/memory.db")
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn


def _ph() -> str:
    return "%s" if USE_POSTGRES else "?"


def init_db():
    conn = get_connection()
    try:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    tool_calls TEXT,
                    tool_call_id TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_conv_user_id
                ON conversations(user_id, timestamp)
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS learning_items (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    url TEXT,
                    titulo TEXT,
                    descripcion TEXT,
                    tipo TEXT DEFAULT 'video',
                    relevancia INTEGER DEFAULT 5,
                    fecha_objetivo DATE,
                    estado TEXT DEFAULT 'pendiente',
                    notas TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    tool_calls TEXT,
                    tool_call_id TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_conv_user_id
                ON conversations(user_id, timestamp)
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS learning_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    url TEXT,
                    titulo TEXT,
                    descripcion TEXT,
                    tipo TEXT DEFAULT 'video',
                    relevancia INTEGER DEFAULT 5,
                    fecha_objetivo DATE,
                    estado TEXT DEFAULT 'pendiente',
                    notas TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
        conn.commit()
        logger.info("Base de datos inicializada correctamente")
    except Exception as e:
        logger.error(f"Error inicializando BD: {e}")
        raise
    finally:
        conn.close()


def save_message(user_id: int, role: str, content: str,
                 tool_calls: List = None):
    conn = get_connection()
    p = _ph()
    try:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO conversations (user_id, role, content, tool_calls) "
            f"VALUES ({p},{p},{p},{p})",
            (user_id, role, content or "",
             json.dumps(tool_calls) if tool_calls else None)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Error guardando mensaje: {e}")
    finally:
        conn.close()


def save_tool_result(user_id: int, tool_call_id: str, content: str):
    conn = get_connection()
    p = _ph()
    try:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO conversations (user_id, role, content, tool_call_id) "
            f"VALUES ({p},'tool',{p},{p})",
            (user_id, content, tool_call_id)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Error guardando tool result: {e}")
    finally:
        conn.close()


def get_history(user_id: int, limit: int = 10) -> List[Dict]:
    conn = get_connection()
    p = _ph()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT role, content, tool_calls, tool_call_id "
            f"FROM conversations WHERE user_id = {p} "
            f"ORDER BY timestamp DESC LIMIT {p}",
            (user_id, limit)
        )
        rows = cur.fetchall()
        messages = []
        for row in reversed(rows):
            if USE_POSTGRES:
                role, content, tool_calls, tool_call_id = row
            else:
                role = row["role"]
                content = row["content"]
                tool_calls = row["tool_calls"]
                tool_call_id = row["tool_call_id"]

            if role == "tool":
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id or "unknown",
                    "content": content or ""
                })
            elif role == "assistant" and tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": content or "",
                    "tool_calls": json.loads(tool_calls)
                })
            else:
                messages.append({
                    "role": role,
                    "content": content or ""
                })
        return messages
    except Exception as e:
        logger.error(f"Error obteniendo historial: {e}")
        return []
    finally:
        conn.close()


def clear_history(user_id: int):
    conn = get_connection()
    p = _ph()
    try:
        cur = conn.cursor()
        cur.execute(
            f"DELETE FROM conversations WHERE user_id = {p}",
            (user_id,)
        )
        conn.commit()
        logger.info(f"Historial borrado para usuario {user_id}")
    except Exception as e:
        logger.error(f"Error borrando historial: {e}")
    finally:
        conn.close()


def add_learning_item(user_id: int, url: str, titulo: str,
                      descripcion: str = "", tipo: str = "video",
                      relevancia: int = 5, fecha_objetivo: str = None,
                      notas: str = "") -> int:
    conn = get_connection()
    p = _ph()
    try:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO learning_items "
            f"(user_id, url, titulo, descripcion, tipo, relevancia, "
            f"fecha_objetivo, notas) "
            f"VALUES ({p},{p},{p},{p},{p},{p},{p},{p})",
            (user_id, url, titulo, descripcion, tipo,
             relevancia, fecha_objetivo, notas)
        )
        conn.commit()
        if USE_POSTGRES:
            cur.execute("SELECT lastval()")
        else:
            cur.execute("SELECT last_insert_rowid()")
        return cur.fetchone()[0]
    except Exception as e:
        logger.error(f"Error añadiendo learning item: {e}")
        return -1
    finally:
        conn.close()


def get_learning_items(user_id: int,
                       estado: str = "pendiente") -> List[Dict]:
    conn = get_connection()
    p = _ph()
    try:
        cur = conn.cursor()
        if estado:
            cur.execute(
                f"SELECT * FROM learning_items "
                f"WHERE user_id = {p} AND estado = {p} "
                f"ORDER BY relevancia DESC, fecha_objetivo ASC",
                (user_id, estado)
            )
        else:
            cur.execute(
                f"SELECT * FROM learning_items WHERE user_id = {p} "
                f"ORDER BY relevancia DESC",
                (user_id,)
            )
        rows = cur.fetchall()
        if USE_POSTGRES:
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in rows]
        else:
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Error obteniendo learning items: {e}")
        return []
    finally:
        conn.close()


def update_learning_item(item_id: int, **kwargs) -> bool:
    if not kwargs:
        return False
    conn = get_connection()
    p = _ph()
    try:
        cur = conn.cursor()
        set_clause = ", ".join([f"{k} = {p}" for k in kwargs.keys()])
        values = list(kwargs.values()) + [item_id]
        cur.execute(
            f"UPDATE learning_items SET {set_clause}, "
            f"updated_at = CURRENT_TIMESTAMP WHERE id = {p}",
            values
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error actualizando learning item: {e}")
        return False
    finally:
        conn.close()


def complete_learning_item(item_id: int) -> bool:
    return update_learning_item(item_id, estado="completado")


def get_overdue_learning_items(user_id: int) -> List[Dict]:
    conn = get_connection()
    p = _ph()
    try:
        cur = conn.cursor()
        today = "CURRENT_DATE" if USE_POSTGRES else "date('now')"
        cur.execute(
            f"SELECT * FROM learning_items "
            f"WHERE user_id = {p} AND estado = 'pendiente' "
            f"AND fecha_objetivo < {today} "
            f"ORDER BY fecha_objetivo ASC",
            (user_id,)
        )
        rows = cur.fetchall()
        if USE_POSTGRES:
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in rows]
        else:
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Error obteniendo items vencidos: {e}")
        return []
    finally:
        conn.close()
