"""Transcripción de voz: nota de voz (bytes) -> texto (Fase 7).

Esta es la **interfaz intercambiable** de transcripción del proyecto: hoy usa
Groq Whisper, pero cambiar de proveedor (OpenAI Whisper, un modelo local, etc.)
solo implica reescribir esta función, sin tocar el bot de Telegram. El bot solo
conoce `transcribe(audio_bytes) -> str`; nada más.

El SDK de Groq es SÍNCRONO, así que esta función también lo es. Es I/O
bloqueante (sube el audio a la API), por lo que el handler async la corre en un
hilo aparte con `asyncio.to_thread`.

Manejo de errores (regla dura del proyecto):
- Si la API de Groq falla, la excepción se PROPAGA: el handler del bot la captura
  y le entrega al usuario un mensaje saneado (nunca el error interno).
- Si falta `GROQ_API_KEY`, se lanza un error claro antes de tocar la red (igual
  que `get_client()` con la key de Anthropic).
"""

from __future__ import annotations

import logging

from groq import Groq

from config import settings

logger = logging.getLogger(__name__)

# Cliente Groq singleton perezoso: se crea en la primera transcripción y se
# reutiliza (mismo patrón que el pool de DB y el cliente de Anthropic). Evita
# construir un cliente HTTP nuevo por cada nota de voz.
_CLIENT: Groq | None = None


def _get_client() -> Groq:
    """Devuelve el cliente Groq, creándolo en el primer uso (singleton)."""
    global _CLIENT
    if _CLIENT is None:
        if not settings.groq_api_key:
            raise RuntimeError(
                "Falta GROQ_API_KEY en el entorno (.env). No se puede transcribir "
                "la nota de voz."
            )
        _CLIENT = Groq(api_key=settings.groq_api_key)
    return _CLIENT


def transcribe(audio_bytes: bytes, *, filename: str = "audio.ogg") -> str:
    """Transcribe una nota de voz a texto en español usando Groq Whisper.

    Args:
        audio_bytes: contenido binario del audio (p. ej. el OGG de Telegram).
        filename: nombre lógico del archivo; Groq lo usa para inferir el formato.

    Returns:
        El texto transcrito, recortado con `.strip()`.

    Raises:
        RuntimeError: si falta `GROQ_API_KEY` en el entorno.
        Exception: cualquier error de la API de Groq se propaga al llamador.
    """
    client = _get_client()
    transcripcion = client.audio.transcriptions.create(
        file=(filename, audio_bytes),
        model=settings.groq_whisper_model,
        language="es",
    )
    return transcripcion.text.strip()
