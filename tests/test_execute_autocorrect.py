"""Pruebas del loop de auto-corrección de `answer_question` (Fase 3).

Anthropic y la base de datos están MOCKEADOS: no se toca la red ni la DB real.
Se monkeypatchean a nivel del módulo `app.agent.execute` las tres piezas del
pipeline (`generate_sql`, `validate_and_secure`, `run_query`) y el `client` se
inyecta como objeto centinela (answer_question no lo usa cuando todo está
monkeypatcheado, pero comprobamos que no se crea uno real).

Verifican:
- Caso feliz: 1er SQL válido -> ok=True, attempts=1, sin error_feedback.
- Auto-corrección por error de Postgres -> converge -> ok=True, y el 2º
  generate_sql recibió el error como feedback.
- Auto-corrección por SQLValidationError -> converge.
- Agotar reintentos -> ok=False, attempts==max_sql_retries, mensaje SIN el error
  crudo de Postgres, SIN SQL crudo y SIN "Traceback".
"""

from __future__ import annotations

import anthropic
import httpx
import psycopg
import pytest

import app.agent.execute as execute
from app.agent.execute import answer_question
from app.agent.validate_sql import SQLValidationError
from config import settings


def _rate_limit_error(request_id: str | None = None) -> anthropic.RateLimitError:
    """Construye un RateLimitError del SDK de Anthropic (con request_id opcional)."""
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    headers = {"request-id": request_id} if request_id else {}
    resp = httpx.Response(429, request=req, headers=headers)
    return anthropic.RateLimitError("rate limited", response=resp, body=None)

# Objeto centinela: representa el cliente Anthropic. Como generate_sql está
# monkeypatcheado, su valor real da igual; sirve para evitar get_client().
SENTINEL_CLIENT = object()


@pytest.fixture(autouse=True)
def _stub_schema_y_glossary(monkeypatch):
    """Evita que answer_question introspeccione la DB o lea el glosario real."""
    monkeypatch.setattr(execute, "get_schema", lambda: "ESQUEMA FALSO")
    monkeypatch.setattr(execute, "get_glossary", lambda: "GLOSARIO FALSO")


class _GenerateSpy:
    """Sustituto de generate_sql que devuelve SQL guionado y captura los kwargs.

    `sqls` es la lista de SQL a devolver por intento (uno por llamada). Guarda en
    `feedbacks` el valor de `error_feedback` recibido en cada llamada, para poder
    afirmar que la auto-corrección le pasó el error al modelo.
    """

    def __init__(self, sqls: list[str]) -> None:
        self._sqls = sqls
        self.feedbacks: list[str | None] = []
        self.histories: list = []
        self.calls = 0

    def __call__(self, client, question, schema, glossary, history=None, *, error_feedback=None):
        self.histories.append(history)
        self.feedbacks.append(error_feedback)
        sql = self._sqls[self.calls]
        self.calls += 1
        return sql


def _fake_run_query_ok(sql):
    """run_query exitoso: devuelve columnas y filas fijas."""
    return (["total"], [(830,)])


def test_caso_feliz_primer_intento(monkeypatch):
    """1er SQL válido -> ok=True, attempts=1, sin error_feedback en la llamada."""
    spy = _GenerateSpy(["SELECT count(*) AS total FROM orders"])
    monkeypatch.setattr(execute, "generate_sql", spy)
    monkeypatch.setattr(execute, "validate_and_secure", lambda sql: sql)
    monkeypatch.setattr(execute, "run_query", _fake_run_query_ok)

    result = answer_question("¿cuántos pedidos hay?", client=SENTINEL_CLIENT)

    assert result.ok is True
    assert result.attempts == 1
    assert result.columns == ["total"]
    assert result.rows == [(830,)]
    assert result.sql == "SELECT count(*) AS total FROM orders"
    assert result.error_message is None
    # Con éxito al primer intento NO se llama a generate_sql con error_feedback.
    assert spy.calls == 1
    assert spy.feedbacks == [None]


def test_autocorreccion_converge_tras_error_postgres(monkeypatch):
    """1er SQL provoca psycopg.Error; el 2º converge y recibió el feedback."""
    spy = _GenerateSpy(
        [
            "SELECT * FROM orders WHERE no_existe = 1",  # rompe en run_query
            "SELECT count(*) AS total FROM orders",  # válido
        ]
    )
    monkeypatch.setattr(execute, "generate_sql", spy)
    monkeypatch.setattr(execute, "validate_and_secure", lambda sql: sql)

    error_pg = 'column "no_existe" does not exist'

    def fake_run_query(sql):
        if "no_existe" in sql:
            raise psycopg.errors.UndefinedColumn(error_pg)
        return (["total"], [(830,)])

    monkeypatch.setattr(execute, "run_query", fake_run_query)

    result = answer_question("¿cuántos pedidos?", client=SENTINEL_CLIENT)

    assert result.ok is True
    assert result.attempts == 2
    assert result.attempts <= settings.max_sql_retries
    assert result.sql == "SELECT count(*) AS total FROM orders"
    # El 1er intento no llevó feedback; el 2º recibió el texto del error de PG.
    assert spy.feedbacks[0] is None
    assert spy.feedbacks[1] is not None
    assert "no_existe" in spy.feedbacks[1]


