"""Setup idempotente de la base de datos AskDB en Neon (Fase 0).

Hace, usando NEON_ADMIN_URL (rol owner, solo para setup):
  1. Carga Northwind (db/load_northwind.sql) si no está cargado.
  2. Crea el rol de SOLO LECTURA 'askdb_readonly' con una contraseña fuerte generada.
  3. Aplica los GRANT/REVOKE (solo SELECT sobre public).
  4. Verifica: el rol read-only puede SELECT pero NO puede DELETE.
  5. Escribe DATABASE_URL (cadena del rol read-only) en .env.

No imprime secretos. Uso:  python scripts/setup_db.py
"""

from __future__ import annotations

import os
import re
import secrets
import string
import sys
from pathlib import Path
from urllib.parse import quote

import psycopg
import sqlparse
from dotenv import load_dotenv
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
DUMP_PATH = ROOT / "db" / "load_northwind.sql"
READONLY_ROLE = "askdb_readonly"


def gen_password(n: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def load_northwind(conn: psycopg.Connection) -> None:
    # ¿ya cargado?
    exists = conn.execute(
        "SELECT to_regclass('public.orders') IS NOT NULL"
    ).fetchone()[0]
    if exists:
        n = conn.execute("SELECT count(*) FROM orders").fetchone()[0]
        if n > 0:
            print(f"  Northwind ya estaba cargado (orders={n}). Omito carga.")
            return
    print("  Cargando Northwind (puede tardar)...")
    sql = DUMP_PATH.read_text(encoding="utf-8")
    statements = [s for s in sqlparse.split(sql) if s.strip()]
    with conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)
    print(f"  Cargadas {len(statements)} sentencias del dump.")


def create_readonly_role(conn: psycopg.Connection, owner: str, dbname: str) -> str:
    password = gen_password()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (READONLY_ROLE,)
        )
        role_ident = sql.Identifier(READONLY_ROLE)
        # El password NO puede ir como parámetro ($1) en CREATE/ALTER ROLE
        # (son comandos de utilidad). Se inyecta como literal citado con sql.Literal.
        verb = "ALTER" if cur.fetchone() else "CREATE"
        cur.execute(
            sql.SQL("{verb} ROLE {role} LOGIN PASSWORD {pw}").format(
                verb=sql.SQL(verb),
                role=role_ident,
                pw=sql.Literal(password),
            )
        )
        # Permisos: solo lectura sobre public
        cur.execute(f"GRANT CONNECT ON DATABASE {dbname} TO {READONLY_ROLE}")
        cur.execute(f"REVOKE ALL ON SCHEMA public FROM {READONLY_ROLE}")
        cur.execute(f"GRANT USAGE ON SCHEMA public TO {READONLY_ROLE}")
        cur.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {READONLY_ROLE}")
        cur.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public "
            f"GRANT SELECT ON TABLES TO {READONLY_ROLE}"
        )
        cur.execute(
            f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER "
            f"ON ALL TABLES IN SCHEMA public FROM {READONLY_ROLE}"
        )
        cur.execute(f"REVOKE CREATE ON SCHEMA public FROM {READONLY_ROLE}")
    print(f"  Rol '{READONLY_ROLE}' creado/actualizado con permisos de solo lectura.")
    return password


def build_readonly_url(admin_url: str, password: str) -> str:
    # Reemplaza usuario:contraseña del owner por el rol read-only
    # admin_url: postgresql://neondb_owner:PASS@host/neondb?params
    m = re.match(r"^(postgres(?:ql)?://)([^:]+):([^@]+)@(.+)$", admin_url)
    if not m:
        raise RuntimeError("NEON_ADMIN_URL no tiene el formato esperado.")
    scheme, _user, _pw, rest = m.groups()
    return f"{scheme}{READONLY_ROLE}:{quote(password, safe='')}@{rest}"


def verify_readonly(url: str) -> None:
    with psycopg.connect(url, connect_timeout=15) as conn:
        user = conn.execute("SELECT current_user").fetchone()[0]
        n = conn.execute("SELECT count(*) FROM orders").fetchone()[0]
        assert user == READONLY_ROLE, f"esperaba {READONLY_ROLE}, conectó como {user}"
        assert n > 0, "orders vacío"
        # Debe FALLAR un intento de escritura
        blocked = False
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM customers WHERE 1=0")
        except psycopg.errors.InsufficientPrivilege:
            blocked = True
        conn.rollback()
        assert blocked, "¡PELIGRO! el rol read-only pudo ejecutar DELETE"
    print(f"  Verificado: conecta como '{user}', orders={n}, DELETE BLOQUEADO por la DB. ✓")


def write_database_url(url: str) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    out, replaced = [], False
    for line in lines:
        if line.startswith("DATABASE_URL="):
            out.append(f"DATABASE_URL={url}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"DATABASE_URL={url}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("  DATABASE_URL (rol read-only) escrito en .env.")


def main() -> int:
    load_dotenv(ENV_PATH)
    admin_url = os.getenv("NEON_ADMIN_URL")
    if not admin_url:
        print("✗ Falta NEON_ADMIN_URL en .env.")
        return 1

    with psycopg.connect(admin_url, autocommit=True, connect_timeout=15) as conn:
        owner = conn.execute("SELECT current_user").fetchone()[0]
        dbname = conn.execute("SELECT current_database()").fetchone()[0]
        print(f"  Conectado como owner '{owner}' a la base '{dbname}'.")
        load_northwind(conn)
        password = create_readonly_role(conn, owner, dbname)

    ro_url = build_readonly_url(admin_url, password)
    verify_readonly(ro_url)
    write_database_url(ro_url)
    print("\n✓ Fase 0 (DB) completa. Ahora puedes correr: python scripts/check_conn.py")
    print("  Recuerda quitar NEON_ADMIN_URL de .env (ya no se necesita en runtime).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
