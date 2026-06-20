"""Pruebas de la transcripción de voz (Fase 7).

Todo SÍNCRONO (el SDK de Groq es síncrono; no se usa pytest-asyncio). Se
monkeypatchea el cliente Groq a nivel de módulo (`transcribe.Groq`) por una
clase falsa cuyo `.audio.transcriptions.create(**kwargs)` captura los kwargs y
devuelve un objeto con `.text`. NUNCA se toca la red ni se llama a Groq de
verdad.
"""

from __future__ import annotations

import dataclasses

import pytest

import app.transcription.transcribe as tr
from config import settings


# ---------------------------------------------------------------------------
# Doble de prueba del cliente Groq
# ---------------------------------------------------------------------------


class _FakeTranscriptions:
    """Falso `client.audio.transcriptions`: captura los kwargs de `create`."""

    def __init__(self, captura: dict, texto: str, *, lanzar: Exception | None = None):
        self._captura = captura
        self._texto = texto
        self._lanzar = lanzar

    def create(self, **kwargs):
        self._captura.update(kwargs)
        if self._lanzar is not None:
            raise self._lanzar

        class _Resp:
            text = self._texto

        return _Resp()


class _FakeAudio:
    def __init__(self, transcriptions: _FakeTranscriptions):
        self.transcriptions = transcriptions


def _fake_groq_factory(captura: dict, texto: str, *, lanzar: Exception | None = None):
    """Devuelve una clase falsa que sustituye a `Groq` en el módulo."""

    class _FakeGroq:
        def __init__(self, *args, **kwargs):
            self.audio = _FakeAudio(
                _FakeTranscriptions(captura, texto, lanzar=lanzar)
            )

    return _FakeGroq


@pytest.fixture(autouse=True)
def _con_api_key(monkeypatch):
    """Por defecto, los tests corren con una API key presente (salvo el que la quita).

    Además resetea el cliente Groq singleton (`tr._CLIENT`) antes y después de cada
    test, para que cada uno instancie su propio doble de prueba (`tr.Groq`).
    """
    tr._CLIENT = None
    monkeypatch.setattr(
        tr, "settings", dataclasses.replace(settings, groq_api_key="gsk_test")
    )
    yield
    tr._CLIENT = None


# ---------------------------------------------------------------------------
# transcribe
# ---------------------------------------------------------------------------


def test_transcribe_devuelve_texto_con_strip(monkeypatch):
    """Devuelve el texto de la API, recortado con .strip()."""
    captura: dict = {}
    monkeypatch.setattr(
        tr, "Groq", _fake_groq_factory(captura, "  Hola mundo  ")
    )

    resultado = tr.transcribe(b"audio-bytes")

    assert resultado == "Hola mundo"


def test_transcribe_pasa_modelo_idioma_y_file(monkeypatch):
    """Pasa model, language='es' y el file=(filename, audio_bytes) correctos."""
    captura: dict = {}
    monkeypatch.setattr(tr, "Groq", _fake_groq_factory(captura, "ok"))
    # Aseguramos un modelo conocido en el settings del módulo.
    monkeypatch.setattr(
        tr,
        "settings",
        dataclasses.replace(
            settings, groq_api_key="gsk_test", groq_whisper_model="whisper-test"
        ),
    )

    tr.transcribe(b"datos", filename="nota.ogg")

    assert captura["model"] == "whisper-test"
    assert captura["language"] == "es"
    assert captura["file"] == ("nota.ogg", b"datos")


def test_transcribe_filename_por_defecto(monkeypatch):
    """Sin filename explícito usa 'audio.ogg'."""
    captura: dict = {}
    monkeypatch.setattr(tr, "Groq", _fake_groq_factory(captura, "ok"))

    tr.transcribe(b"datos")

    assert captura["file"] == ("audio.ogg", b"datos")


def test_transcribe_propaga_error_de_la_api(monkeypatch):
    """Si la API falla, la excepción se propaga (el handler la captura)."""
    captura: dict = {}
    boom = RuntimeError("groq cayó")
    monkeypatch.setattr(
        tr, "Groq", _fake_groq_factory(captura, "", lanzar=boom)
    )

    with pytest.raises(RuntimeError, match="groq cayó"):
        tr.transcribe(b"datos")


def test_transcribe_error_claro_si_falta_api_key(monkeypatch):
    """Sin GROQ_API_KEY, error claro ANTES de tocar la red."""
    monkeypatch.setattr(
        tr, "settings", dataclasses.replace(settings, groq_api_key="")
    )
    # Si llegara a instanciar Groq, esto lo delataría (no debería ocurrir).
    captura: dict = {}
    monkeypatch.setattr(tr, "Groq", _fake_groq_factory(captura, "no-debe-usarse"))

    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        tr.transcribe(b"datos")

    assert captura == {}  # no se llamó a la API


def test_cliente_groq_es_singleton(monkeypatch):
    """B5: dos transcripciones reutilizan UN solo cliente Groq (no uno por llamada)."""
    captura: dict = {}
    instancias = {"n": 0}

    base = _fake_groq_factory(captura, "ok")

    class _ContandoGroq(base):
        def __init__(self, *args, **kwargs):
            instancias["n"] += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(tr, "Groq", _ContandoGroq)

    tr.transcribe(b"uno")
    tr.transcribe(b"dos")

    assert instancias["n"] == 1  # se construyó una sola vez