def test_autocorreccion_converge_tras_validation_error(monkeypatch):
    """1er SQL rechazado por los guardrails; el 2º pasa y converge."""
    spy = _GenerateSpy(
        [
            "SELECT * FROM orders; DROP TABLE orders",  # rechazado por validador
            "SELECT count(*) AS total FROM orders",  # válido
        ]
    )
    monkeypatch.setattr(execute, "generate_sql", spy)

    def fake_validate(sql):
        if "DROP" in sql:
            raise SQLValidationError("Palabra clave no permitida: 'DROP'.")
        return sql

    monkeypatch.setattr(execute, "validate_and_secure", fake_validate)
    monkeypatch.setattr(execute, "run_query", _fake_run_query_ok)

    result = answer_question("borra todo", client=SENTINEL_CLIENT)

    assert result.ok is True
    assert result.attempts == 2
    assert spy.feedbacks[0] is None
    assert spy.feedbacks[1] is not None
    assert "DROP" in spy.feedbacks[1]


def test_agota_reintentos_devuelve_mensaje_saneado(monkeypatch):
    """Todos los intentos fallan -> ok=False, sin error crudo ni stacktrace."""
    n = settings.max_sql_retries
    spy = _GenerateSpy(["SELECT * FROM orders WHERE x = 1"] * n)
    monkeypatch.setattr(execute, "generate_sql", spy)
    monkeypatch.setattr(execute, "validate_and_secure", lambda sql: sql)

    error_pg = 'column "x" does not exist'

    def always_fail(sql):
        raise psycopg.errors.UndefinedColumn(error_pg)

    monkeypatch.setattr(execute, "run_query", always_fail)

    result = answer_question("pregunta imposible", client=SENTINEL_CLIENT)

    assert result.ok is False
    assert result.attempts == settings.max_sql_retries
    assert spy.calls == settings.max_sql_retries
    # El mensaje al usuario NO debe filtrar el error de Postgres, el SQL crudo
    # ni un stacktrace.
    msg = result.error_message or ""
    assert msg  # hay un mensaje claro
    assert error_pg not in msg
    assert "does not exist" not in msg
    assert "Traceback" not in msg
    assert "SELECT" not in msg
    assert result.sql is None
    assert result.columns == []
    assert result.rows == []


def test_no_crea_cliente_real_si_se_inyecta(monkeypatch):
    """Si se inyecta client, no se llama a get_client (no se toca la red)."""
    def boom():
        raise AssertionError("get_client no debería llamarse cuando se inyecta client")

    monkeypatch.setattr(execute, "get_client", boom)
    spy = _GenerateSpy(["SELECT 1"])
    monkeypatch.setattr(execute, "generate_sql", spy)
    monkeypatch.setattr(execute, "validate_and_secure", lambda sql: sql)
    monkeypatch.setattr(execute, "run_query", _fake_run_query_ok)

    result = answer_question("hola", client=SENTINEL_CLIENT)
    assert result.ok is True


# ---------------------------------------------------------------------------
# A2 — robustez ante errores de la API de Anthropic / RuntimeError.
# Ninguno debe PROPAGARSE fuera de answer_question; se tratan como intento
# recuperable y, si se agotan, se devuelve ok=False con mensaje saneado.
# ---------------------------------------------------------------------------


