"""Pruebas de la Fase 2 — guardrails de seguridad (`validate_and_secure`).

Son pruebas PURAS de validación de strings: NO requieren base de datos ni red.
Cubren tres frentes:
  1. Camino feliz: SELECT/CTE legítimos se aceptan y se les inyecta LIMIT.
  2. Bloqueo: cualquier escritura/DDL/admin o múltiple sentencia se rechaza.
  3. Adversarial: intentos de "contrabandear" una escritura (data-modifying CTE,
     comentarios, mayúsculas raras, etc.) — y falsos positivos (palabra peligrosa
     dentro de un literal) que NO deben bloquearse.

Recordatorio de arquitectura: la barrera no-evitable es el rol read-only de la DB
(ya probado en tests/test_conn.py). Esta capa es defensa en profundidad + LIMIT.
"""

from __future__ import annotations

import pytest

from app.agent.validate_sql import SQLValidationError, validate_and_secure
from config import settings

CAP = settings.query_row_hard_cap  # 1000 por defecto


# ---------------------------------------------------------------------------
# 1. ACEPTA — SELECT / CTE legítimos (no deben lanzar)
# ---------------------------------------------------------------------------

SELECTS_VALIDOS = [
    pytest.param("SELECT 1", id="select-trivial"),
    pytest.param("SELECT * FROM customers", id="select-simple"),
    pytest.param(
        "SELECT c.country, count(*) AS n "
        "FROM customers c JOIN orders o ON o.customer_id = c.customer_id "
        "GROUP BY c.country ORDER BY n DESC",
        id="join-agregacion-groupby-orderby",
    ),
    pytest.param(
        "WITH ventas AS (SELECT customer_id, count(*) n FROM orders GROUP BY customer_id) "
        "SELECT * FROM ventas WHERE n > 5",
        id="cte-with-as-select",
    ),
    pytest.param("SELECT 1 UNION SELECT 2", id="union"),
    pytest.param(
        "SELECT * FROM (SELECT customer_id FROM orders) AS q", id="subconsulta"
    ),
    pytest.param(
        "SELECT order_id, row_number() OVER (ORDER BY order_id) FROM orders",
        id="funcion-de-ventana",
    ),
]


@pytest.mark.parametrize("sql", SELECTS_VALIDOS)
def test_acepta_selects_validos(sql):
    """Un SELECT/CTE legítimo no lanza y devuelve un string no vacío."""
    out = validate_and_secure(sql)
    assert isinstance(out, str)
    assert out.strip()


# ---------------------------------------------------------------------------
# 2. INYECCIÓN DE LIMIT
# ---------------------------------------------------------------------------

def test_inyecta_limit_cuando_falta():
    """Un SELECT sin LIMIT sale con 'LIMIT <cap>' (cap = query_row_hard_cap)."""
    out = validate_and_secure("SELECT * FROM orders")
    assert f"LIMIT {CAP}" in out.upper()


def test_respeta_limit_propio_y_no_duplica():
    """Un SELECT con 'LIMIT 5' propio conserva el 5 y NO añade otro LIMIT."""
    out = validate_and_secure("SELECT * FROM orders LIMIT 5")
    assert out.upper().count("LIMIT") == 1
    assert "LIMIT 5" in out.upper()
    assert f"LIMIT {CAP}" not in out.upper()


def test_limit_respeta_max_limit_parametro():
    """El parámetro max_limit sobreescribe el cap por defecto."""
    out = validate_and_secure("SELECT * FROM orders", max_limit=10)
    assert "LIMIT 10" in out.upper()


def test_respeta_fetch_first_y_no_inyecta_limit():
    """`FETCH FIRST n ROWS ONLY` cuenta como tope: NO se le añade un LIMIT extra.

    Si se inyectara `LIMIT` tras `FETCH FIRST ... ROWS ONLY` el SQL sería inválido
    en Postgres (M3). El validador debe detectar el FETCH a nivel superior.
    """
    out = validate_and_secure("SELECT * FROM orders ORDER BY order_id FETCH FIRST 5 ROWS ONLY")
    assert "LIMIT" not in out.upper()
    assert "FETCH" in out.upper()


def test_fetch_first_con_offset_no_inyecta_limit():
    """`OFFSET ... FETCH FIRST ... ROWS ONLY` también cuenta como tope."""
    out = validate_and_secure(
        "SELECT * FROM orders ORDER BY order_id OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY"
    )
    assert "LIMIT" not in out.upper()
    assert "FETCH" in out.upper()


# ---------------------------------------------------------------------------
# 3. BLOQUEA — escrituras, DDL y comandos admin (deben lanzar)
# ---------------------------------------------------------------------------

