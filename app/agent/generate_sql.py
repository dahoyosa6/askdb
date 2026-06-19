"""Generación de SQL con Claude usando tool_use forzado.

El modelo NO responde texto libre: lo obligamos a llamar la herramienta
`emit_sql` (vía `tool_choice`), así devuelve SQL estructurado y limpio, sin
markdown ni preámbulo. El bloque de sistema (esquema + glosario, estable) lleva
`cache_control` ephemeral para aprovechar el prompt caching de Claude.

Funciones públicas:
- `get_client()` -> crea el cliente Anthropic con la API key del config.
- `build_system_prompt(schema, glossary)` -> bloques de sistema (con cache).
- `generate_sql(client, question, schema, glossary, ...)` -> string SQL.

Modelo: claude-sonnet-4-6 (definido en config.settings.anthropic_model).
"""

from __future__ import annotations

import logging
from typing import Any

import anthropic

from config import settings

logger = logging.getLogger(__name__)

# Definición de la herramienta que el modelo está OBLIGADO a llamar. El esquema
# de entrada exige `sql`; `rationale` es opcional (lo ignoramos en runtime pero
# ayuda al modelo a estructurar su respuesta).
EMIT_SQL_TOOL: dict[str, Any] = {
    "name": "emit_sql",
    "description": (
        "Emite la consulta SQL (PostgreSQL, solo lectura) que responde la "
        "pregunta del usuario. Una sola sentencia SELECT o WITH."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": (
                    "La consulta SQL completa, lista para ejecutar. Solo SELECT "
                    "o WITH (CTE). Dialecto PostgreSQL. Sin punto y coma final "
                    "obligatorio, sin markdown, sin comentarios de cierre."
                ),
            },
            "rationale": {
                "type": "string",
                "description": "Explicación breve de cómo la consulta responde la pregunta.",
            },
        },
        "required": ["sql"],
    },
}


def get_client() -> anthropic.Anthropic:
    """Crea el cliente Anthropic con la API key del config.

    Lanza un error claro si la API key no está configurada, en vez de fallar más
    adelante con un mensaje opaco de autenticación.
    """
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "Falta ANTHROPIC_API_KEY en el entorno (.env). No se puede crear el "
            "cliente de Anthropic."
        )
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def build_system_prompt(schema: str, glossary: str) -> list[dict[str, Any]]:
    """Construye el prompt de sistema como lista de bloques de texto.

    El esquema y el glosario son estables (Northwind no cambia), así que el
    último bloque lleva `cache_control: ephemeral` para que Claude cachee todo
    el prefijo y abarate las llamadas repetidas.

    Devuelve una lista de bloques apta para el parámetro `system` de la API.
    """
    instructions = (
        "Eres un generador de SQL para PostgreSQL en modo SOLO LECTURA. "
        "Tu única tarea es traducir la pregunta del usuario (en español) a una "
        "consulta SQL correcta sobre la base de datos Northwind, y emitirla "
        "llamando la herramienta `emit_sql`.\n\n"
        "REGLAS DURAS (obligatorias):\n"
        "1. SOLO lectura: genera únicamente sentencias SELECT o WITH (CTE). "
        "Nunca INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE ni ninguna "
        "otra forma de escritura o DDL.\n"
        "2. Una sola sentencia. Sin múltiples consultas separadas por ';'.\n"
        "3. Dialecto PostgreSQL.\n"
        "4. Usa los nombres de tabla y columna EXACTAMENTE como aparecen en el "
        "esquema (en minúscula, snake_case). No inventes tablas ni columnas.\n"
        "5. Apóyate en el glosario de negocio para interpretar términos como "
        "'ventas', 'facturación' o 'mejor cliente'.\n"
        "6. Si una pregunta no se puede responder con una consulta de solo "
        "lectura sobre este esquema, emite igualmente el SELECT más cercano y "
        "razonable; no expliques fuera de la herramienta.\n"
    )

    schema_block = f"ESQUEMA DE LA BASE DE DATOS (Northwind):\n{schema}"
    glossary_block = glossary

    # Tres bloques en orden estable. El cache_control va en el último para que el
    # prefijo completo (instrucciones + esquema + glosario) quede cacheado.
    return [
        {"type": "text", "text": instructions},
        {"type": "text", "text": schema_block},
        {
            "type": "text",
            "text": glossary_block,
            "cache_control": {"type": "ephemeral"},
        },
    ]


