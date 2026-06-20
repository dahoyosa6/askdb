"""Pruebas de la lógica pura de la interfaz de Telegram (Fase 6).

Todo SÍNCRONO: no se importa pytest-asyncio. Se prueban las piezas que NO tocan
la red ni el event loop:
- `RateLimiter`: ventana móvil por chat, con `now` inyectado (determinista).
- `is_allowed`: allowlist.
- `decidir_envio`: traducción OutputResult -> EnvioPlan.
- `procesar_pregunta`: puente síncrono al cerebro (con answer_question y
  enrutar_salida monkeypatcheados), comprobando que pasa el chat_id y que NUNCA
  devuelve el SQL.

Los handlers async y `build_application` no se prueban aquí (requerirían un event
loop / un bot real); la lógica que contienen está factorizada en estas funciones
puras, que sí se prueban.
"""

from __future__ import annotations

import app.interfaces.telegram_bot as tb
from app.interfaces.telegram_bot import (
    EnvioPlan,
    RateLimiter,
    decidir_envio,
    is_allowed,
    procesar_pregunta,
    texto_eco,
    voz_demasiado_larga,
)
from app.output.router import OutputResult

# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


def test_ratelimiter_permite_bajo_el_limite():
    """Con max=3, las 3 primeras peticiones se permiten."""
    rl = RateLimiter(max_per_min=3)
    assert rl.allow(chat_id=1, now=0.0) is True
    assert rl.allow(chat_id=1, now=1.0) is True
    assert rl.allow(chat_id=1, now=2.0) is True


def test_ratelimiter_bloquea_en_el_limite():
    """La 4ª petición dentro de la ventana (max=3) se bloquea."""
    rl = RateLimiter(max_per_min=3)
    rl.allow(chat_id=1, now=0.0)
    rl.allow(chat_id=1, now=1.0)
    rl.allow(chat_id=1, now=2.0)
    assert rl.allow(chat_id=1, now=3.0) is False


def test_ratelimiter_vuelve_a_permitir_tras_la_ventana():
    """Pasados >60s, las marcas viejas salen de la ventana y se vuelve a permitir."""
    rl = RateLimiter(max_per_min=2, window_s=60.0)
    assert rl.allow(chat_id=1, now=0.0) is True
    assert rl.allow(chat_id=1, now=1.0) is True
    assert rl.allow(chat_id=1, now=2.0) is False  # en el límite
    # A los 61s, las dos marcas (0.0 y 1.0) ya salieron de la ventana de 60s.
    assert rl.allow(chat_id=1, now=61.5) is True


def test_ratelimiter_aisla_chats():
    """El consumo de un chat no afecta el cupo de otro."""
    rl = RateLimiter(max_per_min=1)
    assert rl.allow(chat_id=1, now=0.0) is True
    assert rl.allow(chat_id=1, now=0.1) is False  # chat 1 agotó su cupo
    assert rl.allow(chat_id=2, now=0.2) is True  # chat 2 tiene el suyo intacto


# ---------------------------------------------------------------------------
# is_allowed
# ---------------------------------------------------------------------------


def test_is_allowed_autorizado():
    assert is_allowed(123, [123, 456]) is True


def test_is_allowed_no_autorizado():
    assert is_allowed(999, [123, 456]) is False


def test_is_allowed_lista_vacia_no_autoriza_a_nadie():
    assert is_allowed(123, []) is False


# ---------------------------------------------------------------------------
# decidir_envio
# ---------------------------------------------------------------------------


def test_decidir_envio_text_a_message():
    plan = decidir_envio(OutputResult(kind="text", text="hola"))
    assert plan == EnvioPlan(metodo="message", text="hola")


def test_decidir_envio_chart_a_photo():
    salida = OutputResult(kind="chart", file_path="/tmp/g.png", caption="x / y")
    plan = decidir_envio(salida)
    assert plan.metodo == "photo"
    assert plan.file_path == "/tmp/g.png"
    assert plan.caption == "x / y"


def test_decidir_envio_excel_a_document():
    salida = OutputResult(kind="excel", file_path="/tmp/d.xlsx", caption="10 filas")
    plan = decidir_envio(salida)
    assert plan.metodo == "document"
    assert plan.file_path == "/tmp/d.xlsx"
    assert plan.caption == "10 filas"


def test_decidir_envio_kind_desconocido_cae_a_mensaje_generico():
    """Un kind inesperado y sin texto cae a message con el mensaje genérico."""
    salida = OutputResult(kind="raro", text=None)
    plan = decidir_envio(salida)
    assert plan.metodo == "message"
    assert plan.text == tb._MENSAJE_GENERICO


def test_decidir_envio_text_none_cae_a_mensaje_generico():
    """kind text pero sin texto -> nunca un mensaje vacío; usa el genérico."""
    plan = decidir_envio(OutputResult(kind="text", text=None))
    assert plan.metodo == "message"
    assert plan.text == tb._MENSAJE_GENERICO


# ---------------------------------------------------------------------------
# procesar_pregunta (puente síncrono)
# ---------------------------------------------------------------------------


def test_procesar_pregunta_pasa_chat_id_y_devuelve_output(monkeypatch):
    """Verifica que pasa el chat_id a answer_question y devuelve el OutputResult.

    También comprueba que el resultado NO contiene el SQL crudo (regla dura).
    """
    capturado = {}

    class _FakeAnswer:
        ok = True
        sql = "SELECT count(*) FROM orders"  # interno; no debe salir al usuario

    def fake_answer_question(question, chat_id=None):
        capturado["question"] = question
        capturado["chat_id"] = chat_id
        return _FakeAnswer()

    def fake_enrutar_salida(result):
        # El router devuelve solo texto saneado, nunca el SQL.
        return OutputResult(kind="text", text="Hay 830 pedidos.")

    monkeypatch.setattr(tb, "answer_question", fake_answer_question)
    monkeypatch.setattr(tb, "enrutar_salida", fake_enrutar_salida)

    salida = procesar_pregunta("¿cuántos pedidos?", chat_id=77)

    # Pasó la pregunta y el chat_id correctos al cerebro.
    assert capturado["question"] == "¿cuántos pedidos?"
    assert capturado["chat_id"] == 77
    # Devolvió el OutputResult del router.
    assert isinstance(salida, OutputResult)
    assert salida.kind == "text"
    assert salida.text == "Hay 830 pedidos."
    # El SQL crudo NUNCA viaja en lo que se le entrega al usuario.
    assert "SELECT" not in (salida.text or "")
    assert "SELECT" not in (salida.caption or "")


# ---------------------------------------------------------------------------
# voz_demasiado_larga (Fase 7, helper puro)
# ---------------------------------------------------------------------------


def test_voz_demasiado_larga_excede():
    assert voz_demasiado_larga(130, 120) is True


def test_voz_demasiado_larga_no_excede():
    """Igual al máximo o por debajo no bloquea."""
    assert voz_demasiado_larga(120, 120) is False
    assert voz_demasiado_larga(10, 120) is False


def test_voz_demasiado_larga_none_no_bloquea():
    """Sin dato de duración (None) no se bloquea."""
    assert voz_demasiado_larga(None, 120) is False


# ---------------------------------------------------------------------------
# texto_eco (Fase 7, helper puro)
# ---------------------------------------------------------------------------


def test_texto_eco_formato_correcto():
    assert texto_eco("cuántos pedidos hay") == '🎤 Entendí: "cuántos pedidos hay"'


def test_texto_eco_incluye_el_texto():
    eco = texto_eco("ventas del mes")
    assert "ventas del mes" in eco
