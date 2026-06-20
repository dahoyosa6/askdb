"""Interfaz de Telegram de AskDB (Fase 6, solo texto).

Adaptador delgado entre Telegram y el cerebro síncrono del proyecto. El cerebro
(`answer_question` -> `enrutar_salida`) es SÍNCRONO; python-telegram-bot v21 es
ASÍNCRONO. El puente entre ambos mundos es `procesar_pregunta`, que se ejecuta en
un hilo aparte (`asyncio.to_thread`) desde los handlers async para no bloquear el
event loop.

Diseño en capas (de pura a I/O):
- `RateLimiter`: control de frecuencia por chat (estado en RAM).
- Funciones puras (`is_allowed`, `decidir_envio`): deciden sin tocar la red.
- `procesar_pregunta`: puente síncrono al cerebro.
- Handlers async + `build_application`: el borde con Telegram.

Reglas duras del proyecto que esta capa respeta:
- NUNCA se expone al usuario el SQL crudo ni el error interno: los stacktraces y
  detalles se loguean SOLO del lado servidor; al usuario le llega un mensaje
  saneado en español.
- Allowlist de chat IDs (`settings.allowed_chat_ids`): solo responden los
  autorizados.
- Rate limit por chat (`settings.rate_limit_per_min`).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import settings

# Se importan a nivel de módulo (no dentro de las funciones) a propósito: así los
# tests pueden monkeypatchear `telegram_bot.answer_question`,
# `telegram_bot.enrutar_salida` y `telegram_bot.memory` para probar la lógica sin
# tocar la red, la base de datos ni Anthropic.
from app.agent import memory
from app.agent.execute import answer_question
from app.output.router import OutputResult, enrutar_salida

logger = logging.getLogger(__name__)

# Mensaje genérico y saneado para el usuario cuando algo sale mal. NUNCA debe
# contener SQL crudo, el error interno ni un stacktrace (regla dura): esos
# detalles solo van al log del servidor.
_MENSAJE_GENERICO = (
    "Ocurrió un problema procesando tu pregunta. Intenta reformularla."
)

# --- Textos de los comandos (en español, lenguaje claro para Marta) ---
_TEXTO_NO_AUTORIZADO = "No estás autorizado para usar este bot."
_TEXTO_RATE_LIMIT = "Vas muy rápido, intenta de nuevo en un momento."
_TEXTO_RESET = "Listo, olvidé el contexto de esta conversación."

_TEXTO_START = (
    "¡Hola! Soy AskDB, tu asistente para consultar tus datos.\n\n"
    "Escríbeme una pregunta en español sobre tu negocio y te respondo con el "
    "dato, una gráfica o un archivo de Excel, según lo que pidas. No necesitas "
    "saber nada técnico: pregunta como le preguntarías a un asistente.\n\n"
    "Usa /help para ver ejemplos y /reset para empezar una conversación nueva."
)

_TEXTO_HELP = (
    "Puedes preguntarme cosas como:\n"
    "• ¿Cuáles son mis 5 mejores clientes por facturación?\n"
    "• ¿Cómo van las ventas por mes de 1997?\n"
    "• ¿Qué productos son los más vendidos?\n"
    "• ¿Cuántos pedidos hay en total?\n\n"
    "Comandos: /start (bienvenida) · /help (esta ayuda) · "
    "/reset (olvidar la conversación)."
)


class RateLimiter:
    """Limitador de frecuencia por `chat_id` con ventana móvil de tiempo.

    Mantiene, por chat, las marcas de tiempo de las peticiones recientes y
    permite hasta `max_per_min` dentro de una ventana de `window_s` segundos.

    Limitaciones conocidas (v1, igual que la memoria):
    - **Estado en RAM:** se pierde al reiniciar el proceso.
    - **No es thread-safe:** no usa candados; asume el event loop de un solo
      proceso (los handlers de PTB corren en el mismo loop).
    - **Single-instance:** no se comparte entre varias instancias/workers. Para
      multi-instancia (p. ej. un store en Redis) -> v2.
    """

    def __init__(self, max_per_min: int, window_s: float = 60.0) -> None:
        self._max = max_per_min
        self._window = window_s
        # chat_id -> cola de timestamps (monotónicos) de las peticiones recientes.
        self._eventos: dict[int, deque[float]] = {}

    def allow(self, chat_id: int, now: float | None = None) -> bool:
        """¿Se permite una nueva petición de `chat_id` ahora?

        Usa `time.monotonic()` si `now` es None. `now` es inyectable para que los
        tests sean deterministas (sin depender del reloj real). Si está bajo el
        límite, REGISTRA la petición y devuelve True; si está en o sobre el
        límite, NO registra y devuelve False.
        """
        if now is None:
            now = time.monotonic()

        cola = self._eventos.setdefault(chat_id, deque())

        # Descartamos las marcas que ya salieron de la ventana móvil.
        limite_inferior = now - self._window
        while cola and cola[0] <= limite_inferior:
            cola.popleft()

        if len(cola) >= self._max:
            return False

        cola.append(now)
        return True


# Limitador a nivel de módulo: vive mientras vive el proceso (estado en RAM).
_rate_limiter = RateLimiter(settings.rate_limit_per_min)


def is_allowed(chat_id: int, allowed: list[int]) -> bool:
    """¿Está `chat_id` en la allowlist? Una lista vacía no autoriza a nadie."""
    return chat_id in allowed


@dataclass
class EnvioPlan:
    """Plan de envío hacia Telegram, derivado del `OutputResult` del router.

    `metodo` es uno de: "message" (texto), "photo" (gráfica PNG) o "document"
    (archivo Excel). Es el dato que el handler usa para decidir qué API de
    Telegram llamar, sin volver a inspeccionar el `kind`.
    """

    metodo: str
    text: str | None = None
    file_path: str | None = None
    caption: str | None = None


def decidir_envio(salida: OutputResult) -> EnvioPlan:
    """Traduce un `OutputResult` (capa de salida) a un `EnvioPlan` (capa Telegram).

    - "chart" -> foto (PNG) con leyenda.
    - "excel" -> documento (.xlsx) con leyenda.
    - "text" o CUALQUIER kind inesperado -> mensaje de texto. Si no hay texto,
      se usa `_MENSAJE_GENERICO` (nunca se envía un mensaje vacío).
    """
    if salida.kind == "chart":
        return EnvioPlan(
            metodo="photo",
            file_path=salida.file_path,
            caption=salida.caption,
        )
    if salida.kind == "excel":
        return EnvioPlan(
            metodo="document",
            file_path=salida.file_path,
            caption=salida.caption,
        )
    # "text" o cualquier kind inesperado: caemos a un mensaje de texto seguro.
    return EnvioPlan(metodo="message", text=salida.text or _MENSAJE_GENERICO)


def procesar_pregunta(question: str, chat_id: int) -> OutputResult:
    """Puente SÍNCRONO al cerebro: pregunta -> respuesta lista para enviar.

    Llama a `answer_question` (orquesta generar SQL -> validar -> ejecutar, con
    auto-corrección y memoria por `chat_id`) y luego al router `enrutar_salida`
    para decidir el formato (texto / gráfica / Excel).

    Esta función es síncrona y BLOQUEANTE (toca DB y red): los handlers async la
    ejecutan en un hilo aparte con `asyncio.to_thread`. NUNCA devuelve ni loguea
    el SQL al usuario: el `OutputResult` solo contiene texto saneado o rutas de
    artefacto.
    """
    result = answer_question(question, chat_id=chat_id)
    return enrutar_salida(result)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler de mensajes de texto: el flujo principal del bot.

    Verifica allowlist y rate limit, ejecuta el cerebro en un hilo aparte y envía
    la respuesta según el plan. Todo el procesamiento va dentro de un try/except:
    ante cualquier error se loguea el stacktrace EN EL SERVIDOR y al usuario solo
    le llega un mensaje genérico saneado (nunca el error ni el SQL).
    """
    chat_id = update.effective_chat.id

    # 1. Allowlist: solo responden los chats autorizados.
    if not is_allowed(chat_id, settings.allowed_chat_ids):
        logger.warning("Mensaje de chat NO autorizado: %s", chat_id)
        await context.bot.send_message(chat_id, _TEXTO_NO_AUTORIZADO)
        return

    # 2. Rate limit: frena el abuso por chat.
    if not _rate_limiter.allow(chat_id):
        await context.bot.send_message(chat_id, _TEXTO_RATE_LIMIT)
        return

    # 3. Texto de la pregunta. Si llega vacío, no hay nada que procesar.
    texto = (update.message.text or "").strip()
    if not texto:
        return

    try:
        # El cerebro es síncrono y bloqueante: lo corremos en un hilo para no
        # bloquear el event loop de Telegram.
        salida = await asyncio.to_thread(procesar_pregunta, texto, chat_id)
        plan = decidir_envio(salida)

        if plan.metodo == "photo":
            with open(plan.file_path, "rb") as f:
                await context.bot.send_photo(chat_id, f, caption=plan.caption)
        elif plan.metodo == "document":
            with open(plan.file_path, "rb") as f:
                await context.bot.send_document(chat_id, f, caption=plan.caption)
        else:  # "message"
            await context.bot.send_message(chat_id, plan.text)
    except Exception:  # noqa: BLE001 - frontera: saneamos todo error al usuario
        # Regla dura: stacktrace SOLO en el servidor; al usuario, mensaje genérico.
        logger.exception("handle_text: error procesando el mensaje de chat %s", chat_id)
        await context.bot.send_message(chat_id, _MENSAJE_GENERICO)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start: bienvenida y explicación de cómo usar el bot."""
    chat_id = update.effective_chat.id
    if not is_allowed(chat_id, settings.allowed_chat_ids):
        logger.warning("/start de chat NO autorizado: %s", chat_id)
        await context.bot.send_message(chat_id, _TEXTO_NO_AUTORIZADO)
        return
    await context.bot.send_message(chat_id, _TEXTO_START)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help: ejemplos de preguntas reales y lista de comandos."""
    chat_id = update.effective_chat.id
    if not is_allowed(chat_id, settings.allowed_chat_ids):
        logger.warning("/help de chat NO autorizado: %s", chat_id)
        await context.bot.send_message(chat_id, _TEXTO_NO_AUTORIZADO)
        return
    await context.bot.send_message(chat_id, _TEXTO_HELP)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/reset: olvida la memoria conversacional de este chat.

    `memory.reset` es una operación en RAM (rápida), así que se llama directo, sin
    pasar por un hilo aparte.
    """
    chat_id = update.effective_chat.id
    if not is_allowed(chat_id, settings.allowed_chat_ids):
        logger.warning("/reset de chat NO autorizado: %s", chat_id)
        await context.bot.send_message(chat_id, _TEXTO_NO_AUTORIZADO)
        return
    memory.reset(chat_id)
    await context.bot.send_message(chat_id, _TEXTO_RESET)


def build_application() -> Application:
    """Construye la `Application` de python-telegram-bot con sus handlers.

    Registra los comandos (/start, /help, /reset) y el handler de texto (cualquier
    mensaje de texto que NO sea un comando). El arranque/parada de la Application y
    el registro del webhook los gestiona `app/main.py` (FastAPI).
    """
    application = ApplicationBuilder().token(settings.telegram_bot_token).build()

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("reset", cmd_reset))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )

    return application
