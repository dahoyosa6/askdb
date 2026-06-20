"""Pruebas de los handlers ASÍNCRONOS de Telegram (§4 del informe del tester).

El bot es el ÚNICO punto de contacto con el usuario y la regla dura de "nunca
fugar SQL ni el error interno" se cumple en el try/except de los handlers, que
hasta ahora no tenía red de seguridad. Aquí se cubre, por handler:

  1. no autorizado -> `_TEXTO_NO_AUTORIZADO` y NO se llama al cerebro.
  2. rate-limited -> `_TEXTO_RATE_LIMIT` y NO se llama al cerebro.
  3. camino feliz texto -> `send_message` con el texto del router, NUNCA con SQL.
  4. excepción del cerebro -> EXACTAMENTE `_MENSAJE_GENERICO`, sin str(exc) ni SELECT.
  5. voz: muy larga / transcripción vacía / camino feliz (eco + respuesta).
  6. None-guard: update sin message/effective_chat no revienta.
  7. orden de guards: allowlist ANTES de rate limit.

Todo con `AsyncMock` para `context.bot`: NUNCA se toca la red, la DB ni Anthropic.
`asyncio_mode = auto` (pytest.ini) corre las funciones `async def` como corrutinas.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.interfaces.telegram_bot as tb
from app.output.router import OutputResult

CHAT_OK = 111
CHAT_NO = 999


@pytest.fixture(autouse=True)
def _entorno(monkeypatch):
    """Allowlist con CHAT_OK, rate limiter permisivo y cerebro NO llamado por defecto.

    Cada test que quiera un comportamiento distinto del cerebro lo monkeypatchea.
    Por defecto, `procesar_pregunta` revienta si se llama sin querer (así un test de
    'no autorizado' falla si el cerebro se ejecutara).
    """
    # `settings` es un dataclass frozen: se sustituye por una copia con la
    # allowlist deseada (no se puede mutar in situ).
    monkeypatch.setattr(
        tb,
        "settings",
        dataclasses.replace(
            tb.settings, allowed_chat_ids=[CHAT_OK], max_voice_duration_s=120
        ),
    )
    # Rate limiter nuevo y permisivo para no arrastrar estado entre tests.
    monkeypatch.setattr(tb, "_rate_limiter", tb.RateLimiter(max_per_min=1000))

    def _cerebro_prohibido(*args, **kwargs):
        raise AssertionError("procesar_pregunta NO debía llamarse en este caso")

    monkeypatch.setattr(tb, "procesar_pregunta", _cerebro_prohibido)


def _ctx() -> SimpleNamespace:
    """Contexto falso de PTB con un `bot` AsyncMock (send_message, send_photo, ...)."""
    bot = AsyncMock()
    return SimpleNamespace(bot=bot)


def _update_texto(texto: str, chat_id: int = CHAT_OK) -> SimpleNamespace:
    """Update falso de mensaje de texto."""
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        message=SimpleNamespace(text=texto, voice=None),
    )


def _update_voz(duracion: int | None, chat_id: int = CHAT_OK) -> SimpleNamespace:
    """Update falso de nota de voz."""
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        message=SimpleNamespace(
            text=None, voice=SimpleNamespace(duration=duracion, file_id="f1")
        ),
    )


# ---------------------------------------------------------------------------
# handle_text
# ---------------------------------------------------------------------------


async def test_texto_no_autorizado_no_llama_cerebro():
    """Chat fuera de la allowlist -> _TEXTO_NO_AUTORIZADO y cerebro intacto."""
    ctx = _ctx()
    await tb.handle_text(_update_texto("hola", chat_id=CHAT_NO), ctx)

    ctx.bot.send_message.assert_awaited_once_with(CHAT_NO, tb._TEXTO_NO_AUTORIZADO)


async def test_texto_rate_limited_no_llama_cerebro(monkeypatch):
    """Sobre el límite -> _TEXTO_RATE_LIMIT y cerebro intacto."""
    monkeypatch.setattr(tb, "_rate_limiter", tb.RateLimiter(max_per_min=0))
    ctx = _ctx()
    await tb.handle_text(_update_texto("hola"), ctx)

    ctx.bot.send_message.assert_awaited_once_with(CHAT_OK, tb._TEXTO_RATE_LIMIT)


async def test_texto_orden_guards_allowlist_antes_de_rate_limit(monkeypatch):
    """Un no autorizado, aun con rate limit a 0, recibe NO_AUTORIZADO (no rate-limit)."""
    monkeypatch.setattr(tb, "_rate_limiter", tb.RateLimiter(max_per_min=0))
    ctx = _ctx()
    await tb.handle_text(_update_texto("hola", chat_id=CHAT_NO), ctx)

    ctx.bot.send_message.assert_awaited_once_with(CHAT_NO, tb._TEXTO_NO_AUTORIZADO)


async def test_texto_camino_feliz_envia_texto_y_nunca_sql(monkeypatch):
    """Camino feliz -> send_message con el texto del router; jamás SQL."""
    async def fake_to_thread(fn, *args, **kwargs):
        return OutputResult(kind="text", text="830.")

    monkeypatch.setattr(tb.asyncio, "to_thread", fake_to_thread)
    ctx = _ctx()
    await tb.handle_text(_update_texto("¿cuántos pedidos?"), ctx)

    ctx.bot.send_message.assert_awaited_once_with(CHAT_OK, "830.")
    # Nunca se filtró SQL al usuario.
    enviado = ctx.bot.send_message.await_args.args[1]
    assert "SELECT" not in enviado


async def test_texto_camino_feliz_grafica_envia_photo(monkeypatch, tmp_path):
    """Si el router devuelve chart -> send_photo con el archivo."""
    png = tmp_path / "g.png"
    png.write_bytes(b"\x89PNG fake")

    async def fake_to_thread(fn, *args, **kwargs):
        return OutputResult(kind="chart", file_path=str(png), caption="cap")

    monkeypatch.setattr(tb.asyncio, "to_thread", fake_to_thread)
    ctx = _ctx()
    await tb.handle_text(_update_texto("top 5"), ctx)

    ctx.bot.send_photo.assert_awaited_once()
    ctx.bot.send_message.assert_not_awaited()


async def test_texto_excepcion_del_cerebro_envia_mensaje_generico(monkeypatch):
    """El cerebro lanza -> EXACTAMENTE _MENSAJE_GENERICO; no viaja str(exc) ni SELECT."""
    async def fake_to_thread(fn, *args, **kwargs):
        raise RuntimeError("SELECT secreto FROM tabla -- boom interno")

    monkeypatch.setattr(tb.asyncio, "to_thread", fake_to_thread)
    ctx = _ctx()
    await tb.handle_text(_update_texto("algo"), ctx)

    ctx.bot.send_message.assert_awaited_once_with(CHAT_OK, tb._MENSAJE_GENERICO)
    enviado = ctx.bot.send_message.await_args.args[1]
    assert "SELECT" not in enviado
    assert "boom interno" not in enviado


async def test_texto_vacio_no_hace_nada():
    """Un mensaje de solo espacios no llama al cerebro ni responde."""
    ctx = _ctx()
    await tb.handle_text(_update_texto("   "), ctx)
    ctx.bot.send_message.assert_not_awaited()


async def test_texto_none_guard_no_revienta():
    """Update sin message/effective_chat -> retorna sin error y sin enviar nada."""
    ctx = _ctx()
    update = SimpleNamespace(effective_chat=None, message=None)
    await tb.handle_text(update, ctx)  # no debe lanzar
    ctx.bot.send_message.assert_not_awaited()


# ---------------------------------------------------------------------------
# handle_voice
# ---------------------------------------------------------------------------


async def test_voz_no_autorizada_no_llama_cerebro():
    """Voz de chat no autorizado -> _TEXTO_NO_AUTORIZADO."""
    ctx = _ctx()
    await tb.handle_voice(_update_voz(5, chat_id=CHAT_NO), ctx)
    ctx.bot.send_message.assert_awaited_once_with(CHAT_NO, tb._TEXTO_NO_AUTORIZADO)


async def test_voz_rate_limited(monkeypatch):
    """Voz sobre el límite -> _TEXTO_RATE_LIMIT."""
    monkeypatch.setattr(tb, "_rate_limiter", tb.RateLimiter(max_per_min=0))
    ctx = _ctx()
    await tb.handle_voice(_update_voz(5), ctx)
    ctx.bot.send_message.assert_awaited_once_with(CHAT_OK, tb._TEXTO_RATE_LIMIT)


async def test_voz_demasiado_larga_no_procesa(monkeypatch):
    """Duración > máximo -> _TEXTO_VOZ_MUY_LARGA y NO se descarga/transcribe."""
    ctx = _ctx()
    await tb.handle_voice(_update_voz(999), ctx)
    ctx.bot.send_message.assert_awaited_once_with(CHAT_OK, tb._TEXTO_VOZ_MUY_LARGA)
    ctx.bot.get_file.assert_not_awaited()


async def test_voz_transcripcion_vacia(monkeypatch):
    """Transcripción vacía -> _TEXTO_VOZ_NO_ENTENDIDA, no se llama al cerebro."""

    async def fake_to_thread(fn, *args, **kwargs):
        return "   "  # transcribe devuelve vacío

    monkeypatch.setattr(tb.asyncio, "to_thread", fake_to_thread)

    ctx = _ctx()
    # get_file/download deben devolver objetos awaitable utilizables.
    archivo = AsyncMock()
    archivo.download_as_bytearray = AsyncMock(return_value=bytearray(b"audio"))
    ctx.bot.get_file = AsyncMock(return_value=archivo)

    await tb.handle_voice(_update_voz(5), ctx)
    ctx.bot.send_message.assert_awaited_once_with(CHAT_OK, tb._TEXTO_VOZ_NO_ENTENDIDA)


async def test_voz_camino_feliz_ecoa_y_responde(monkeypatch):
    """Voz feliz -> eco '🎤 Entendí:' y luego la respuesta del router."""

    llamadas = {"n": 0}

    async def fake_to_thread(fn, *args, **kwargs):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            return "cuántos pedidos hay"  # transcribe
        return OutputResult(kind="text", text="830.")  # procesar_pregunta

    monkeypatch.setattr(tb.asyncio, "to_thread", fake_to_thread)

    ctx = _ctx()
    archivo = AsyncMock()
    archivo.download_as_bytearray = AsyncMock(return_value=bytearray(b"audio"))
    ctx.bot.get_file = AsyncMock(return_value=archivo)

    await tb.handle_voice(_update_voz(5), ctx)

    textos = [c.args[1] for c in ctx.bot.send_message.await_args_list]
    assert any("🎤 Entendí" in t for t in textos)
    assert "830." in textos


async def test_voz_none_guard_no_revienta():
    """Voz: update sin message/effective_chat -> no revienta."""
    ctx = _ctx()
    update = SimpleNamespace(effective_chat=None, message=None)
    await tb.handle_voice(update, ctx)
    ctx.bot.send_message.assert_not_awaited()


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------


async def test_cmd_start_autorizado_envia_bienvenida():
    ctx = _ctx()
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=CHAT_OK), message=None)
    await tb.cmd_start(update, ctx)
    ctx.bot.send_message.assert_awaited_once_with(CHAT_OK, tb._TEXTO_START)


async def test_cmd_help_no_autorizado():
    ctx = _ctx()
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=CHAT_NO), message=None)
    await tb.cmd_help(update, ctx)
    ctx.bot.send_message.assert_awaited_once_with(CHAT_NO, tb._TEXTO_NO_AUTORIZADO)


async def test_cmd_reset_limpia_memoria(monkeypatch):
    """/reset autorizado -> llama memory.reset y confirma con _TEXTO_RESET."""
    reseteados = []
    monkeypatch.setattr(tb.memory, "reset", lambda cid: reseteados.append(cid))
    ctx = _ctx()
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=CHAT_OK), message=None)
    await tb.cmd_reset(update, ctx)
    assert reseteados == [CHAT_OK]
    ctx.bot.send_message.assert_awaited_once_with(CHAT_OK, tb._TEXTO_RESET)


async def test_cmd_start_none_guard_no_revienta():
    ctx = _ctx()
    update = SimpleNamespace(effective_chat=None, message=None)
    await tb.cmd_start(update, ctx)
    ctx.bot.send_message.assert_not_awaited()