def _build_messages(
    question: str,
    history: list[dict[str, Any]] | None,
    error_feedback: str | None,
) -> list[dict[str, Any]]:
    """Arma la lista de mensajes (historial + pregunta + feedback de error)."""
    messages: list[dict[str, Any]] = []

    if history:
        # El historial se asume ya en formato de mensajes de la API
        # ({"role": ..., "content": ...}). Lo copiamos tal cual.
        messages.extend(history)

    messages.append({"role": "user", "content": question})

    if error_feedback:
        # Turno adicional para auto-corrección: le contamos al modelo qué error
        # devolvió Postgres para que reintente. (Fase 1 no lo usa todavía, pero
        # generate_sql lo soporta para la Fase 3.)
        messages.append(
            {
                "role": "user",
                "content": (
                    "La consulta anterior falló al ejecutarse. Error de "
                    f"PostgreSQL:\n{error_feedback}\n\n"
                    "Corrige el SQL y vuelve a emitirlo con la herramienta "
                    "`emit_sql`."
                ),
            }
        )

    return messages


def generate_sql(
    client: anthropic.Anthropic,
    question: str,
    schema: str,
    glossary: str,
    history: list[dict[str, Any]] | None = None,
    *,
    error_feedback: str | None = None,
    model: str | None = None,
) -> str:
    """Genera SQL para `question` usando Claude con tool_use forzado.

    Args:
        client: cliente Anthropic (de `get_client()`).
        question: pregunta del usuario en lenguaje natural.
        schema: esquema formateado (de `get_schema()`).
        glossary: glosario de negocio (de `get_glossary()`).
        history: mensajes previos (memoria conversacional). Opcional.
        error_feedback: si se pasa, añade un turno con el error de Postgres para
            que el modelo auto-corrija. Opcional (Fase 3).
        model: override del modelo; por defecto usa settings.anthropic_model.

    Returns:
        El string SQL extraído del bloque tool_use `emit_sql`.

    Raises:
        RuntimeError: si la respuesta no contiene un bloque tool_use válido con
            la clave `sql`.
    """
    system = build_system_prompt(schema, glossary)
    messages = _build_messages(question, history, error_feedback)
    used_model = model or settings.anthropic_model

    logger.info("generate_sql: solicitando SQL al modelo %s.", used_model)

    response = client.messages.create(
        model=used_model,
        max_tokens=settings.anthropic_max_tokens,
        system=system,
        messages=messages,
        tools=[EMIT_SQL_TOOL],
        # tool_choice forzado: el modelo DEBE llamar emit_sql.
        tool_choice={"type": "tool", "name": "emit_sql"},
    )

    # Extraer el SQL del primer bloque tool_use llamado `emit_sql`.
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "emit_sql":
            sql = block.input.get("sql")
            if not sql or not isinstance(sql, str):
                raise RuntimeError(
                    "El modelo llamó emit_sql pero no devolvió un 'sql' válido. "
                    f"Input recibido: {block.input!r}"
                )
            logger.info("generate_sql: SQL generado (%d caracteres).", len(sql))
            return sql.strip()

    # Si llegamos aquí, el modelo no usó la herramienta como se le forzó.
    stop_reason = getattr(response, "stop_reason", None)
    raise RuntimeError(
        "El modelo no devolvió un bloque tool_use 'emit_sql'. "
        f"stop_reason={stop_reason!r}."
    )
