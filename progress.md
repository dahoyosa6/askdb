# Progress — AskDB · "Habla con tus Datos"

> Diario de a bordo. Primer archivo que se lee al abrir sesión, último que se escribe al cerrar.

## Estado general
- **Fase actual:** Fase 1 COMPLETA ✅ (probada en vivo) → siguiente: Fase 2 (guardrails).
- **% MVP:** ~28%.
- **Próximo paso:** Fase 2 — validador de SQL (`validate_sql.py`): solo SELECT/CTE, una
  sentencia, bloquear DDL/DML, inyectar LIMIT. Tests de "DELETE bloqueado por app".

## Funcionalidades (estado)
| # | Funcionalidad | Estado | Pruebas |
|---|---|---|---|
| F0 | Setup (repo, entorno, DB, rol read-only) | ✅ Terminada | 4/4 verdes |
| F1 | Core CLI (NL→SQL→ejecutar→tabla) | ✅ Terminada (vivo) | 17/17 + prueba en vivo |
| F2 | Guardrails de seguridad | Pendiente | — |
| F3 | Auto-corrección | Pendiente | — |
| F4 | Router de formato (texto/gráfica/Excel) | Pendiente | — |
| F5 | Memoria conversacional | Pendiente | — |
| F6 | Bot Telegram (texto) | Pendiente | — |
| F7 | Voz (Groq) | Pendiente | — |
| F8 | Despliegue Railway | Pendiente | — |

## Bitácora
### 2026-06-19
- Entrevista cerrada: todo desde cero, hosting Railway, GitHub público, transcripción Groq.
- **Seguridad:** se encontró un `.env.rtf` con la API key de Anthropic en texto plano →
  eliminado; `.env` recreado con placeholders; `.gitignore` protege secretos desde el commit 0.
  **Pendiente David:** rotar esa key en console.anthropic.com (comprometida).
- Andamiaje creado: estructura de carpetas, `requirements.txt`, `config.py`, `.env.example`,
  `db/load_northwind.sql` (pthom/northwind_psql, 14 tablas), `db/create_readonly_role.sql`,
  `scripts/check_conn.py`. venv creado e instaladas dependencias (imports OK).
- **Decisión de arquitectura:** DB pasa de Supabase a **Neon** (free). Supabase de David está al
  tope de 2 proyectos gratis (Saku + Momentum); Pro costaría ~$44/mes. La v1 solo necesita
  Postgres, así que Neon da base dedicada/aislada a $0. Código sin cambios.
- PRD y este progress creados; proyecto registrado en el cerebro del estudio.
- **DB lista:** proyecto Neon `AskDB` (Postgres 18, US East 1). Northwind cargado vía
  `scripts/setup_db.py` (830 orders, 14 tablas). Rol `askdb_readonly` (solo SELECT) creado;
  verificado que un DELETE rebota a nivel DB. `NEON_ADMIN_URL` ya inerte en `.env`.
- Fase 0 verificada (`check_conn.py` + `pytest`, 4/4). **Commit `50ba562`**.
- Fix en el camino: `CREATE ROLE ... PASSWORD` no admite parámetro `$1`; se inyecta el
  password con `psycopg.sql.Literal`.

## Pendientes para David
- [x] Crear proyecto Neon `askdb` y pegar `NEON_ADMIN_URL` (hecho; DB cargada).
- [ ] **Rotar la API key de Anthropic y pegar la REAL en `.env`** (`ANTHROPIC_API_KEY=sk-ant-...`).
      Sigue el placeholder → la prueba en vivo de Fase 1 da 401.
- [ ] ¿Crear el repo público en GitHub y subir? (el Head lo hace con `gh` cuando confirmes).

## Bitácora Fase 1
### 2026-06-19
- Construidos `app/agent/{schema,glossary,generate_sql,execute}.py` y `app/cli.py` (delegado a code-architect).
- **Bug encontrado y corregido (importante):** la introspección leía constraints de
  `information_schema`, que sale VACÍO bajo un rol de solo-SELECT → Claude no veía PK/FK.
  Reescrita para leer de `pg_catalog`. Ahora detecta las 14 PK y 13 FK (verificado).
- El arquitecto había marcado eso como "defecto de datos" con tests `xfail`; era su propio
  bug. Tests reescritos a aserciones estrictas. **17/17 verdes.**
- `get_schema()` ahora abre su propia conexión read-only si no hay cache (arregla el CLI).
- **Prueba en vivo OK** con la key real: "¿cuántos pedidos?" → COUNT = 830; "top 5 clientes
  por facturación" → 3 joins por FK + interpretación del glosario (unit_price*quantity*(1-discount))
  → QUICK-Stop $110.277, etc. Claude usa las FK que arreglé para los joins.
- Trampa de infra: al editar `.env` para pegar la key, se sobrescribió `DATABASE_URL` con el
  placeholder; se restauró reejecutando `setup_db.py` (idempotente).

## Accesos y enlaces
- Repo local: `/Users/davidhoyos/Clientes/AskDB`
- GitHub: https://github.com/dahoyosa6/askdb (público)
- Neon: proyecto `AskDB` (org dahoyosa6) — base `neondb`, rol runtime `askdb_readonly`
- Railway: (pendiente, Fase 8)
