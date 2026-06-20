# Progress — AskDB · "Habla con tus Datos"

> Diario de a bordo. Primer archivo que se lee al abrir sesión, último que se escribe al cerrar.

## Estado general
- **Fase actual:** Fase 5 COMPLETA ✅ (memoria conversacional) → siguiente: Fase 6 (bot Telegram).
- **% MVP:** ~65%. El cerebro entiende conversaciones (follow-ups) además de preguntas sueltas.
- **Próximo paso:** Fase 6 — bot de Telegram (texto): allowlist de chat IDs, rate limit, y
  cablear el `chat_id` real de cada chat a `answer_question` (la memoria ya está lista para recibirlo).
  Decidir si exponer un comando `/reset` que llame a `memory.reset(chat_id)`.

## Funcionalidades (estado)
| # | Funcionalidad | Estado | Pruebas |
|---|---|---|---|
| F0 | Setup (repo, entorno, DB, rol read-only) | ✅ Terminada | 4/4 verdes |
| F1 | Core CLI (NL→SQL→ejecutar→tabla) | ✅ Terminada (vivo) | 17/17 + prueba en vivo |
| F2 | Guardrails de seguridad | ✅ Terminada | 41/41 (validador) + e2e timeout |
| F3 | Auto-corrección | ✅ Terminada | 63/63 (5 nuevos, mockeados) |
| F4 | Router de formato (texto/gráfica/Excel) | ✅ Terminada | 88/88 (25 nuevos) |
| F5 | Memoria conversacional | ✅ Terminada | 100/100 (12 nuevos) |
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
- [x] Rotar la API key de Anthropic y pegar la REAL en `.env` (hecha; prueba en vivo OK).
- [x] Crear el repo público en GitHub y subir (hecho: github.com/dahoyosa6/askdb, rama `main`).
- [ ] (Recordatorio higiene) Al editar `.env`, cambiar SOLO la línea necesaria; no reemplazar
      todo el archivo (ya pasó una vez y borró `DATABASE_URL`).
- [ ] (Fase 8) Crear cuenta/keys de Telegram (BotFather) y Groq cuando lleguemos a esas fases.

## Para la PRÓXIMA sesión (Fase 6 — bot de Telegram, texto)
- **Objetivo:** la interfaz real. Bot de Telegram (python-telegram-bot v21) que recibe texto,
  llama a `answer_question(question, chat_id=<id del chat>)` y responde según el `OutputResult`
  del router (texto / envía PNG / envía documento Excel). Criterio F6 del PRD.
- **Seguridad:** allowlist de chat IDs (`settings.allowed_chat_ids`) — solo responden los
  autorizados; rate limit (`settings.rate_limit_per_min`, =10). NUNCA mostrar SQL al usuario.
- **Memoria (ya lista):** pasar el `chat_id` real conecta la memoria de Fase 5 automáticamente.
  Decidir si exponer comando `/reset` → `memory.reset(chat_id)` para "empezar de cero".
- Construir `app/interfaces/telegram_bot.py` (hoy `app/interfaces/` está vacío) y, si hace falta,
  `app/main.py` (FastAPI para webhook, o polling). Las keys de Telegram las crea David (BotFather).
- Tests: mockear la API de Telegram; verificar allowlist (chat no autorizado se ignora), que el
  pipeline se invoca con el chat_id correcto, y el ruteo de texto/imagen/documento.
- Arranque: leer este `progress.md` + `prd.md` + `CLAUDE.md`; `source venv/bin/activate`;
  `pytest` debe dar **100/100** antes de tocar nada. Código clave: `app/agent/execute.py`
  (`answer_question`), `app/output/router.py` (`OutputResult`), `app/agent/memory.py` (`reset`),
  `config.py` (telegram_*, allowed_chat_ids, rate_limit_per_min).

## Bitácora Fase 5 (memoria conversacional)
### 2026-06-19
- `app/agent/memory.py` (NUEVO): store en RAM por `chat_id` (`_STORE: dict`). API: `get_history`
  (copia defensiva), `append_turn` (guarda `{user:pregunta}` + `{assistant:SQL ejecutado}` y recorta
  a `settings.memory_window`, leído en runtime), `reset` (idempotente) y `clear_all` (para tests).
  Documentada la limitación: RAM, single-process, sin persistencia ni locking → v2.
  (delegado a code-architect reps 1–3; verificado por el Head.)
- **Decisiones de producto (David):** memoria en **RAM** (no se escribe en la DB read-only; se pierde
  al reiniciar, aceptable v1); se recuerda **pregunta + SQL** (no las filas).
- **Decisiones técnicas:** turno del asistente = SQL en texto plano (no bloques tool_use reales);
  `memory_window` cuenta mensajes (6 = 3 pares); se guarda el `safe_sql`; se guarda **solo en éxito**.
  El historial va en `messages`, no en el `system` → el prompt-caching del esquema/glosario NO se rompe.
- `app/agent/execute.py`: `answer_question` recupera `history` del turno previo (si hay `chat_id`),
  lo pasa a `generate_sql` en TODOS los intentos (ortogonal al `error_feedback`), y hace `append_turn`
  solo al tener éxito. `chat_id` ya no es "reservado". `generate_sql.py`/`config.py`/`cli.py` intactos.
- Tests: `tests/test_memory.py` (6, store puro) + 6 de integración en `test_execute_autocorrect.py`
  (2º turno hereda el history del 1º; sin chat_id history=None; éxito guarda; fallo no guarda;
  aislamiento entre chats; history y error_feedback ortogonales). `_GenerateSpy` ampliado para
  capturar `history` (retro-compatible). **Suite total: 100/100 verdes** (88 previos + 12 nuevos).
