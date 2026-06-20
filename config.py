"""Zona única de mantenimiento de AskDB.

Todas las constantes configurables del proyecto viven aquí. Nada de valores
mágicos dispersos por el código. Los secretos y los valores que cambian por
entorno se leen de variables de entorno (.env en local; variables del servicio
en Railway).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()  # carga .env en local; en producción las vars ya están en el entorno


def _get(name: str, default: str | None = None, *, required: bool = False) -> str:
    """Lee una variable de entorno. Si es requerida y falta, lanza error claro."""
    value = os.getenv(name, default)
    if required and (value is None or value == ""):
        raise RuntimeError(
            f"Falta la variable de entorno obligatoria: {name}. "
            f"Revisa tu archivo .env (usa .env.example como plantilla)."
        )
    return value  # type: ignore[return-value]


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


def _get_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def _get_chat_ids(name: str) -> list[int]:
    raw = os.getenv(name, "")
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    # --- Anthropic ---
    anthropic_api_key: str = field(default_factory=lambda: _get("ANTHROPIC_API_KEY", required=False))
    anthropic_model: str = field(default_factory=lambda: _get("ANTHROPIC_MODEL", "claude-sonnet-4-6"))
    anthropic_max_tokens: int = field(default_factory=lambda: _get_int("ANTHROPIC_MAX_TOKENS", 2048))

    # --- Base de datos (rol read-only) ---
    database_url: str = field(default_factory=lambda: _get("DATABASE_URL", required=False))
    db_statement_timeout_ms: int = field(default_factory=lambda: _get_int("DB_STATEMENT_TIMEOUT_MS", 8000))
    db_pool_min: int = field(default_factory=lambda: _get_int("DB_POOL_MIN", 1))
    db_pool_max: int = field(default_factory=lambda: _get_int("DB_POOL_MAX", 5))

    # --- Comportamiento del agente ---
    query_row_hard_cap: int = field(default_factory=lambda: _get_int("QUERY_ROW_HARD_CAP", 1000))
    max_sql_retries: int = field(default_factory=lambda: _get_int("MAX_SQL_RETRIES", 3))
    memory_window: int = field(default_factory=lambda: _get_int("MEMORY_WINDOW", 6))
    rate_limit_per_min: int = field(default_factory=lambda: _get_int("RATE_LIMIT_PER_MIN", 10))
    # Duración máxima de una nota de voz (segundos). Más larga se rechaza (Fase 7).
    max_voice_duration_s: int = field(default_factory=lambda: _get_int("MAX_VOICE_DURATION_S", 120))

    # --- Telegram ---
    telegram_bot_token: str = field(default_factory=lambda: _get("TELEGRAM_BOT_TOKEN", ""))
    allowed_chat_ids: list[int] = field(default_factory=lambda: _get_chat_ids("ALLOWED_CHAT_IDS"))
    telegram_use_webhook: bool = field(default_factory=lambda: _get_bool("TELEGRAM_USE_WEBHOOK", False))
    webhook_url: str = field(default_factory=lambda: _get("WEBHOOK_URL", ""))
    webhook_secret: str = field(default_factory=lambda: _get("WEBHOOK_SECRET", ""))

    # --- Groq (voz) ---
    groq_api_key: str = field(default_factory=lambda: _get("GROQ_API_KEY", ""))
    groq_whisper_model: str = field(default_factory=lambda: _get("GROQ_WHISPER_MODEL", "whisper-large-v3"))

    # --- Salidas / logging ---
    output_dir: str = field(default_factory=lambda: _get("OUTPUT_DIR", "outputs"))
    chart_max_rows: int = field(default_factory=lambda: _get_int("CHART_MAX_ROWS", 50))
    table_max_rows_text: int = field(default_factory=lambda: _get_int("TABLE_MAX_ROWS_TEXT", 20))
    # Decimales con que se muestran montos (float/Decimal) en la salida de TEXTO.
    text_decimals: int = field(default_factory=lambda: _get_int("TEXT_DECIMALS", 2))
    schema_cache_path: str = field(default_factory=lambda: _get("SCHEMA_CACHE_PATH", "db/schema_cache.json"))
    log_level: str = field(default_factory=lambda: _get("LOG_LEVEL", "INFO"))


settings = Settings()
