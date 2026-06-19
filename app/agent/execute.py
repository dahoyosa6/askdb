"""Ejecución de consultas en modo SOLO LECTURA (Fase 1, versión mínima).

Capa de ejecución del pipeline: recibe SQL ya generado y lo corre contra Neon
Postgres con el rol read-only, dentro de una transacción acorazada:
- `SET LOCAL statement_timeout` para que ninguna consulta cuelgue el sistema.
- `SET TRANSACTION READ ONLY` como cinturón extra (además del rol de DB).

Usa un pool de conexiones (psycopg_pool) creado de forma perezosa (singleton),
para no abrir/cerrar una conexión por consulta.

NOTA (alcance Fase 1): aquí NO hay validación de guardrails (validate_sql) ni
auto-corrección. Eso es Fase 2-3. Este módulo solo ejecuta y reporta errores.

Funciones públicas:
- `run_query(sql)` -> (columnas, filas).
- `get_pool()` -> el pool singleton (uso interno/avanzado).
- `close_pool()` -> cierra el pool (útil en tests o apagado limpio).
"""

from __future__ import annotations

import logging

from psycopg_pool import ConnectionPool

from config import settings

logger = logging.getLogger(__name__)

# Pool singleton perezoso. Se crea en el primer uso y se reutiliza.
_POOL: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    """Devuelve el pool de conexiones, creándolo en el primer uso (singleton)."""
    global _POOL
    if _POOL is None:
        if not settings.database_url:
            raise RuntimeError(
                "Falta DATABASE_URL en el entorno (.env). No se puede crear el "
                "pool de conexiones a la base de datos."
            )
        logger.info(
            "Creando pool de conexiones (min=%d, max=%d).",
            settings.db_pool_min,
            settings.db_pool_max,
        )
        _POOL = ConnectionPool(
            conninfo=settings.database_url,
            min_size=settings.db_pool_min,
            max_size=settings.db_pool_max,
            open=True,
        )
    return _POOL


def close_pool() -> None:
    """Cierra el pool si está abierto. Idempotente."""
    global _POOL
    if _POOL is not None:
        logger.info("Cerrando pool de conexiones.")
        _POOL.close()
        _POOL = None


def run_query(sql: str) -> tuple[list[str], list[tuple]]:
    """Ejecuta `sql` en modo solo lectura y devuelve (columnas, filas).

    Abre una transacción con statement_timeout y READ ONLY, ejecuta la consulta,
    y devuelve los nombres de columna y las filas. No silencia errores: cualquier
    fallo de Postgres (sintaxis, permisos, timeout) se loguea y se re-lanza para
    que el llamador decida qué hacer (en Fase 3, auto-corregir).

    Returns:
        (columns, rows): lista de nombres de columna y lista de tuplas de filas.
    """
    timeout_ms = settings.db_statement_timeout_ms
    pool = get_pool()

    with pool.connection() as conn:
        try:
            with conn.cursor() as cur:
                # SET LOCAL aplica solo a esta transacción. READ ONLY rechaza
                # cualquier escritura aunque el SQL la intentara (cinturón extra
                # sobre el rol de DB).
                cur.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
                cur.execute("SET TRANSACTION READ ONLY")

                cur.execute(sql)

                # cur.description es None para sentencias sin resultado; aquí
                # esperamos siempre un SELECT, pero lo manejamos con cuidado.
                columns = [desc.name for desc in cur.description] if cur.description else []
                rows = cur.fetchall() if cur.description else []

            logger.info(
                "run_query: %d fila(s), %d columna(s).", len(rows), len(columns)
            )
            return columns, rows
        except Exception as exc:
            # Importante: rollback explícito para no dejar la conexión en estado
            # de error al devolverla al pool.
            conn.rollback()
            logger.error("run_query: error ejecutando SQL: %s", exc)
            raise