def test_runtime_error_de_generate_no_se_propaga(monkeypatch):
    """Un RuntimeError de generate_sql (tool_use ausente) es recuperable."""
    spy = _GenerateSpy(["SELECT count(*) AS total FROM orders"])

    calls = {"n": 0}

    def generate_que_falla_primero(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("El modelo no devolvió un bloque tool_use válido")
        return spy(*args, **kwargs)

    monkeypatch.setattr(execute, "generate_sql", generate_que_falla_primero)
    monkeypatch.setattr(execute, "validate_and_secure", lambda sql: sql)
    monkeypatch.setattr(execute, "run_query", _fake_run_query_ok)

    result = answer_question("¿cuántos pedidos?", client=SENTINEL_CLIENT)

    assert result.ok is True
    assert result.attempts == 2


def test_rate_limit_anthropic_no_se_propaga_y_da_mensaje_saturado(monkeypatch):
    """Si la API agota los intentos por saturación -> ok=False, mensaje 'saturado'."""
    n = settings.max_sql_retries

    def siempre_rate_limit(*args, **kwargs):
        raise _rate_limit_error()

    monkeypatch.setattr(execute, "generate_sql", siempre_rate_limit)
    monkeypatch.setattr(execute, "validate_and_secure", lambda sql: sql)
    monkeypatch.setattr(execute, "run_query", _fake_run_query_ok)

    # No debe lanzar: se sanea a ok=False.
    result = answer_question("¿cuántos pedidos?", client=SENTINEL_CLIENT)

    assert result.ok is False
    assert result.attempts == n
    msg = result.error_message or ""
    assert "saturado" in msg.lower()
    # Nunca fuga el detalle interno ni un stacktrace.
    assert "Traceback" not in msg
    assert "RateLimit" not in msg
    assert "429" not in msg


def test_error_anthropic_transitorio_se_reintenta_y_converge(monkeypatch):
    """Un fallo de la API en el 1er intento y éxito en el 2º -> ok=True."""
    sqls = ["SELECT count(*) AS total FROM orders"]
    estado = {"n": 0}

    def generate(*args, **kwargs):
        estado["n"] += 1
        if estado["n"] == 1:
            raise _rate_limit_error(request_id="req_abc123")
        return sqls[0]

    monkeypatch.setattr(execute, "generate_sql", generate)
    monkeypatch.setattr(execute, "validate_and_secure", lambda sql: sql)
    monkeypatch.setattr(execute, "run_query", _fake_run_query_ok)

    result = answer_question("¿cuántos pedidos?", client=SENTINEL_CLIENT)

    assert result.ok is True
    assert result.attempts == 2


def test_api_status_error_no_se_propaga(monkeypatch):
    """Un APIStatusError (5xx) tampoco se propaga: ok=False saneado."""

    def siempre_5xx(*args, **kwargs):
        req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        resp = httpx.Response(500, request=req)
        raise anthropic.InternalServerError("boom", response=resp, body=None)

    monkeypatch.setattr(execute, "generate_sql", siempre_5xx)
    monkeypatch.setattr(execute, "validate_and_secure", lambda sql: sql)
    monkeypatch.setattr(execute, "run_query", _fake_run_query_ok)

    result = answer_question("hola", client=SENTINEL_CLIENT)
    assert result.ok is False
    assert "saturado" in (result.error_message or "").lower()


# ---------------------------------------------------------------------------
# Integración de la memoria conversacional (Fase 5).
# ---------------------------------------------------------------------------

from app.agent import memory  # noqa: E402  (import local a la sección de memoria)


@pytest.fixture
def _memoria_limpia():
    """Resetea el store de memoria antes y después de cada test que lo use."""
    memory.clear_all()
    yield
    memory.clear_all()


def test_segundo_turno_recibe_history_del_primero(monkeypatch, _memoria_limpia):
    """El 2º turno (mismo chat_id) recibe el history del 1º; el 1º recibe None."""
    spy = _GenerateSpy(
        [
            "SELECT count(*) AS total FROM orders",  # turno 1
            "SELECT count(*) AS total FROM customers",  # turno 2
        ]
    )
    monkeypatch.setattr(execute, "generate_sql", spy)
    monkeypatch.setattr(execute, "validate_and_secure", lambda sql: sql)
    monkeypatch.setattr(execute, "run_query", _fake_run_query_ok)

    answer_question("¿cuántos pedidos?", chat_id=42, client=SENTINEL_CLIENT)
    answer_question("¿y clientes?", chat_id=42, client=SENTINEL_CLIENT)

    # El 1er turno no tenía historial previo: get_history devuelve [] (vacío),
    # que generate_sql trata igual que None (su `if history:` es falsy).
    assert spy.histories[0] == []
    # El 2º turno recibe el turno previo: pregunta + SQL securizado del 1º.
    assert spy.histories[1] == [
        {"role": "user", "content": "¿cuántos pedidos?"},
        {"role": "assistant", "content": "SELECT count(*) AS total FROM orders"},
    ]


def test_sin_chat_id_history_es_none(monkeypatch, _memoria_limpia):
    """Sin chat_id no se activa memoria: el history pasado es None."""
    spy = _GenerateSpy(["SELECT count(*) AS total FROM orders"])
    monkeypatch.setattr(execute, "generate_sql", spy)
    monkeypatch.setattr(execute, "validate_and_secure", lambda sql: sql)
    monkeypatch.setattr(execute, "run_query", _fake_run_query_ok)

    answer_question("¿cuántos pedidos?", client=SENTINEL_CLIENT)

    assert spy.histories == [None]


def test_exito_hace_append_a_memoria(monkeypatch, _memoria_limpia):
    """Tras un turno exitoso, la memoria del chat tiene la pregunta y el SQL."""
    spy = _GenerateSpy(["SELECT count(*) AS total FROM orders"])
    monkeypatch.setattr(execute, "generate_sql", spy)
    monkeypatch.setattr(execute, "validate_and_secure", lambda sql: sql)
    monkeypatch.setattr(execute, "run_query", _fake_run_query_ok)

    answer_question("¿cuántos pedidos?", chat_id=7, client=SENTINEL_CLIENT)

    # Usa el store real (reseteado por la fixture).
    assert memory.get_history(7) == [
        {"role": "user", "content": "¿cuántos pedidos?"},
        {"role": "assistant", "content": "SELECT count(*) AS total FROM orders"},
    ]


def test_fallo_no_hace_append_a_memoria(monkeypatch, _memoria_limpia):
    """Si se agotan los reintentos (ok=False), NO se guarda nada en memoria."""
    n = settings.max_sql_retries
    spy = _GenerateSpy(["SELECT * FROM orders WHERE x = 1"] * n)
    monkeypatch.setattr(execute, "generate_sql", spy)
    monkeypatch.setattr(execute, "validate_and_secure", lambda sql: sql)

    def always_fail(sql):
        raise psycopg.errors.UndefinedColumn('column "x" does not exist')

    monkeypatch.setattr(execute, "run_query", always_fail)

    result = answer_question("pregunta imposible", chat_id=8, client=SENTINEL_CLIENT)

    assert result.ok is False
    assert memory.get_history(8) == []


def test_aislamiento_entre_chats(monkeypatch, _memoria_limpia):
    """El history de un turno de chat 2 no contiene la pregunta de chat 1."""
    spy = _GenerateSpy(
        [
            "SELECT 1",  # chat 1
            "SELECT 2",  # chat 2
        ]
    )
    monkeypatch.setattr(execute, "generate_sql", spy)
    monkeypatch.setattr(execute, "validate_and_secure", lambda sql: sql)
    monkeypatch.setattr(execute, "run_query", _fake_run_query_ok)

    answer_question("pregunta de chat 1", chat_id=1, client=SENTINEL_CLIENT)
    answer_question("pregunta de chat 2", chat_id=2, client=SENTINEL_CLIENT)

    # El turno de chat 2 no arrastra nada del chat 1.
    history_chat_2 = spy.histories[1]
    contenidos = [m["content"] for m in (history_chat_2 or [])]
    assert "pregunta de chat 1" not in contenidos
    # Y de hecho, al ser su primer turno, chat 2 no tenía historial previo
    # (get_history devuelve [] para un chat sin turnos).
    assert history_chat_2 == []


def test_history_constante_entre_reintentos_del_mismo_turno(monkeypatch, _memoria_limpia):
    """El history del turno previo es el mismo en los 2 intentos; el feedback no.

    Sembramos un turno previo (chat 5) y, en el turno actual, el 1er intento
    falla en run_query y el 2º converge. Ambos intentos deben llevar el MISMO
    history (el del turno previo); el 2º intento, además, lleva el error_feedback.
    """
    # Turno previo que puebla la memoria del chat 5.
    spy_previo = _GenerateSpy(["SELECT count(*) AS total FROM orders"])
    monkeypatch.setattr(execute, "generate_sql", spy_previo)
    monkeypatch.setattr(execute, "validate_and_secure", lambda sql: sql)
    monkeypatch.setattr(execute, "run_query", _fake_run_query_ok)
    answer_question("¿cuántos pedidos?", chat_id=5, client=SENTINEL_CLIENT)

    historial_previo = [
        {"role": "user", "content": "¿cuántos pedidos?"},
        {"role": "assistant", "content": "SELECT count(*) AS total FROM orders"},
    ]

    # Turno actual: el 1er intento rompe en run_query; el 2º converge.
    spy = _GenerateSpy(
        [
            "SELECT * FROM orders WHERE no_existe = 1",  # falla en run_query
            "SELECT count(*) AS total FROM orders",  # válido
        ]
    )
    monkeypatch.setattr(execute, "generate_sql", spy)

    error_pg = 'column "no_existe" does not exist'

    def fake_run_query(sql):
        if "no_existe" in sql:
            raise psycopg.errors.UndefinedColumn(error_pg)
        return (["total"], [(830,)])

    monkeypatch.setattr(execute, "run_query", fake_run_query)

    result = answer_question("dame el detalle", chat_id=5, client=SENTINEL_CLIENT)

    assert result.ok is True
    assert result.attempts == 2
    # Los 2 intentos del MISMO turno llevan el mismo history del turno previo.
    assert spy.histories[0] == historial_previo
    assert spy.histories[1] == historial_previo
    # Ortogonalidad: el 1er intento sin feedback, el 2º con el error de PG.
    assert spy.feedbacks[0] is None
    assert spy.feedbacks[1] is not None
    assert "no_existe" in spy.feedbacks[1]
