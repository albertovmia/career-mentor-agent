import sqlite3
import json
from typing import List, Dict, Optional
from config import settings
from utils.logger import get_logger
import os

logger = get_logger("database")


def get_db_connection():
    # En Railway usar path absoluto para persistencia
    db_path = settings.db_path
    if not os.path.isabs(db_path):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db_path = os.path.join(base_dir, db_path.lstrip('./'))
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    try:
        conn.execute("""
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
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_id 
            ON conversations(user_id, timestamp)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS learning_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                titulo TEXT NOT NULL,
                descripcion TEXT,
                tipo TEXT DEFAULT 'video',
                relevancia INTEGER DEFAULT 5,
                fecha_objetivo TEXT,
                estado TEXT DEFAULT 'pendiente',
                notas TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        logger.info("Base de datos inicializada correctamente")
    finally:
        conn.close()


def save_message(user_id: int, role: str, content: str,
                 tool_calls: List = None):
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO conversations 
               (user_id, role, content, tool_calls) 
               VALUES (?, ?, ?, ?)""",
            (
                user_id,
                role,
                content or "",
                json.dumps(tool_calls) if tool_calls else None
            )
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Error guardando mensaje: {e}")
    finally:
        conn.close()


def save_tool_result(user_id: int, tool_call_id: str, content: str):
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO conversations 
               (user_id, role, content, tool_call_id) 
               VALUES (?, 'tool', ?, ?)""",
            (user_id, content, tool_call_id)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Error guardando tool result: {e}")
    finally:
        conn.close()


def get_history(user_id: int, limit: int = 20) -> List[Dict]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """SELECT role, content, tool_calls, tool_call_id
               FROM conversations 
               WHERE user_id = ? 
               ORDER BY timestamp DESC 
               LIMIT ?""",
            (user_id, limit)
        ).fetchall()

        messages = []
        for row in reversed(rows):
            role = row["role"]
            
            if role == "tool":
                # Mensaje de resultado de herramienta
                messages.append({
                    "role": "tool",
                    "tool_call_id": row["tool_call_id"] or "unknown",
                    "content": row["content"] or ""
                })
            elif role == "assistant" and row["tool_calls"]:
                # Mensaje de asistente con tool calls
                messages.append({
                    "role": "assistant",
                    "content": row["content"] or "",
                    "tool_calls": json.loads(row["tool_calls"])
                })
            else:
                # Mensaje normal user/assistant
                messages.append({
                    "role": role,
                    "content": row["content"] or ""
                })
        
        return messages
    finally:
        conn.close()


def add_learning_item(user_id: int, url: str, titulo: str,
                      descripcion: str = "", tipo: str = "video",
                      relevancia: int = 5, fecha_objetivo: str = None,
                      notas: str = "") -> int:
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            """INSERT INTO learning_items 
               (user_id, url, titulo, descripcion, tipo, 
                relevancia, fecha_objetivo, notas)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, url, titulo, descripcion, tipo,
             relevancia, fecha_objetivo, notas)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_learning_items(user_id: int, estado: str = None,
                       limit: int = 20) -> List[Dict]:
    conn = get_db_connection()
    try:
        if estado:
            rows = conn.execute(
                """SELECT * FROM learning_items
                   WHERE user_id = ? AND estado = ?
                   ORDER BY relevancia DESC, fecha_objetivo ASC
                   LIMIT ?""",
                (user_id, estado, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM learning_items
                   WHERE user_id = ?
                   ORDER BY relevancia DESC, fecha_objetivo ASC
                   LIMIT ?""",
                (user_id, limit)
            ).fetchall()
        return [dict(row) for row in rows] if rows else []
    except Exception as e:
        logger.error(f"Error obteniendo learning items: {e}")
        return []
    finally:
        conn.close()


def get_overdue_learning_items(user_id: int) -> List[Dict]:
    """Items pendientes con fecha_objetivo <= hoy."""
    conn = get_db_connection()
    try:
        from datetime import date
        today = date.today().isoformat()
        rows = conn.execute(
            """SELECT * FROM learning_items 
               WHERE user_id = ? 
               AND estado = 'pendiente'
               AND fecha_objetivo IS NOT NULL
               AND fecha_objetivo <= ?
               ORDER BY relevancia DESC""",
            (user_id, today)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def update_learning_item(item_id: int, user_id: int, **kwargs) -> bool:
    conn = get_db_connection()
    try:
        allowed = {'relevancia', 'fecha_objetivo', 'estado',
                   'notas', 'titulo', 'tipo'}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        set_clause = ", ".join(
            f"{k} = ?" for k in updates
        )
        set_clause += ", updated_at = CURRENT_TIMESTAMP"
        values = list(updates.values())
        values.extend([item_id, user_id])
        conn.execute(
            f"""UPDATE learning_items 
                SET {set_clause}
                WHERE id = ? AND user_id = ?""",
            values
        )
        conn.commit()
        return True
    finally:
        conn.close()


def complete_learning_item(item_id: int, user_id: int) -> bool:
    return update_learning_item(item_id, user_id, estado='completado')


def clear_history(user_id: int):
    conn = get_db_connection()
    try:
        conn.execute(
            "DELETE FROM conversations WHERE user_id = ?",
            (user_id,)
        )
        conn.commit()
        logger.info(f"Historial borrado para usuario {user_id}")
    finally:
        conn.close()
