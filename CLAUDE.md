# CLAUDE.md — AskDB · "Habla con tus Datos"

> Memoria viva del proyecto. Se carga al inicio de cada sesión sobre esta carpeta.
> Decisiones de fondo en `prd.md`; estado y avance en `progress.md`; léelos primero.

## Qué es
Agente conversacional **text-to-SQL**: pregunta en lenguaje natural por Telegram (texto/voz)
→ SQL **seguro de solo lectura** → ejecución contra **Northwind** (Neon Postgres) → respuesta
en texto / gráfica PNG / Excel, con memoria conversacional y auto-corrección. Proyecto insignia
de portafolio: replicable y barato de operar.

## Stack
Python 3.12 (compatible 3.11+) · FastAPI+uvicorn · Anthropic SDK (`claude-sonnet-4-6`) · python-telegram-bot v21 ·
psycopg3 (+pool) · sqlparse · matplotlib · pandas+openpyxl · groq (voz) · python-dotenv.
DB: **Neon Postgres** (free). Hosting: **Railway**. Repo: GitHub público.

## Reglas duras
1. **Read-only sin excepción.** La app se conecta SIEMPRE con el rol `askdb_readonly`
   (solo SELECT), nunca con el owner. El owner solo se usó en setup.
2. **Seguridad en 3 capas:** validación con sqlparse (solo SELECT/CTE, una sentencia, sin DDL/DML) +
   LIMIT forzado (1000) + rol DB read-only. La capa DB es la barrera no-evitable.
3. **Nunca** exponer SQL crudo ni errores internos al usuario; loguear del lado servidor.
4. **Cero secretos en el repo.** Todo en `.env` (gitignored). `.env.example` documenta los nombres.
5. **config.py es la única zona de mantenimiento** (modelos, límites, glosario, timeouts).
6. **Spec-Driven + por fases:** no saltar fases; cada una se cierra con su prueba verde.

## Decisiones de arquitectura (cronológico)
- **2026-06-19 · DB = Neon, no Supabase.** Free tier de Supabase tope a 2 proyectos (Saku +
  Momentum, ambos en uso); Pro ~$44/mes. La v1 no usa features propias de Supabase (solo Postgres
  SELECT) → Neon da base dedicada/aislada gratis. El código (`psycopg`) es idéntico.
- **tool_use forzado** (`tool_choice` → herramienta `emit_sql`) para que Claude devuelva SQL
  estructurado y limpio, sin markdown ni preámbulo.
- **psycopg3 directo + pool**, no ORM: control fino de `statement_timeout` y `SET TRANSACTION READ ONLY`.
- **Cache de esquema** (Northwind es estático): menos tokens y prefijo estable para prompt-caching de Claude.
- **transcribe() como interfaz** intercambiable: Groq Whisper hoy; cambiar proveedor no toca el bot.
- **2026-06-19 · Introspección vía `pg_catalog`, no `information_schema`.** Bajo el rol de
  solo-SELECT, `information_schema.table_constraints/key_column_usage` salen VACÍAS (solo muestran
  constraints de tablas con privilegio distinto de SELECT). Sin esto Claude no ve PK/FK. `schema.py`
  lee de `pg_catalog` (visible para todos). **Trampa a recordar** para futuros agentes read-only.
- **2026-06-19 · LIMIT por append + statement_timeout para DoS.** El validador añade `LIMIT` al
  final (no envuelve, rompía joins con columnas duplicadas); `pg_sleep` y consultas pesadas las
  corta el `statement_timeout` (8s), no el validador.

## Estado por fases (resumen; detalle en progress.md)
- F0 Setup ✅ · F1 Core CLI ✅ (vivo) · F2 Guardrails ✅ · F3 Auto-corrección ✅ ·
  F4 Formato ✅ · F5 Memoria ✅ · F6 Telegram (webhook) ✅ · F7 Voz ✅ (170 tests).
- **F8 Railway (despliegue) → siguiente.** MVP funcional completo: texto y voz por
  Telegram, seguro, con memoria y formato automático.

## Cómo correrlo (local)
```bash
source venv/bin/activate
python scripts/check_conn.py     # verifica conexión read-only + Northwind (compuerta Fase 0)
# (Fase 1+) python -m app.cli "¿cuántos pedidos hay?"
pytest                            # pruebas
```

## Estructura
`config.py` (constantes) · `app/agent/` (schema, glossary, generate_sql, validate_sql, execute,
memory) · `app/output/` (chart, spreadsheet, router) · `app/transcription/transcribe.py` ·
`app/interfaces/telegram_bot.py` · `app/main.py` (FastAPI) · `db/` (load_northwind.sql,
create_readonly_role.sql) · `scripts/check_conn.py` · `tests/`.

## Idioma
Responder siempre en español; explicar lo técnico en lenguaje claro.
