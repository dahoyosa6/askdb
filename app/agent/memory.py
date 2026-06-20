"""Memoria conversacional corta en RAM, indexada por `chat_id` (Fase 5).

Guarda el historial reciente de cada conversación para que el modelo entienda
follow-ups ("¿y el mes pasado?") sin que el usuario repita el contexto. El
historial se almacena en el formato de mensajes de la API de Anthropic
(`{"role": ..., "content": ...}`) listo para pasarlo a `generate_sql`.

Por turno se guardan DOS mensajes: la pregunta del usuario (`role="user"`) y el
SQL que finalmente se ejecutó (`role="assistant"`, en TEXTO PLANO, sin prefijo).
El SQL en memoria es INTERNO: nunca se expone al usuario (regla dura del
proyecto). El historial se recorta a los últimos `settings.memory_window`
mensajes para acotar tokens y mantener el prefijo de caché estable.

Limitación conocida (v1): el store vive SOLO en memoria del proceso. Implica:
- **Single-process:** no se comparte entre varios workers/instancias.
- **Sin persistencia:** se pierde por completo al reiniciar la app.
- **Sin locking:** no es seguro ante concurrencia real (no hay candados).
Para multi-instancia o persistencia (p. ej. Redis/Postgres) → v2.

Funciones públicas:
- `get_history(chat_id)` -> copia del historial (lista vacía si no hay).
- `append_turn(chat_id, question, sql)` -> añade el turno y recorta a la ventana.
- `reset(chat_id)` -> olvida ese chat (idempotente).
- `clear_all()` -> vacía todo el store (útil para aislar tests).
"""

from __future__ import annotations

from config import settings

# Store en RAM: chat_id -> lista de mensajes {"role", "content"}. Es un singleton
# a nivel de módulo; se pierde al reiniciar el proceso (ver limitación arriba).
_STORE: dict[int, list[dict[str, str]]] = {}


def get_history(chat_id: int) -> list[dict[str, str]]:
    """Devuelve una COPIA del historial del chat (lista vacía si no existe).

    Se devuelve una copia defensiva (lista nueva + dicts nuevos) para que mutar
    el resultado NO altere el store interno. Así el llamador puede manipular el
    historial sin efectos colaterales sobre la memoria.
    """
    mensajes = _STORE.get(chat_id, [])
    # Copia profunda ligera: lista nueva con un dict nuevo por mensaje.
    return [dict(m) for m in mensajes]


def append_turn(chat_id: int, question: str, sql: str) -> None:
    """Añade un turno (pregunta + SQL ejecutado) y recorta a la ventana.

    Guarda `{"role": "user", "content": question}` seguido de
    `{"role": "assistant", "content": sql}` (el SQL va en TEXTO PLANO, sin
    prefijo). Después recorta el historial a los últimos `settings.memory_window`
    mensajes. La ventana se lee EN RUNTIME (no se captura al importar) para que
    los tests puedan monkeypatchearla.
    """
    historial = _STORE.setdefault(chat_id, [])
    historial.append({"role": "user", "content": question})
    historial.append({"role": "assistant", "content": sql})

    # Recorte a la ventana móvil: nos quedamos con los mensajes más recientes.
    # Leemos settings.memory_window aquí (runtime) para que sea monkeypatcheable.
    _STORE[chat_id] = historial[-settings.memory_window :]


def reset(chat_id: int) -> None:
    """Olvida el historial de un chat. Idempotente (no falla si no existe)."""
    _STORE.pop(chat_id, None)


def clear_all() -> None:
    """Vacía TODO el store. Pensado para aislar tests entre sí."""
    _STORE.clear()
