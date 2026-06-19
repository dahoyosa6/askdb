-- ─────────────────────────────────────────────────────────────
-- AskDB · Rol de aplicación de SOLO LECTURA sobre Northwind (Neon Postgres)
-- ─────────────────────────────────────────────────────────────
-- Ejecutar UNA sola vez, conectado con el rol OWNER de Neon (NEON_ADMIN_URL).
-- En runtime, la app SIEMPRE se conecta con 'askdb_readonly', nunca con el owner.
--
-- Defensa en profundidad: este rol es la barrera no-evitable. Aunque el modelo
-- generara un DELETE y la validación de la app fallara, la DB lo rechaza.
--
-- Notas Neon:
--   · La base por defecto es 'neondb' y el owner suele llamarse 'neondb_owner'.
--     Si tu owner tiene otro nombre, ajusta el ALTER DEFAULT PRIVILEGES FOR ROLE.
--   · Reemplaza 'REEMPLAZAR_PASSWORD_FUERTE' por una contraseña fuerte y úsala en
--     DATABASE_URL (.env):
--       postgresql://askdb_readonly:[PASSWORD]@[host].neon.tech/neondb?sslmode=require
-- ─────────────────────────────────────────────────────────────

-- 1) Crear el rol si no existe
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'askdb_readonly') THEN
    CREATE ROLE askdb_readonly LOGIN PASSWORD 'REEMPLAZAR_PASSWORD_FUERTE';
  END IF;
END$$;

-- 2) Conexión a la base, sin privilegios amplios
GRANT CONNECT ON DATABASE neondb TO askdb_readonly;

-- 3) Acceso de lectura al schema public (donde vive Northwind)
REVOKE ALL ON SCHEMA public FROM askdb_readonly;
GRANT USAGE ON SCHEMA public TO askdb_readonly;

-- 4) SELECT en todas las tablas/vistas existentes
GRANT SELECT ON ALL TABLES IN SCHEMA public TO askdb_readonly;

-- 5) Y en las que cree el owner a futuro
ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA public
  GRANT SELECT ON TABLES TO askdb_readonly;

-- 6) Negación explícita de escritura y de creación de objetos
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
  ON ALL TABLES IN SCHEMA public FROM askdb_readonly;
REVOKE CREATE ON SCHEMA public FROM askdb_readonly;

-- 7) Verificación rápida (debe devolver solo SELECT para askdb_readonly)
-- SELECT grantee, table_name, privilege_type
--   FROM information_schema.role_table_grants
--  WHERE grantee = 'askdb_readonly' ORDER BY table_name, privilege_type;