- Nota desviación menor: el history del 1er turno de un chat es `[]` (no `None`); inocuo porque
  `_build_messages` trata ambos igual (`if history:`).
- Pendiente Fase 6: decidir comando `/reset` que exponga `memory.reset(chat_id)`. No se ejecutó CLI en vivo.

## Bitácora Fase 4 (router de formato de salida)
### 2026-06-19
- Capa de salida nueva en `app/output/`: `router.py` (dataclass `OutputResult` +
  `enrutar_salida(result, *, generar_artefacto=True)` + heurística determinista `elegir_formato`
  y helpers `_clasificar_columna`/`_tipo_de_grafica`/`_formatear_texto`), `chart.py`
  (`generar_grafica`, matplotlib backend `Agg` headless, barras/línea, `plt.close` siempre) y
  `spreadsheet.py` (`generar_excel`, pandas+openpyxl, des-duplica columnas homónimas).
  (delegado a code-architect reps 1–4; verificado por el Head.)
- **Decisiones de producto (David):** detalle largo → **Excel `.xlsx`** (no CSV); un solo
  registro (1 fila) → **siempre texto** en el chat (un valor = frase; ficha = lista).
- **Decisiones técnicas:** fechas = solo tipos nativos `date`/`datetime` (serie → línea);
  `Decimal` cuenta como numérico, `bool` no; nombre de archivo determinista por hash de contenido
  (`sha1[:8]`, idempotente, sin fecha/azar → tests reproducibles).
- **Seguridad (regla dura):** si generar gráfica/Excel falla, el router captura, loguea del lado
  servidor y **cae a texto**; nunca propaga el error ni expone stacktrace. Rama texto es pura
  (no toca disco ni importa matplotlib).
- **Rep 5 (Head):** `app/cli.py` integra `enrutar_salida`: texto se imprime; gráfica/Excel muestra
  ruta + caption + vista previa tabular acotada (`table_max_rows_text`). El CLI sigue mostrando el
  SQL (herramienta de dev); `answer_question` quedó intacto.
- Artefactos (`outputs/`, `*.png`, `*.xlsx`) siguen gitignored. Sin dependencias nuevas.
  **Suite total: 88/88 verdes** (63 previos + 25 nuevos). No se ejecutó el CLI en vivo.

## Bitácora Fase 3 (auto-corrección)
### 2026-06-19
- `app/agent/execute.py`: dataclass `AnswerResult` (ok, columns, rows, sql, attempts, error_message)
  + `answer_question(question, chat_id=None, *, client=None)` que orquesta generar→validar→ejecutar
  con bucle de auto-corrección. Captura `(SQLValidationError, psycopg.Error)`, loguea el detalle del
  lado servidor y reinyecta el error **saneado** (`str(exc)` recortado a 500 chars) como
  `error_feedback` al siguiente `generate_sql`. (delegado a code-architect, verificado por el Head.)
- **Decisión de semántica del tope:** `settings.max_sql_retries` (=3) se interpreta como
  **3 intentos de generación EN TOTAL incluyendo el primero** (no 1+3), para "converger en ≤3".
  Registrado también en el PRD.
- **Seguridad:** al usuario nunca le llega SQL crudo ni el error de Postgres; si se agotan los
  intentos devuelve `ok=False` con un `error_message` fijo en español (sin stacktrace).
- `app/cli.py` refactorizado: delega TODO a `answer_question`; imprime SQL + tabla si `ok=True`,
  o el mensaje saneado y código de salida 1 si `ok=False`. Uso vacío sigue devolviendo 2.
- Tests nuevos (Anthropic y DB mockeados, sin red): caso feliz (attempts=1, sin feedback);
  convergencia tras `psycopg.Error` verificando que el 2º generate recibió el error; convergencia
  tras `SQLValidationError`; agotar reintentos sin filtrar error crudo/SQL/Traceback; no crear
  cliente real si se inyecta. **Suite total: 63/63 verdes.** No se ejecutó el CLI en vivo.
- `chat_id` queda reservado (sin usar) para la memoria de Fase 5. Sin dependencias nuevas.

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
- Repo en GitHub (público), rama renombrada `master`→`main` (default actualizado).

## Bitácora Fase 2 (guardrails)
### 2026-06-19
- `app/agent/validate_sql.py`: `validate_and_secure()` — quita comentarios, exige una sola
  sentencia, solo SELECT/WITH, bloquea keywords de escritura/DDL/admin por TOKEN (no por texto,
  para no romper literales), e inyecta LIMIT (cap settings.query_row_hard_cap=1000) si falta.
  Respeta un LIMIT propio del modelo (decisión v1). Cableado en `app/cli.py`.
- **Tester-expert (adversarial):** 41 tests, 0 agujeros. Probó data-modifying CTEs de Postgres
  (`WITH x AS (DELETE...RETURNING) SELECT`) en variantes de mayúsculas/espacios → todos BLOQUEADOS.
- Observación: `SELECT pg_sleep(N)` pasa la app (no escribe) pero lo mata el `statement_timeout`
  de 8s → verificado e2e (cortado a 9s con QueryCanceled). Defensa en profundidad OK.
- **Suite total: 58/58 verdes.**

## Accesos y enlaces
- Repo local: `/Users/davidhoyos/Clientes/AskDB`
- GitHub: https://github.com/dahoyosa6/askdb (público)
- Neon: proyecto `AskDB` (org dahoyosa6) — base `neondb`, rol runtime `askdb_readonly`
- Railway: (pendiente, Fase 8)