SQL_PELIGROSO = [
    pytest.param("DELETE FROM customers WHERE 1=0", id="delete"),
    pytest.param("UPDATE orders SET freight = 0", id="update"),
    pytest.param("INSERT INTO orders DEFAULT VALUES", id="insert"),
    pytest.param("DROP TABLE orders", id="drop-table"),
    pytest.param("ALTER TABLE orders ADD COLUMN x int", id="alter-table"),
    pytest.param("CREATE TABLE x (id int)", id="create-table"),
    pytest.param("TRUNCATE orders", id="truncate"),
    pytest.param("GRANT SELECT ON orders TO public", id="grant"),
    pytest.param("REVOKE SELECT ON orders FROM public", id="revoke"),
    pytest.param("SELECT 1; DROP TABLE orders", id="multiple-sentencias"),
    pytest.param("SELECT * INTO nueva_tabla FROM customers", id="select-into"),
    pytest.param("EXPLAIN SELECT * FROM orders", id="empieza-por-explain"),
    pytest.param("SHOW search_path", id="empieza-por-show"),
    pytest.param("SET search_path TO public", id="empieza-por-set"),
]


@pytest.mark.parametrize("sql", SQL_PELIGROSO)
def test_bloquea_sql_peligroso(sql):
    """Cualquier escritura, DDL, comando admin o múltiple sentencia se rechaza."""
    with pytest.raises(SQLValidationError):
        validate_and_secure(sql)


def test_bloquea_vacio():
    """SQL vacío o solo espacios se rechaza."""
    with pytest.raises(SQLValidationError):
        validate_and_secure("   ")


# ---------------------------------------------------------------------------
# 4. NO FALSOS POSITIVOS — palabra peligrosa dentro de un literal (debe PASAR)
# ---------------------------------------------------------------------------

NO_FALSOS_POSITIVOS = [
    pytest.param(
        "SELECT * FROM customers WHERE contact_name = 'please delete'",
        id="literal-please-delete",
    ),
    pytest.param(
        "SELECT * FROM customers WHERE company_name LIKE '%DROP%'",
        id="like-con-DROP",
    ),
    pytest.param(
        "SELECT * FROM products WHERE product_name = 'INSERT cable'",
        id="literal-insert",
    ),
]


@pytest.mark.parametrize("sql", NO_FALSOS_POSITIVOS)
def test_no_bloquea_keyword_dentro_de_literal(sql):
    """Una palabra peligrosa DENTRO de un string no es un keyword: no se bloquea."""
    out = validate_and_secure(sql)
    assert out.strip()  # pasó sin lanzar


# ---------------------------------------------------------------------------
# 5. COMENTARIOS — se quitan; el keyword peligroso oculto NO sobrevive
# ---------------------------------------------------------------------------

def test_comentario_de_linea_se_elimina():
    """`SELECT 1 -- ; DELETE ...` pasa y el resultado NO contiene DELETE."""
    out = validate_and_secure("SELECT 1 -- ; DELETE FROM customers")
    assert "DELETE" not in out.upper()
    assert "SELECT" in out.upper()


def test_comentario_de_bloque_se_elimina():
    """`SELECT 1 /* DELETE */ FROM orders` pasa y el resultado NO contiene DELETE."""
    out = validate_and_secure("SELECT 1 /* DELETE */ FROM orders")
    assert "DELETE" not in out.upper()
    assert "SELECT" in out.upper()


# ---------------------------------------------------------------------------
# 6. ADVERSARIAL — intentos reales de contrabandear una escritura
# ---------------------------------------------------------------------------
# El vector más peligroso en Postgres: data-modifying CTE. Un `WITH x AS
# (DELETE ... RETURNING *) SELECT * FROM x` EMPIEZA por WITH (pasaría el filtro
# de "primera palabra") pero ESCRIBE en la tabla. El validador debe atraparlo
# por el escaneo de keywords prohibidas en los tokens.

CTE_QUE_ESCRIBEN = [
    pytest.param(
        "WITH x AS (DELETE FROM orders WHERE 1=0 RETURNING *) SELECT * FROM x",
        id="cte-delete-returning",
    ),
    pytest.param(
        "WITH x AS (UPDATE orders SET freight = 0 RETURNING *) SELECT * FROM x",
        id="cte-update-returning",
    ),
    pytest.param(
        "WITH x AS (INSERT INTO orders DEFAULT VALUES RETURNING *) SELECT * FROM x",
        id="cte-insert-returning",
    ),
    # Trucos de mayúsculas/minúsculas y espaciado raro sobre el mismo ataque.
    pytest.param(
        "with x as (delete from orders returning *) select * from x",
        id="cte-delete-minusculas",
    ),
    pytest.param(
        "WITH x AS (DeLeTe FROM orders RETURNING *) SELECT * FROM x",
        id="cte-delete-mixed-case",
    ),
    pytest.param(
        "WITH x AS (\n\tDELETE\tFROM orders RETURNING *\n) SELECT * FROM x",
        id="cte-delete-tabs-saltos",
    ),
]


