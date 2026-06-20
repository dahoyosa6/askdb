"""Ejecución de consultas en modo SOLO LECTURA + orquestación del pipeline.

Capa de ejecución del pipeline. Tiene dos responsabilidades:

1. `run_query(sql)`: corre SQL ya generado contra Neon Postgres con el rol
   read-only, dentro de una transacción acorazada:
   - `SET LOCAL statement_timeout` para que ninguna consulta cuelgue el sistema.
   - `SET TRANSACTION READ ONLY` como cinturón extra (además del rol de DB).
   Usa un pool de conexiones (psycopg_pool) perezoso (singleton), para no
   abrir/cerrar una conexión por consulta.

2. `answer_question(question, ...)` (Fase 3): orquesta el pipeline completo
   generar SQL -> validar -> ejecutar, con **auto-corrección**: si un intento
   falla (error de Postgres o de validación), pasa el error saneado al modelo y
   reintenta, hasta `settings.max_sql_retries` intentos de generación en total.

Funciones públicas:
- `answer_question(question, chat_id=None, *, client=None)` -> AnswerResult.
- `run_query(sql)` -> (columnas, filas).
- `get_pool()` -> el pool singleton (uso interno/avanzado).
- `close_pool()` -> cierra el pool (útil en tests o apagado limpio).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import anthropic
import psycopg
from psycopg_pool import ConnectionPool

from config import settings

# Se importan a nivel de módulo (no dentro de la función) a propósito: así los
# tests pueden monkeypatchear `app.agent.execute.generate_sql`,
# `app.agent.execute.validate_and_secure` y `app.agent.execute.run_query` para
# probar la orquestación sin tocar la red ni la base de datos real.
from app.agent import memory
from app.agent.generate_sql import generate_sql, get_client
from app.agent.glossary import get_glossary
from app.agent.schema import get_schema
from app.agent.validate_sql import SQLValidationError, validate_and_secure

logger = logging.getLogger(__name__)

# Mensaje único y saneado para el usuario cuando se agotan los intentos. NUNCA
# debe incluir SQL crudo, el error interno de Postgres ni un stacktrace: esos
# detalles solo van al log del lado servidor (regla dura del proyecto).
_MENSAJE_FALLO = (
    "No pude responder esa pregunta con los datos disponibles. "
    "Intenta reformularla de otra manera o sé más específico."
)

# Mensaje específico cuando el servicio de IA está saturado o no responde
# (429/timeout/caída de red). Sigue siendo saneado: no expone detalles internos.
_MENSAJE_SATURADO = (
    "El servicio está saturado en este momento. Intenta de nuevo en un momento."
)

# Errores RECUPERABLES dentro del loop de auto-corrección: además de los de
# validación (app) y los de Postgres (DB), un `RuntimeError` de `generate_sql`
# (el modelo no devolvió un bloque tool_use válido) y toda la jerarquía de errores
# del SDK de Anthropic (`anthropic.APIError` cubre RateLimit, APIConnection,
# APIStatus, APITimeout, etc.). NUNCA se propagan al llamador: o se reintenta, o
# se devuelve `ok=False` con un mensaje saneado.
_ERRORES_RECUPERABLES = (
    SQLValidationError,
    psycopg.Error,
    RuntimeError,
    anthropic.APIError,
)

# Errores de la API de Anthropic que indican saturación/indisponibilidad temporal
# (no un fallo del SQL): merecen el mensaje "saturado" en vez del genérico.
_ERRORES_SATURACION = (
    anthropic.RateLimitError,
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
    anthropic.OverloadedError,
)

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
            # Neon free PAUSA la base por inactividad: tras despertar, las
            # conexiones del pool pueden quedar muertas. `check` valida (y recicla
            # si hace falta) cada conexión al sacarla, para que el "primer mensaje
            # tras inactividad" no falle con una conexión zombi. `max_idle` corto
            # cierra las conexiones ociosas antes de que Neon las mate.
            check=ConnectionPool.check_connection,
            max_idle=120.0,
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
                #
                # Límite conocido (v2): tipos exóticos de Postgres (arrays, JSON,
                # bytea, rangos) llegan como objetos Python que el router renderiza
                # con str() y pueden verse feos (p. ej. bytea -> "b'\\x...'"), o no
                # graficarse. Northwind no los usa; al conectar datos reales del
                # cliente habrá que darles un formato amable.
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


@dataclass
class AnswerResult:
    """Resultado del pipeline completo de `answer_question`.

    Permite al llamador (CLI, bot) decidir qué mostrar: si `ok` es True, imprime
    `sql` + la tabla (`columns`/`rows`); si es False, muestra `error_message`
    (texto saneado para el usuario, sin SQL ni error interno).

    Atributos:
        ok: True si una consulta se ejecutó con éxito; False si se agotaron los
            intentos.
        columns: nombres de columna del resultado (vacío si falló).
        rows: filas del resultado (vacío si falló).
        sql: el SQL final que se ejecutó con éxito; None si falló.
        attempts: cuántos intentos de generación se hicieron (1..max_sql_retries).
        error_message: mensaje saneado para el usuario cuando ok=False; None si ok.
    """

    ok: bool
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    sql: str | None = None
    attempts: int = 0
    error_message: str | None = None


def _sanear_error(exc: Exception) -> str:
    """Convierte una excepción en un texto corto y legible para el feedback al modelo.

    Devuelve `str(exc)` recortado (nunca un stacktrace). Este texto se usa SOLO
    como `error_feedback` para que Claude auto-corrija; no se muestra al usuario
    final (al usuario solo le llega `_MENSAJE_FALLO`).
    """
    texto = str(exc).strip()
    # Recorte defensivo: el error de Postgres rara vez excede esto, pero evita
    # inflar el prompt y arrastrar contexto innecesario.
    return texto[:500] if texto else exc.__class__.__name__


def answer_question(
    question: str,
    chat_id: int | None = None,
    *,
    client: "object | None" = None,
) -> AnswerResult:
    """Orquesta el pipeline completo con auto-corrección (Fase 3).

    Flujo por intento: generar SQL -> validar -> ejecutar. Si un intento falla
    (por `SQLValidationError` de la app o por `psycopg.Error` de Postgres), se
    sanea el texto del error y se pasa como `error_feedback` a `generate_sql` en
    el siguiente intento, para que el modelo corrija.

    Tope de intentos: el total de intentos de GENERACIÓN está acotado por
    `settings.max_sql_retries` (=3). Se interpreta como **máximo 3 intentos de
    generación en total, incluyendo el primero**, de modo que el agente
    "converge en <=3". No es "1 intento + 3 reintentos": es 3 en total.

    Seguridad: si se agotan los intentos, se devuelve un `AnswerResult` con
    `ok=False` y un `error_message` claro en español, SIN stacktrace, SIN SQL
    crudo y SIN el error interno de Postgres. El error real sí se loguea del lado
    servidor (regla dura del proyecto).

    Args:
        question: pregunta del usuario en lenguaje natural.
        chat_id: identifica la conversación. Si se pasa, se activa la memoria
            conversacional corta (Fase 5): el historial del chat se inyecta al
            modelo en cada intento y, si la consulta tiene éxito, el turno
            (pregunta + SQL ejecutado) se guarda en memoria. Si es None, no se
            usa ni se actualiza memoria.
        client: cliente Anthropic ya creado (útil en tests para inyectarlo). Si
            es None, se crea con `get_client()`.

    Returns:
        AnswerResult con el resultado o el mensaje de fallo saneado.
    """
    # Memoria conversacional (Fase 5): si hay chat_id, recuperamos el historial
    # del turno previo para inyectarlo al modelo. Es el MISMO en cada reintento
    # del turno actual (el error_feedback, en cambio, es propio de cada intento).
    history = memory.get_history(chat_id) if chat_id is not None else None

    schema = get_schema()
    glossary = get_glossary()
    if client is None:
        client = get_client()

    max_intentos = settings.max_sql_retries
    error_feedback: str | None = None
    # Mensaje saneado a devolver si se agotan los intentos. Por defecto el
    # genérico; un error de saturación de la API lo cambia al específico.
    mensaje_fallo = _MENSAJE_FALLO

    for intento in range(1, max_intentos + 1):
        try:
            # 1. Generar SQL (con el feedback del error previo si lo hubo).
            sql = generate_sql(
                client,
                question,
                schema,
                glossary,
                history=history,
                error_feedback=error_feedback,
            )
            # 2. Guardrails de seguridad (solo SELECT, una sentencia, LIMIT).
            safe_sql = validate_and_secure(sql)
            # 3. Ejecutar en modo solo lectura.
            columns, rows = run_query(safe_sql)
        except _ERRORES_RECUPERABLES as exc:
            # Fallo recuperable: lo logueamos del lado servidor y preparamos el
            # feedback saneado para que el siguiente intento corrija. Cubre tanto
            # errores del SQL (validación/Postgres) como fallos de la API de IA
            # (Anthropic) o un tool_use ausente (RuntimeError de generate_sql).
            # NUNCA se propaga: la regla dura es que un 429/timeout/5xx de la API
            # no tumbe el turno ni reviente el CLI.
            error_feedback = _sanear_error(exc)
            # Para errores de saturación de la API guardamos su request_id (si lo
            # expone el SDK) para observabilidad, y recordamos el mensaje "saturado".
            extra = ""
            if isinstance(exc, _ERRORES_SATURACION):
                mensaje_fallo = _MENSAJE_SATURADO
                request_id = getattr(exc, "_request_id", None)
                if request_id:
                    extra = f" [request_id={request_id}]"
            elif isinstance(exc, anthropic.APIError):
                # Otros errores del SDK (4xx no recuperables, validación, etc.):
                # también logueamos el request_id para soporte.
                request_id = getattr(exc, "_request_id", None)
                if request_id:
                    extra = f" [request_id={request_id}]"
            logger.warning(
                "answer_question: intento %d/%d falló (%s): %s%s",
                intento,
                max_intentos,
                exc.__class__.__name__,
                error_feedback,
                extra,
            )
            continue

        # Éxito: devolvemos el resultado con el número de intento alcanzado.
        logger.info(
            "answer_question: éxito en el intento %d/%d.", intento, max_intentos
        )
        # Memoria (Fase 5): guardamos el turno SOLO en éxito, con el SQL ya
        # securizado (el que de verdad se ejecutó), no el crudo del modelo. En el
        # camino de fallo (ok=False) NO se guarda nada.
        if chat_id is not None:
            memory.append_turn(chat_id, question, safe_sql)
        return AnswerResult(
            ok=True,
            columns=columns,
            rows=rows,
            sql=safe_sql,
            attempts=intento,
        )

    # Se agotaron todos los intentos: fallo controlado, mensaje saneado.
    logger.error(
        "answer_question: agotados los %d intentos sin una consulta válida.",
        max_intentos,
    )
    return AnswerResult(
        ok=False,
        attempts=max_intentos,
        error_message=mensaje_fallo,
    )
