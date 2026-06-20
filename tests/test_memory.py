"""Pruebas de la memoria conversacional corta en RAM (Fase 5).

No tocan red ni DB: es un store en memoria. Una fixture autouse limpia el store
antes de cada test para que no se filtre estado entre pruebas.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent import memory


@pytest.fixture(autouse=True)
def _limpiar_store():
    """Vacía el store antes de cada test para aislarlos."""
    memory.clear_all()


def test_append_y_get_respeta_orden():
    """Un turno guarda user y luego assistant, en ese orden."""
    memory.append_turn(1, "¿cuántos pedidos?", "SELECT count(*) FROM orders")

    historial = memory.get_history(1)
    assert historial == [
        {"role": "user", "content": "¿cuántos pedidos?"},
        {"role": "assistant", "content": "SELECT count(*) FROM orders"},
    ]


def test_get_history_chat_inexistente_es_lista_vacia():
    """Pedir el historial de un chat sin turnos devuelve []."""
    assert memory.get_history(999) == []


def test_recorte_a_la_ventana(monkeypatch):
    """Con ventana=4 y 3 turnos (6 mensajes), quedan los 2 turnos más recientes."""
    # `settings` es un dataclass frozen (no admite setattr en la instancia), así
    # que reemplazamos la referencia del módulo por un stub con la ventana a 4.
    monkeypatch.setattr(memory, "settings", SimpleNamespace(memory_window=4))

    memory.append_turn(1, "q1", "sql1")
    memory.append_turn(1, "q2", "sql2")
    memory.append_turn(1, "q3", "sql3")

    historial = memory.get_history(1)
    assert len(historial) == 4
    # Quedan los 2 turnos más recientes (q2/sql2 y q3/sql3), en orden.
    assert historial == [
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "sql2"},
        {"role": "user", "content": "q3"},
        {"role": "assistant", "content": "sql3"},
    ]


def test_chats_aislados():
    """El historial de un chat no contamina el de otro."""
    memory.append_turn(1, "q-chat-1", "sql-chat-1")
    memory.append_turn(2, "q-chat-2", "sql-chat-2")

    assert memory.get_history(1) == [
        {"role": "user", "content": "q-chat-1"},
        {"role": "assistant", "content": "sql-chat-1"},
    ]
    assert memory.get_history(2) == [
        {"role": "user", "content": "q-chat-2"},
        {"role": "assistant", "content": "sql-chat-2"},
    ]


def test_reset_limpia_y_es_idempotente():
    """reset olvida el chat y no falla si el chat no existe."""
    memory.append_turn(1, "q", "sql")
    memory.reset(1)
    assert memory.get_history(1) == []

    # Idempotente: reset sobre un chat inexistente no lanza error.
    memory.reset(1)
    memory.reset(12345)
    assert memory.get_history(1) == []


def test_get_history_devuelve_copia():
    """Mutar el resultado de get_history no afecta un segundo get_history."""
    memory.append_turn(1, "q", "sql")

    primero = memory.get_history(1)
    primero.append({"role": "user", "content": "intruso"})
    primero[0]["content"] = "modificado"

    segundo = memory.get_history(1)
    assert segundo == [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "sql"},
    ]