@pytest.mark.parametrize("sql", CTE_QUE_ESCRIBEN)
def test_bloquea_cte_que_modifican_datos(sql):
    """Un data-modifying CTE empieza por WITH pero ESCRIBE: debe ser bloqueado.

    Postgres ejecuta el DELETE/UPDATE/INSERT del CTE aunque la sentencia empiece
    por WITH; si el validador lo aceptara, sería un AGUJERO DE SEGURIDAD real.
    """
    with pytest.raises(SQLValidationError):
        validate_and_secure(sql)


ADVERSARIAL_VARIOS = [
    pytest.param("SELECT * FROM orders FOR UPDATE", id="for-update-toma-locks"),
    pytest.param("COPY customers TO '/tmp/x.csv'", id="copy-to-archivo"),
    pytest.param("SELECT 1 ; SELECT 2", id="dos-selects-tambien-bloqueado"),
    pytest.param(
        "SELECT 1; /**/DROP TABLE orders", id="comentario-no-fusiona-sentencias"
    ),
]


@pytest.mark.parametrize("sql", ADVERSARIAL_VARIOS)
def test_bloquea_otros_vectores_adversariales(sql):
    """Otros vectores: FOR UPDATE (locks), COPY TO, y multi-sentencia disfrazada."""
    with pytest.raises(SQLValidationError):
        validate_and_secure(sql)


# ---------------------------------------------------------------------------
# 7. HALLAZGO documentado — pg_sleep PASA (no es escritura, pero sí DoS)
# ---------------------------------------------------------------------------
# No es un agujero de "escritura": pg_sleep no modifica datos, así que NO viola
# la garantía read-only de la Fase 2. PERO permite un ataque de denegación de
# servicio (bloquear el pool). La mitigación real es `statement_timeout` a nivel
# de conexión (Fase 1, ya documentado en CLAUDE.md). Se deja este test como
# DOCUMENTACIÓN del comportamiento actual: si en el futuro se decide bloquear
# funciones peligrosas por nombre en la capa de app, este test debe cambiar.

def test_documenta_pg_sleep_pasa_la_capa_de_app():
    """pg_sleep no es escritura → la capa de app lo acepta (mitigado por timeout)."""
    out = validate_and_secure("SELECT pg_sleep(10)")
    assert "PG_SLEEP" in out.upper()


# ---------------------------------------------------------------------------
# 8. DENYLIST DE FUNCIONES PELIGROSAS (defensa en profundidad — §5 del tester)
# ---------------------------------------------------------------------------
# Estas funciones leen archivos del servidor o hacen IO de red. NO modifican
# datos (no violan read-only), así que pasaban el validador y solo las cortaba el
# rol DB. Ahora la APP es también barrera: las rechaza por NOMBRE de función.

FUNCIONES_PELIGROSAS = [
    pytest.param("SELECT pg_read_file('/etc/passwd')", id="pg_read_file"),
    pytest.param("SELECT pg_read_binary_file('/etc/hosts')", id="pg_read_binary_file"),
    pytest.param("SELECT pg_ls_dir('/')", id="pg_ls_dir"),
    pytest.param("SELECT lo_import('/etc/hosts')", id="lo_import"),
    pytest.param("SELECT lo_export(1, '/tmp/x')", id="lo_export"),
    pytest.param("SELECT * FROM dblink('host=x', 'SELECT 1') AS t(a int)", id="dblink"),
]


@pytest.mark.parametrize("sql", FUNCIONES_PELIGROSAS)
def test_bloquea_funciones_peligrosas_por_nombre(sql):
    """Funciones de lectura de archivos / IO de red se rechazan en la capa app."""
    with pytest.raises(SQLValidationError):
        validate_and_secure(sql)


def test_pg_shadow_pasa_la_capa_de_app():
    """pg_shadow es una VISTA, no una función: la app la deja pasar (la corta el rol DB)."""
    out = validate_and_secure("SELECT * FROM pg_shadow")
    assert out.strip()


def test_denylist_no_falso_positivo_en_literal():
    """El nombre de una función peligrosa DENTRO de un literal NO debe bloquearse."""
    out = validate_and_secure(
        "SELECT * FROM products WHERE product_name = 'pg_read_file backup'"
    )
    assert out.strip()


def test_denylist_no_bloquea_columna_parecida():
    """Una columna/identificador que NO es una llamada a función no se bloquea."""
    # 'lo_importante' contiene 'lo_import' como substring: la detección por token
    # de nombre completo NO debe confundirlos.
    out = validate_and_secure("SELECT lo_importante FROM productos")
    assert out.strip()
