"""Pruebas de generación de SQL con el cliente Anthropic MOCKEADO.

No tocan la red ni requieren API key real: usan un cliente falso cuyo
messages.create devuelve un objeto con un bloque tipo tool_use. Verifican que:
- generate_sql fuerza tool_choice a la herramienta emit_sql.
- extrae correctamente el 'sql' del bloque tool_use.
- arma el prompt de sistema con cache_control en el último bloque.
"""

from __future__ import annotations

import pytest

from app.agent.generate_sql import (
    EMIT_SQL_TOOL,
    build_system_prompt,
    generate_sql,
)

SCHEMA = "TABLE orders(order_id int PK, customer_id varchar -> customers.customer_id)"
GLOSSARY = "GLOSARIO: venta = unit_price * quantity * (1 - discount)."
FAKE_SQL = "SELECT count(*) AS total FROM orders"


class _FakeToolUseBlock:
    """Imita un bloque tool_use de la respuesta de la API."""

    def __init__(self, name: str, sql: str) -> None:
        self.type = "tool_use"
        self.name = name
        self.input = {"sql": sql, "rationale": "cuenta los pedidos"}


class _FakeResponse:
    def __init__(self, content) -> None:
        self.content = content
        self.stop_reason = "tool_use"


class _FakeMessages:
    """Captura los kwargs de la llamada y devuelve una respuesta fija."""

    def __init__(self, response) -> None:
        self._response = response
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._response


class _FakeClient:
    def __init__(self, response) -> None:
        self.messages = _FakeMessages(response)


def _make_client(content):
    return _FakeClient(_FakeResponse(content))


def test_extrae_sql_del_bloque_tool_use():
    client = _make_client([_FakeToolUseBlock("emit_sql", FAKE_SQL)])
    sql = generate_sql(client, "¿cuántos pedidos hay?", SCHEMA, GLOSSARY)
    assert sql == FAKE_SQL


def test_fuerza_tool_choice_emit_sql():
    client = _make_client([_FakeToolUseBlock("emit_sql", FAKE_SQL)])
    generate_sql(client, "¿cuántos pedidos hay?", SCHEMA, GLOSSARY)

    kwargs = client.messages.last_kwargs
    assert kwargs is not None
    # tool_choice forzado a la herramienta emit_sql.
    assert kwargs["tool_choice"] == {"type": "tool", "name": "emit_sql"}
    # La herramienta emit_sql está en la lista de tools.
    tool_names = [t["name"] for t in kwargs["tools"]]
    assert "emit_sql" in tool_names
    assert kwargs["tools"][0] is EMIT_SQL_TOOL


def test_pasa_la_pregunta_como_mensaje_de_usuario():
    client = _make_client([_FakeToolUseBlock("emit_sql", FAKE_SQL)])
    generate_sql(client, "¿cuántos pedidos hay?", SCHEMA, GLOSSARY)

    messages = client.messages.last_kwargs["messages"]
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "¿cuántos pedidos hay?"


def test_error_feedback_anade_turno_de_correccion():
    client = _make_client([_FakeToolUseBlock("emit_sql", FAKE_SQL)])
    generate_sql(
        client,
        "¿cuántos pedidos hay?",
        SCHEMA,
        GLOSSARY,
        error_feedback="column 'ordes' does not exist",
    )
    messages = client.messages.last_kwargs["messages"]
    # El último mensaje debe ser el feedback de error (turno de auto-corrección).
    assert messages[-1]["role"] == "user"
    assert "ordes" in messages[-1]["content"]


def test_sin_bloque_tool_use_lanza_error():
    # Respuesta sin ningún bloque tool_use emit_sql.
    class _TextBlock:
        type = "text"
        text = "No puedo."

    client = _make_client([_TextBlock()])
    with pytest.raises(RuntimeError):
        generate_sql(client, "pregunta", SCHEMA, GLOSSARY)


def test_sql_vacio_lanza_error():
    client = _make_client([_FakeToolUseBlock("emit_sql", "")])
    with pytest.raises(RuntimeError):
        generate_sql(client, "pregunta", SCHEMA, GLOSSARY)


def test_system_prompt_cachea_ultimo_bloque():
    system = build_system_prompt(SCHEMA, GLOSSARY)
    assert isinstance(system, list)
    assert len(system) == 3
    # Solo el último bloque lleva cache_control ephemeral.
    assert system[-1].get("cache_control") == {"type": "ephemeral"}
    assert "cache_control" not in system[0]
    assert "cache_control" not in system[1]
    # El esquema y el glosario están presentes.
    joined = "\n".join(b["text"] for b in system)
    assert "orders" in joined
    assert "GLOSARIO" in joined


def test_instrucciones_guian_columnas_justas_en_comparacion():
    """La regla nueva (#7) debe pedir SOLO dimensión + la métrica pedida,
    sin agregar métricas que el usuario no pidió. Esto guía al modelo a
    devolver 2 columnas en preguntas de comparar/ver, para que el router las
    grafique en vez de mandarlas a Excel."""
    instructions = build_system_prompt(SCHEMA, GLOSSARY)[0]["text"]
    low = instructions.lower()
    # Existe la regla numerada nueva.
    assert "7." in instructions
    # Menciona comparar/ver una métrica por una dimensión.
    assert "comparar" in low or "comparar o ver" in low
    assert "dimensión" in low
    assert "métrica" in low
    # Pide devolver SOLO 2 columnas (dimensión + la única métrica).
    assert "2 columnas" in low
    # No agregar métricas que el usuario no pidió.
    assert "no pidió" in low or "no pidio" in low
    # Excepción explícita para varias métricas / detalle / reporte.
    assert "excepción" in low or "excepcion" in low
    # Series temporales: no duplicar el eje (fecha + nombre del mes).
    assert "por mes" in low or "serie" in low or "temporal" in low


def test_reglas_duras_de_seguridad_intactas():
    """La regla nueva NO debe haber alterado las barreras de seguridad
    existentes (solo SELECT/WITH, una sola sentencia, nombres exactos)."""
    instructions = build_system_prompt(SCHEMA, GLOSSARY)[0]["text"]
    low = instructions.lower()
    assert "sentencias select o with" in low
    assert "una sola sentencia" in low
    assert "exactamente" in low
    assert "nunca insert, update, delete" in low
    # Las 6 reglas previas siguen presentes (y la nueva 7).
    for n in range(1, 8):
        assert f"{n}." in instructions
