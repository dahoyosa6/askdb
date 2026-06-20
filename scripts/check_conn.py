"""Verificación de conexión de la Fase 0.

Confirma que la app se conecta a Neon con el rol de SOLO LECTURA y que
Northwind está cargado. Es la compuerta para pasar a la Fase 1.

Uso:
    python scripts/check_conn.py
"""

from __future__ import annotations

import sys

import psycopg

# Permite ejecutar el script desde la raíz del repo
sys.path.insert(0, ".")
from config import settings  # noqa: E402


def main() -> int:
    if not settings.database_url:
        print("✗ Falta DATABASE_URL en .env (cadena del pooler con rol askdb_readonly).")
        return 1

    try:
        with psycopg.connect(settings.database_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_user;")
                user = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM orders;")
                n_orders = cur.fetchone()[0]
    except Exception as exc:  # noqa: BLE001
        print(f"✗ No se pudo conectar/consultar: {exc}")
        return 1

    print(f"  Usuario conectado : {user}")
    print(f"  Filas en 'orders' : {n_orders}")

    ok = True
    if user != "askdb_readonly":
        print(f"✗ Conectado como '{user}', se esperaba 'askdb_readonly' (rol read-only).")
        ok = False
    if n_orders <= 0:
        print("✗ La tabla 'orders' está vacía: ¿se cargó Northwind?")
        ok = False

    if ok:
        print("✓ Fase 0 verificada: conexión read-only OK y Northwind poblado.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
