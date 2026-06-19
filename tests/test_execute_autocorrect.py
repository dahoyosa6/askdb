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

import psycopg
import pytest

import app.agent.execute as execute
from app.agent.execute import answer_question
from app.agent.validate_sql import SQLValidationError
from config import settings

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
        self.calls = 0

    def __call__(self, client, question, schema, glossary, *, error_feedback=None):
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
