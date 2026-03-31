"""
Career Mentor Agent - Sistema de Logging
=========================================
Logging estructurado para el sistema.
"""

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logger(
    name: str,
    level: Optional[str] = None,
    log_file: Optional[str] = None
) -> logging.Logger:
    """
    Configura un logger con formato estructurado.

    Args:
        name: Nombre del logger
        level: Nivel de logging (DEBUG, INFO, WARNING, ERROR)
        log_file: Archivo de log opcional

    Returns:
        Logger configurado
    """
    logger = logging.getLogger(name)

    # Determinar nivel
    log_level = getattr(logging, (level or "INFO").upper())
    logger.setLevel(log_level)

    # Formato
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Handler de consola
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Handler de archivo si se especifica
    if log_file:
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)
        file_handler = logging.FileHandler(
            logs_dir / log_file,
            encoding="utf-8"
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


# Logger principal
logger = setup_logger("career_mentor")


class LogContext:
    """Contexto para logging con datos adicionales."""

    def __init__(self, user_id: Optional[str] = None, agent: Optional[str] = None):
        self.user_id = user_id
        self.agent = agent
        self.extra = {}

    def log(self, level: str, message: str, **kwargs):
        """Log con contexto adicional."""
        extra_data = {
            "user_id": self.user_id,
            "agent": self.agent,
            **self.extra,
            **kwargs
        }
        extra_str = " | ".join(f"{k}={v}" for k, v in extra_data.items() if v)
        full_message = f"{message} | {extra_str}" if extra_str else message

        log_method = getattr(logger, level.lower())
        log_method(full_message)


def get_logger(name: str) -> logging.Logger:
    """Obtiene un logger para un modulo especifico."""
    return logging.getLogger(f"career_mentor.{name}")


# Loggers especificos por modulo
db_logger = get_logger("database")
bot_logger = get_logger("bot")
service_logger = get_logger("services")
