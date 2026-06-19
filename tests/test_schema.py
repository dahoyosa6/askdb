"""Pruebas de introspección del esquema (Fase 1).

Son pruebas de integración: requieren DATABASE_URL (rol read-only) en .env, igual
que tests/test_conn.py. Se omiten automáticamente si no hay conexión configurada.
"""

from __future__ import annotations

import psycopg
import pytest

from config import settings

from app.agent.schema import format_schema_for_prompt, introspect_schema

pytestmark = pytest.mark.skipif(
    not settings.database_url, reason="DATABASE_URL no configurada (.env)"
)

# Las 14 tablas de Northwind (snake/plural) que carga la Fase 0.
EXPECTED_TABLES = {
    "categories",
    "customers",
    "employees",
    "employee_territories",
    "orders",
    "order_details",
    "products",
    "suppliers",
    "shippers",
    "region",
    "territories",
    "us_states",
    "customer_demographics",
    "customer_customer_demo",
}


@pytest.fixture(scope="module")
def conn():
    with psycopg.connect(settings.database_url, connect_timeout=15) as c:
        yield c


@pytest.fixture(scope="module")
def schema(conn):
    return introspect_schema(conn)


def test_encuentra_las_14_tablas(schema):
    tables = set(schema["tables"].keys())
    # Deben estar al menos las 14 esperadas (puede haber más, pero no menos).
    faltantes = EXPECTED_TABLES - tables
    assert not faltantes, f"Faltan tablas en la introspección: {faltantes}"
    assert len(tables) >= 14


# Northwind en Neon SÍ tiene constraints (14 PK + 13 FK). La introspección las
# lee de pg_catalog (no de information_schema, que sale vacío bajo un rol de
# solo-SELECT). Estas pruebas verifican que efectivamente las recoge.


def test_encuentra_las_fks(schema):
    total_fks = sum(
        len(info["foreign_keys"]) for info in schema["tables"].values()
    )
    assert total_fks >= 13, f"Se esperaban >=13 FK, se encontraron {total_fks}."


def test_order_details_referencia_orders_y_products(schema):
    fks = schema["tables"]["order_details"]["foreign_keys"]
    ref_tables = {fk["ref_table"] for fk in fks}
    assert "orders" in ref_tables
    assert "products" in ref_tables


def test_orders_tiene_pk(schema):
    # orders debe tener order_id como llave primaria.
    assert "orders" in schema["tables"]
    assert "order_id" in schema["tables"]["orders"]["primary_key"]


def test_introspeccion_lee_columnas_de_orders(schema):
    # Verifica el MECANISMO de introspección (independiente de constraints):
    # orders debe tener sus columnas y tipos leídos correctamente.
    assert "orders" in schema["tables"]
    col_names = {c["name"] for c in schema["tables"]["orders"]["columns"]}
    assert "order_id" in col_names
    assert "customer_id" in col_names


def test_formato_para_prompt_no_vacio_y_contiene_orders(schema):
    formatted = format_schema_for_prompt(schema)
    assert formatted.strip(), "El esquema formateado está vacío."
    assert "orders" in formatted
    # El formato compacto debe arrancar cada tabla con 'TABLE '.
    assert "TABLE orders(" in formatted
