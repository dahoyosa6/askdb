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
5. Bloquea por NOMBRE las funciones peligrosas de lectura de archivos / IO de red
   (defensa en profundidad — ver `FORBIDDEN_FUNCTIONS`).
6. Inyecta un LIMIT si la consulta no trae uno a nivel superior.

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

# Funciones peligrosas bloqueadas por NOMBRE (defensa en profundidad).
#
# Estas funciones NO modifican datos (no violan la garantía read-only), pero leen
# archivos del servidor o hacen IO de red. Hoy las corta el rol de DB read-only
# (verificado en vivo: rebotan con InsufficientPrivilege). Esta denylist convierte
# la APP en una SEGUNDA barrera real, para el día en que se conecte a una DB de
# cliente con un rol más permisivo. Se detecta el nombre como token de FUNCIÓN
# (un Name seguido de '('), insensible a mayúsculas; un mismo nombre dentro de un
# literal o como identificador suelto NO dispara (no es una llamada).
#
# NOTA: `COPY` y `pg_sleep` no están aquí: COPY ya se bloquea como keyword;
# pg_sleep se mitiga con statement_timeout (decisión documentada). `pg_shadow` es
# una VISTA (no función) y la corta el rol DB.
FORBIDDEN_FUNCTIONS: frozenset[str] = frozenset(
    {
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "lo_import",
        "lo_export",
        "dblink",
    }
)

# Tipos de token que cuentan como "palabra clave" para el escaneo.
_KEYWORD_TTYPES = (
    T.Keyword,
    T.Keyword.DDL,
    T.Keyword.DML,
    T.Keyword.CTE,
)

# Tipos de token que pueden NOMBRAR una función al ir seguidos de '('.
# - `T.Name`: identificador sin comillas (`pg_read_file(...)`).
# - `T.Literal.String.Symbol`: identificador citado con comillas dobles
#   (`"pg_read_file"(...)`), forma válida en Postgres que sqlparse NO marca como
#   Name. Sin incluirlo, una función citada evadía la denylist (hallazgo B5-NEW).
_FUNCTION_NAME_TTYPES = (
    T.Name,
    T.Literal.String.Symbol,
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
    #    De paso, recogemos los tokens no-espacio para detectar llamadas a
    #    funciones peligrosas (un Name seguido de '(').
    tokens_significativos = []
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
        if not token.is_whitespace:
            tokens_significativos.append(token)

    # 3b. Denylist de funciones peligrosas por nombre (defensa en profundidad).
    #     Una llamada a función es un identificador seguido (sin espacios, ya
    #     filtrados) de un '('. El identificador puede ir SIN comillas (`T.Name`,
    #     p.ej. pg_read_file) o entre comillas dobles (`String.Symbol`, p.ej.
    #     "pg_read_file"), ambas válidas en Postgres. Se normaliza quitando las
    #     comillas dobles y se compara en minúsculas (en Postgres el nombre citado
    #     es case-sensitive, pero por seguridad bloqueamos igual cualquier casing).
    #     Para esquema calificado (`"pg_catalog"."pg_read_file"(...)`), el token
    #     que precede al '(' es el nombre de la función, que es lo que importa.
    #     Un literal 'pg_read_file ...' o un identificador citado que NO va seguido
    #     de '(' (p.ej. columna "pg_read_file_log" FROM t) NO disparan.
    for actual, siguiente in zip(tokens_significativos, tokens_significativos[1:]):
        if actual.ttype in _FUNCTION_NAME_TTYPES and (
            siguiente.ttype is T.Punctuation and siguiente.value == "("
        ):
            nombre = actual.value.strip('"').lower()
            if nombre in FORBIDDEN_FUNCTIONS:
                raise SQLValidationError(
                    f"Función no permitida (lectura de archivos / IO de red): "
                    f"'{nombre}'."
                )

    # 4. Garantizar un LIMIT a nivel superior.
    secured = _ensure_limit(cleaned, stmt, max_limit)
    logger.info("validate_sql: SQL aprobado (LIMIT<=%d garantizado).", max_limit)
    return secured


def _has_top_level_limit(stmt: sqlparse.sql.Statement) -> bool:
    """¿La sentencia ya acota cuántas filas devuelve a nivel superior?

    Detecta tanto `LIMIT` como `FETCH FIRST/NEXT n ROWS ONLY` (sintaxis SQL
    estándar válida en Postgres). Si no se detectara el `FETCH`, se inyectaría un
    `LIMIT` tras él y el SQL resultante sería inválido (M3). Se mira solo el nivel
    superior, no dentro de subconsultas.
    """
    for token in stmt.tokens:
        if token.ttype is T.Keyword and token.normalized.upper() in ("LIMIT", "FETCH"):
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
