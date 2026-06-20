"""Servidor FastAPI de AskDB: recibe los updates de Telegram por WEBHOOK (Fase 6).

Modelo elegido: WEBHOOK (no polling). Telegram envía cada update como un POST a
`/webhook`; FastAPI lo recibe y se lo entrega a la `Application` de
python-telegram-bot para que sus handlers lo procesen.

Seguridad del webhook (regla dura):
- Telegram reenvía el secreto en la cabecera `X-Telegram-Bot-Api-Secret-Token`.
  `/webhook` rechaza con HTTP 403 cualquier petición sin esa cabecera o con un
  valor distinto al `settings.webhook_secret`.
- FALLO CERRADO: si `webhook_secret` está vacío (mal configurado), TODO se
  rechaza con 403. Mejor no atender que atender sin verificar el origen.

El ciclo de vida (lifespan) arranca y detiene la Application, registra el webhook
en Telegram (si hay `webhook_url`) y, al cerrar, libera el pool de conexiones a la
base de datos.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from telegram import Update

from app.agent.execute import close_pool
from app.interfaces.telegram_bot import build_application
from config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Arranca/detiene la Application de Telegram junto con FastAPI."""
    application = build_application()
    await application.initialize()
    await application.start()

    # Registramos el webhook en Telegram solo si tenemos una URL pública. Va
    # envuelto en try/except: si falla (token inválido, sin red, etc.) NO debe
    # tumbar el arranque del servidor; se loguea y se sigue.
    if settings.webhook_url:
        try:
            await application.bot.set_webhook(
                url=settings.webhook_url,
                secret_token=settings.webhook_secret or None,
                allowed_updates=["message"],
            )
            logger.info("Webhook registrado en Telegram: %s", settings.webhook_url)
        except Exception:  # noqa: BLE001 - el arranque no debe caer por esto
            logger.exception("No se pudo registrar el webhook en Telegram.")

    app.state.application = application
    try:
        yield
    finally:
        # Cierre ordenado: detenemos la Application y liberamos el pool de DB.
        await application.stop()
        await application.shutdown()
        close_pool()


app = FastAPI(title="AskDB", lifespan=lifespan)


@app.get("/")
async def health() -> dict[str, str]:
    """Health check para Railway (y para verificar que el servidor está vivo)."""
    return {"status": "ok"}


def _verificar_secreto(request: Request) -> bool:
    """Valida que la petición trae el secreto correcto de Telegram.

    FALLO CERRADO: si no hay `webhook_secret` configurado, devuelve False (se
    rechaza todo). Si la cabecera no coincide con el secreto, también False.
    """
    if not settings.webhook_secret:
        return False
    recibido = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    return recibido == settings.webhook_secret


@app.post("/webhook")
async def webhook(request: Request) -> JSONResponse:
    """Recibe un update de Telegram, lo verifica y lo procesa.

    Devuelve 403 si el secreto no es válido; 200 cuando el update se entrega a la
    Application para que sus handlers lo procesen.
    """
    if not _verificar_secreto(request):
        logger.warning("Webhook rechazado: secreto ausente o inválido.")
        return JSONResponse(status_code=403, content={"detail": "forbidden"})

    application = request.app.state.application
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return JSONResponse(status_code=200, content={"ok": True})
