"""Guardrails de seguridad: validación del SQL ANTES de ejecutarlo (Fase 2).

Esta es la capa de la APP en la defensa en profundidad. La barrera no-evitable es
el rol de base de datos de solo lectura; esta capa rechaza temprano (con un mensaje
para el log) y fuerza un LIMIT.

Reglas que aplica `validate_and_secure`:
1. Una sola sentencia (rechaza múltiples separadas por ';').
2. Solo SELECT o WITH ... SELECT (CTE). Cualquier otra cosa se rechaza.
3. Bloquea palabras clave de escritura/DDL/admin (INSERT, UPDATE, DELETE, DROP,
   ALTER, CREATE, TRUNCATE, GRANT, etc.) detectadas como *keywords* del parser
   (no como texto crudo), para no romper literales como `'please delete'`.
4. Quita comentarios (vector de smuggling) antes de validar.
5. Inyecta un LIMIT si la consulta no trae uno a nivel superior.

Función pública:
- `validate_and_secure(sql, max_limit=...)` -> SQL saneado, o lanza SQLValidationError.
"""

from __future__ import annotations

import logging

import sqlparse
from sqlparse import tokens as T

from config import settings

logger = logging.getLogger(__name__)


class SQLValidationError(Exception):
    """El SQL no pasó los guardrails de seguridad (no es un SELECT seguro)."""


# Palabras clave prohibidas: cualquier escritura, DDL o comando administrativo.
# Se comparan contra tokens que el parser marca como keyword (no contra el texto
# crudo), así un literal como 'please delete' NO dispara un falso positivo.
FORBIDDEN_KEYWORDS: frozenset[str] = frozenset(
    {
        "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
        "GRANT", "REVOKE", "MERGE", "REPLACE", "UPSERT", "CALL", "DO",
        "EXECUTE", "PREPARE", "DEALLOCATE", "COPY", "VACUUM", "ANALYZE",
        "REINDEX", "CLUSTER", "REFRESH", "LOCK", "SET", "RESET", "DISCARD",
        "LISTEN", "NOTIFY", "UNLISTEN", "COMMENT", "SECURITY", "IMPORT",
        "ATTACH", "DETACH", "INTO",  # SELECT ... INTO crea una tabla
    }
)

# Tipos de token que cuentan como "palabra clave" para el escaneo.
_KEYWORD_TTYPES = (
    T.Keyword,
    T.Keyword.DDL,
    T.Keyword.DML,
    T.Keyword.CTE,
)

# Primeras palabras permitidas para la sentencia.
_ALLOWED_FIRST = frozenset({"SELECT", "WITH"})


def validate_and_secure(sql: str, *, max_limit: int | None = None) -> str:
    """Valida que `sql` sea un SELECT seguro y le inyecta un LIMIT.

    Args:
        sql: SQL candidato (normalmente generado por el modelo).
        max_limit: tope de filas a forzar. Por defecto settings.query_row_hard_cap.

    Returns:
        El SQL saneado (sin comentarios, sin ';' final, con LIMIT garantizado).

    Raises:
        SQLValidationError: si el SQL viola cualquier regla de seguridad.
    """
    if max_limit is None:
        max_limit = settings.query_row_hard_cap

    if not sql or not sql.strip():
        raise SQLValidationError("El SQL está vacío.")

    # 0. Quitar comentarios (-- y /* */): neutraliza smuggling dentro de comentarios.
    cleaned = sqlparse.format(sql, strip_comments=True).strip()
    # Quitar ';' final (uno o varios) y espacios sobrantes.
    cleaned = cleaned.rstrip(";").strip()
    if not cleaned:
        raise SQLValidationError("El SQL quedó vacío tras limpiar comentarios.")

    # 1. Una sola sentencia.
    statements = [s for s in sqlparse.parse(cleaned) if str(s).strip()]
    if len(statements) != 1:
        raise SQLValidationError(
            f"Se permite una sola sentencia; se recibieron {len(statements)}."
        )
    stmt = statements[0]

    # 2. La primera palabra clave debe ser SELECT o WITH.
    first = stmt.token_first(skip_cm=True)
    if first is None:
        raise SQLValidationError("No se encontró una sentencia válida.")
    first_kw = first.normalized.upper()
    if first_kw not in _ALLOWED_FIRST:
        raise SQLValidationError(
            f"Solo se permiten consultas SELECT o WITH; empieza por '{first_kw}'."
        )

    # 3. Escanear todos los tokens hoja en busca de keywords prohibidas y de ';'.
    for token in stmt.flatten():
        if token.ttype is T.Punctuation and token.value == ";":
            raise SQLValidationError("Se detectó ';' (posible múltiple sentencia).")
        if token.ttype in _KEYWORD_TTYPES:
            word = token.normalized.upper()
            if word in FORBIDDEN_KEYWORDS:
                raise SQLValidationError(
                    f"Palabra clave no permitida en una consulta de solo lectura: "
                    f"'{word}'."
                )

    # 4. Garantizar un LIMIT a nivel superior.
    secured = _ensure_limit(cleaned, stmt, max_limit)
    logger.info("validate_sql: SQL aprobado (LIMIT<=%d garantizado).", max_limit)
    return secured


def _has_top_level_limit(stmt: sqlparse.sql.Statement) -> bool:
    """¿La sentencia tiene un LIMIT a nivel superior (no dentro de subconsultas)?"""
    for token in stmt.tokens:
        if token.ttype is T.Keyword and token.normalized.upper() == "LIMIT":
            return True
    return False


def _ensure_limit(sql: str, stmt: sqlparse.sql.Statement, max_limit: int) -> str:
    """Añade `LIMIT max_limit` si no hay un LIMIT a nivel superior.

    Se añade al final (no se envuelve en subconsulta) para no romper consultas con
    columnas duplicadas en SELECT *, UNION u ORDER BY. Si el modelo ya puso un
    LIMIT propio, se respeta (decisión v1; documentado en el PRD).
    """
    if _has_top_level_limit(stmt):
        return sql
    return f"{sql}\nLIMIT {int(max_limit)}"
