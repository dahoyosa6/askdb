"""Pruebas de la Fase 0 — conexión y seguridad a nivel de base de datos.

Son pruebas de integración: requieren DATABASE_URL (rol read-only) en .env.
Se omiten automáticamente si no hay conexión configurada.
"""

from __future__ import annotations

import psycopg
import pytest

from config import settings

pytestmark = pytest.mark.skipif(
    not settings.database_url, reason="DATABASE_URL no configurada (.env)"
)


@pytest.fixture(scope="module")
def conn():
    with psycopg.connect(settings.database_url, connect_timeout=15) as c:
        yield c


def test_conecta_como_rol_readonly(conn):
    user = conn.execute("SELECT current_user").fetchone()[0]
    assert user == "askdb_readonly"


def test_northwind_poblado(conn):
    n = conn.execute("SELECT count(*) FROM orders").fetchone()[0]
    assert n > 0


def test_las_14_tablas_existen(conn):
    n = conn.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchone()[0]
    assert n >= 14


def test_la_db_bloquea_escritura(conn):
    """Doble cinturón: aunque la app fallara, la DB rechaza un DELETE."""
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM customers WHERE 1=0")
    conn.rollback()
