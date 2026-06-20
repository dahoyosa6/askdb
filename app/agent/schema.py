"""Introspección del esquema de la base de datos.

Lee tablas, columnas y tipos de `information_schema` y las llaves primarias (PK)
y foráneas (FK) del catálogo del sistema `pg_catalog` de Postgres, y los convierte
en un texto compacto tipo DDL listo para inyectar al modelo. Northwind es estático,
así que el resultado se cachea en memoria y se vuelca a disco (gitignored).

NOTA (trampa de la Fase 1): las PK/FK se leen de `pg_catalog`, NO de las vistas de
constraints de `information_schema`. Esas vistas salen VACÍAS para un rol de
solo-SELECT (ver el comentario extenso dentro de `introspect_schema`).

Funciones públicas:
- `introspect_schema(conn)`  -> estructura cruda (dict) del esquema.
- `format_schema_for_prompt(schema)` -> texto compacto para el prompt de Claude.
- `get_schema(conn=None, *, refresh=False)` -> texto cacheado (memoria + disco).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import psycopg

from config import settings

logger = logging.getLogger(__name__)

# Cache en memoria del esquema formateado (texto DDL). Northwind no cambia, así
# que una vez calculado se reutiliza durante toda la vida del proceso.
_SCHEMA_CACHE: str | None = None


def introspect_schema(conn: psycopg.Connection) -> dict[str, Any]:
    """Lee la estructura del esquema `public`.

    Columnas y tipos salen de `information_schema.columns`; las PK/FK salen de
    `pg_catalog` (las vistas de constraints de information_schema están vacías
    para el rol de solo-SELECT — ver el comentario más abajo).

    Devuelve un dict con esta forma::

        {
            "tables": {
                "orders": {
                    "columns": [
                        {"name": "order_id", "type": "integer"},
                        {"name": "customer_id", "type": "character varying"},
                        ...
                    ],
                    "primary_key": ["order_id"],
                    "foreign_keys": [
                        {"column": "customer_id",
                         "ref_table": "customers",
                         "ref_column": "customer_id"},
                        ...
                    ],
                },
                ...
            }
        }

    No silencia errores: si la consulta falla, el error de psycopg se propaga.
    """
    tables: dict[str, dict[str, Any]] = {}

    # --- 1. Columnas y tipos (ordenadas por posición para un DDL legible) ---
    columns_sql = """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """
    with conn.cursor() as cur:
        cur.execute(columns_sql)
        for table_name, column_name, data_type in cur.fetchall():
            table = tables.setdefault(
                table_name,
                {"columns": [], "primary_key": [], "foreign_keys": []},
            )
            table["columns"].append({"name": column_name, "type": data_type})

    logger.info("Introspección: %d tablas encontradas en esquema public.", len(tables))

    # IMPORTANTE: las vistas de constraints de information_schema
    # (table_constraints/key_column_usage) SOLO muestran filas de tablas donde el
    # rol actual tiene un privilegio DISTINTO de SELECT. Como la app se conecta con
    # un rol de solo-SELECT (askdb_readonly), esas vistas salen VACÍAS. Por eso
    # leemos las PK/FK del catálogo del sistema (pg_catalog), visible para todos.

    # --- 2. Llaves primarias (PK) ---
    # unnest(conkey) WITH ORDINALITY preserva el orden de claves compuestas.
    pk_sql = """
        SELECT cl.relname AS table_name, att.attname AS column_name
        FROM pg_constraint con
        JOIN pg_class cl ON cl.oid = con.conrelid
        JOIN pg_namespace ns ON ns.oid = cl.relnamespace
        JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord) ON true
        JOIN pg_attribute att
          ON att.attrelid = con.conrelid AND att.attnum = k.attnum
        WHERE con.contype = 'p' AND ns.nspname = 'public'
        ORDER BY cl.relname, k.ord
    """
    with conn.cursor() as cur:
        cur.execute(pk_sql)
        for table_name, column_name in cur.fetchall():
            if table_name in tables:
                tables[table_name]["primary_key"].append(column_name)

    # --- 3. Llaves foráneas (FK) ---
    # conkey = columnas locales, confkey = columnas referenciadas; se emparejan
    # por posición con unnest de ambos arrays.
    fk_sql = """
        SELECT
            cl.relname   AS local_table,
            att.attname  AS local_column,
            fcl.relname  AS ref_table,
            fatt.attname AS ref_column
        FROM pg_constraint con
        JOIN pg_class cl  ON cl.oid = con.conrelid
        JOIN pg_namespace ns ON ns.oid = cl.relnamespace
        JOIN pg_class fcl ON fcl.oid = con.confrelid
        JOIN LATERAL unnest(con.conkey, con.confkey) WITH ORDINALITY
             AS k(attnum, fattnum, ord) ON true
        JOIN pg_attribute att
          ON att.attrelid = con.conrelid AND att.attnum = k.attnum
        JOIN pg_attribute fatt
          ON fatt.attrelid = con.confrelid AND fatt.attnum = k.fattnum
        WHERE con.contype = 'f' AND ns.nspname = 'public'
        ORDER BY cl.relname, k.ord
    """
    with conn.cursor() as cur:
        cur.execute(fk_sql)
        for local_table, local_column, ref_table, ref_column in cur.fetchall():
            if local_table in tables:
                tables[local_table]["foreign_keys"].append(
                    {
                        "column": local_column,
                        "ref_table": ref_table,
                        "ref_column": ref_column,
                    }
                )

    return {"tables": tables}


def format_schema_for_prompt(schema: dict[str, Any]) -> str:
    """Convierte el dict del esquema en texto compacto tipo DDL.

    Formato por tabla (una línea por tabla)::

        TABLE orders(order_id int PK, customer_id varchar -> customers.customer_id,
                     order_date date, ...)

    Mucho más barato en tokens que volcar el JSON crudo, y le da a Claude las
    relaciones (FK) explícitas para que no alucine joins.
    """
    tables = schema.get("tables", {})
    lines: list[str] = []

    for table_name in sorted(tables):
        info = tables[table_name]
        pk_set = set(info.get("primary_key", []))
        # Indexamos las FK por columna local para anotar la flecha -> destino.
        fk_by_column = {
            fk["column"]: f"{fk['ref_table']}.{fk['ref_column']}"
            for fk in info.get("foreign_keys", [])
        }

        col_parts: list[str] = []
        for col in info.get("columns", []):
            name = col["name"]
            short_type = _shorten_type(col["type"])
            part = f"{name} {short_type}"
            if name in pk_set:
                part += " PK"
            if name in fk_by_column:
                part += f" -> {fk_by_column[name]}"
            col_parts.append(part)

        lines.append(f"TABLE {table_name}({', '.join(col_parts)})")

    return "\n".join(lines)


def _shorten_type(data_type: str) -> str:
    """Abrevia el tipo Postgres (de information_schema.columns) a una forma corta.

    `character varying` -> `varchar`, `timestamp without time zone` -> `timestamp`,
    etc. Reduce tokens sin perder el significado para generar SQL.
    """
    mapping = {
        "character varying": "varchar",
        "character": "char",
        "integer": "int",
        "smallint": "smallint",
        "bigint": "bigint",
        "numeric": "numeric",
        "double precision": "double",
        "real": "real",
        "boolean": "bool",
        "timestamp without time zone": "timestamp",
        "timestamp with time zone": "timestamptz",
        "time without time zone": "time",
        "date": "date",
        "text": "text",
    }
    return mapping.get(data_type, data_type.replace(" ", "_"))


def get_schema(
    conn: psycopg.Connection | None = None,
    *,
    refresh: bool = False,
) -> str:
    """Devuelve el esquema formateado (texto DDL), con cache en memoria y disco.

    Orden de resolución:
    1. Si hay cache en memoria y no se pide refresh, se devuelve esa.
    2. Si existe el archivo de cache en disco y no se pide refresh, se carga.
    3. Si no, se introspecciona la DB (requiere `conn`), se formatea, y se
       guarda tanto en memoria como en disco.

    `conn` solo es obligatoria cuando hay que introspeccionar de verdad (sin
    cache disponible o con refresh=True).
    """
    global _SCHEMA_CACHE

    if _SCHEMA_CACHE is not None and not refresh:
        logger.debug("get_schema: usando cache en memoria.")
        return _SCHEMA_CACHE

    cache_path = settings.schema_cache_path

    # Intentar cargar desde disco si no se fuerza refresh.
    if not refresh and os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                cached = json.load(f)
            formatted = cached.get("formatted")
            if formatted:
                logger.info("get_schema: cache cargada desde %s.", cache_path)
                _SCHEMA_CACHE = formatted
                return formatted
            logger.warning(
                "get_schema: cache en %s sin clave 'formatted'; reintrospección.",
                cache_path,
            )
        except (OSError, json.JSONDecodeError) as exc:
            # No silenciamos: avisamos y caemos a reintrospección.
            logger.warning(
                "get_schema: no se pudo leer la cache %s (%s); reintrospección.",
                cache_path,
                exc,
            )

    # Hay que introspeccionar. Si no nos dieron conexión, abrimos una corta con
    # el rol read-only (DATABASE_URL); el resultado queda cacheado, así que esto
    # ocurre a lo sumo una vez por entorno.
    logger.info("get_schema: introspeccionando la base de datos...")
    if conn is not None:
        schema = introspect_schema(conn)
    else:
        if not settings.database_url:
            raise RuntimeError(
                "get_schema necesita introspeccionar pero falta DATABASE_URL "
                "(.env) y no se pasó una conexión."
            )
        with psycopg.connect(settings.database_url, connect_timeout=15) as own_conn:
            schema = introspect_schema(own_conn)
    formatted = format_schema_for_prompt(schema)

    # Guardar en memoria.
    _SCHEMA_CACHE = formatted

    # Volcar a disco (best-effort: si falla, lo logueamos pero seguimos).
    try:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"raw": schema, "formatted": formatted}, f, ensure_ascii=False, indent=2)
        logger.info("get_schema: cache escrita en %s.", cache_path)
    except OSError as exc:
        logger.warning("get_schema: no se pudo escribir la cache %s (%s).", cache_path, exc)

    return formatted
