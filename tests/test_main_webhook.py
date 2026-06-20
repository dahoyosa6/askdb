"""Pruebas del servidor FastAPI del webhook (Fase 6).

Síncrono, sin red ni DB: se usa `fastapi.testclient.TestClient` (que dispara el
lifespan async internamente) con una `Application` de Telegram FALSA cuyos métodos
de ciclo de vida y de proceso son `AsyncMock`. Así verificamos:
- GET / (health) -> 200.
- POST /webhook con secreto correcto -> 200 y se llamó a process_update.
- POST /webhook con secreto ausente/incorrecto -> 403.
- POST /webhook con webhook_secret vacío -> 403 (fallo cerrado).

Para no llamar al `set_webhook` real (que requeriría red), se deja
`settings.webhook_url` vacío durante el arranque.
"""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import app.main as main_mod
from config import settings


def _settings_con(monkeypatch, *, webhook_url: str = "", webhook_secret: str = "") -> None:
    """Reemplaza el `settings` que usa app.main por una copia con estos valores.

    `Settings` es frozen, así que no se le puede asignar un campo. En su lugar
    creamos una copia inmutable con `dataclasses.replace` y la inyectamos en el
    módulo `app.main` (monkeypatch la restaura al terminar el test).
    """
    reemplazo = dataclasses.replace(
        settings, webhook_url=webhook_url, webhook_secret=webhook_secret
    )
    monkeypatch.setattr(main_mod, "settings", reemplazo)


def _fake_application() -> MagicMock:
    """Una Application de Telegram falsa: métodos de ciclo de vida = AsyncMock."""
    fake = MagicMock()
    fake.initialize = AsyncMock()
    fake.start = AsyncMock()
    fake.stop = AsyncMock()
    fake.shutdown = AsyncMock()
    fake.process_update = AsyncMock()
    fake.bot = MagicMock()
    fake.bot.set_webhook = AsyncMock()
    return fake


@pytest.fixture
def fake_app(monkeypatch):
    """Parchea build_application y deja webhook_url vacío (no se llama set_webhook).

    Devuelve la Application falsa para poder hacer aserciones sobre sus AsyncMock.
    Como Update.de_json requiere un bot válido para parsear, también parcheamos
    Update.de_json para devolver un centinela inocuo.
    """
    fake = _fake_application()
    monkeypatch.setattr(main_mod, "build_application", lambda: fake)
    # Evita el set_webhook real durante el lifespan (webhook_url vacío).
    _settings_con(monkeypatch, webhook_url="", webhook_secret="")
    # de_json no debe tocar la red ni validar el bot falso.
    monkeypatch.setattr(main_mod.Update, "de_json", staticmethod(lambda data, bot: object()))
    return fake


def test_health_ok(fake_app):
    with TestClient(main_mod.app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_webhook_con_secreto_correcto_procesa(fake_app, monkeypatch):
    """Header correcto -> 200 y process_update llamado exactamente una vez."""
    _settings_con(monkeypatch, webhook_url="", webhook_secret="s3cr3t")
    with TestClient(main_mod.app) as client:
        resp = client.post(
            "/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "s3cr3t"},
        )
    assert resp.status_code == 200
    assert fake_app.process_update.await_count == 1


def test_webhook_header_incorrecto_es_403(fake_app, monkeypatch):
    _settings_con(monkeypatch, webhook_url="", webhook_secret="s3cr3t")
    with TestClient(main_mod.app) as client:
        resp = client.post(
            "/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "otro"},
        )
    assert resp.status_code == 403
    assert fake_app.process_update.await_count == 0


def test_webhook_sin_header_es_403(fake_app, monkeypatch):
    _settings_con(monkeypatch, webhook_url="", webhook_secret="s3cr3t")
    with TestClient(main_mod.app) as client:
        resp = client.post("/webhook", json={"update_id": 1})
    assert resp.status_code == 403
    assert fake_app.process_update.await_count == 0


def test_webhook_secreto_vacio_es_403_fallo_cerrado(fake_app, monkeypatch):
    """Sin webhook_secret configurado, todo update se rechaza (fallo cerrado)."""
    _settings_con(monkeypatch, webhook_url="", webhook_secret="")
    with TestClient(main_mod.app) as client:
        resp = client.post(
            "/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "loquesea"},
        )
    assert resp.status_code == 403
    assert fake_app.process_update.await_count == 0
