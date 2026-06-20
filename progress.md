# Progress — AskDB · "Habla con tus Datos"

> Diario de a bordo. Primer archivo que se lee al abrir sesión, último que se escribe al cerrar.

## Estado general
- **Fase actual:** Fase 7 COMPLETA ✅ + **review completa de endurecimiento pre-F8 ✅** → siguiente: Fase 8 (despliegue Railway).
- **% MVP:** ~92%. MVP funcional COMPLETO y endurecido: el agente acepta texto y voz por Telegram,
  seguro y con memoria. Suite ahora en **170/170** tras dos vueltas de review + verificación.
- **Próximo paso:** Fase 8 — desplegar en Railway: subir el servidor FastAPI, definir variables de
  entorno (token, keys, WEBHOOK_URL pública, WEBHOOK_SECRET), registrar el webhook y probar en vivo.

## Funcionalidades (estado)
| # | Funcionalidad | Estado | Pruebas |
|---|---|---|---|
| F0 | Setup (repo, entorno, DB, rol read-only) | ✅ Terminada | 4/4 verdes |
| F1 | Core CLI (NL→SQL→ejecutar→tabla) | ✅ Terminada (vivo) | 17/17 + prueba en vivo |
| F2 | Guardrails de seguridad | ✅ Terminada | 41/41 (validador) + e2e timeout |
| F3 | Auto-corrección | ✅ Terminada | 63/63 (5 nuevos, mockeados) |
| F4 | Router de formato (texto/gráfica/Excel) | ✅ Terminada | 88/88 (25 nuevos) |
| F5 | Memoria conversacional | ✅ Terminada | 100/100 (12 nuevos) |
| F6 | Bot Telegram (texto, webhook) | ✅ Terminada | 118/118 (18 nuevos) |
| F7 | Voz (Groq) | ✅ Terminada | 128/128 (10 nuevos) |
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
- [x] Borrar el `.env.rtf` con la key vieja (hecho en la review; no estaba en git, key ya rotada).
- [ ] (Recordatorio higiene) Al editar `.env`, cambiar SOLO la línea necesaria; no reemplazar
      todo el archivo (ya pasó una vez y borró `DATABASE_URL`).
- [ ] (Para probar el bot en vivo, F7/F8) Crear el bot en **BotFather** → `TELEGRAM_BOT_TOKEN`;
      averiguar tu `chat_id` y poblar `ALLOWED_CHAT_IDS`; definir un `WEBHOOK_SECRET` aleatorio.
      La `WEBHOOK_URL` pública sale del despliegue (Railway, F8).
- [ ] (Fase 7) Crear `GROQ_API_KEY` (groq.com, free tier) para la transcripción de voz.

## Para la PRÓXIMA sesión (Fase 8 — despliegue en Railway)
- **Objetivo:** poner el bot en producción. Desplegar el servidor FastAPI (`app/main.py`) en Railway,
  configurar variables de entorno, registrar el webhook contra Telegram y probar EN VIVO (texto y voz).
- **Listo de antemano:** la review de seguridad ya se hizo (2 vueltas, informes en `docs/revisiones/`);
  `Procfile` (`web: uvicorn app.main:app --host 0.0.0.0 --port $PORT`) y `.python-version` (3.12) ya creados;
  el lifespan ya registra el webhook solo si hay `WEBHOOK_URL`. Suite **170/170** (correr `pytest` antes de tocar).
- Pasos previstos: (1) crear servicio en Railway apuntando al repo (usa el `Procfile`); (2) cargar
  variables: `ANTHROPIC_API_KEY`, `DATABASE_URL` (Neon, rol read-only), `ANTHROPIC_MODEL` (claude-sonnet-4-6),
  `TELEGRAM_BOT_TOKEN`, `ALLOWED_CHAT_IDS`, `WEBHOOK_SECRET`, `GROQ_API_KEY`, y `WEBHOOK_URL` = la URL
  pública que da Railway (apuntando a `/webhook`); (3) deploy → el lifespan registra el webhook; (4) recorrer
  la **checklist de prueba manual en vivo** (en `docs/revisiones/tester-2026-06-19.md` §6: texto, gráfica,
  Excel, voz, voz larga, no autorizado, rate limit, /reset+follow-up, webhook 403, pregunta imposible).
- **Mantener 1 sola réplica** en Railway (el estado —memoria + rate limiter— vive en RAM; multi-instancia = v2).
- **Diferido a F8 (de la review):** B4 — dar visibilidad al fallo de `set_webhook` vía **Sentry** (MCP
  disponible) para que un registro fallido no quede solo en logs. Conectar Sentry en este paso.
- **Recordatorio del estudio (§9 + Automatizaciones.md):** AskDB sería el PRIMER proyecto en producción →
  activar la **guardia de producción** y el **pulso de analítica** (PostHog) listados en `Automatizaciones.md`.
- Pendientes David (sin esto NO funciona en vivo): crear bot en BotFather (`TELEGRAM_BOT_TOKEN`),
  averiguar su `chat_id` (`ALLOWED_CHAT_IDS`), generar `WEBHOOK_SECRET` aleatorio, crear `GROQ_API_KEY`.
- Opcional antes de Railway: prueba en vivo local con un túnel (ngrok) para validar el webhook end-to-end.
- **Nota de mantenimiento (no bloquea):** 164 warnings de `pytest-asyncio` en Python 3.14 (deprecación de
  event-loop-policy de la librería); el `StarletteDeprecationWarning` del TestClient es de FastAPI, no del código.

## Bitácora — 2ª vuelta: verificación de la review
### 2026-06-19
- Re-review con los 4 subagentes (informes `*-verificacion-2026-06-19.md` en `docs/revisiones/`)
  para confirmar que los arreglos quedaron **de fondo** y sin regresiones.
- **Veredictos:** code-architect "listo para F8" (11/13 hallazgos resueltos de fondo, 0 sin resolver,
  B1/B4 aceptados por diseño; seguridad SQL re-probada intacta, sin regresiones); tester **PASA F8**
  (huecos cerrados con tests reales, aserciones endurecidas); auditor **alineado** (desviaciones
  cerradas); calidad **aprobado sin reservas** (ningún texto técnico se cuela al usuario).
- **Único hallazgo nuevo (B5-NEW, 🟡, no explotable hoy):** una función entre comillas dobles
  `SELECT "pg_read_file"(...)` evadía la denylist (sqlparse la tokeniza como `String.Symbol`, no
  `Name`). **Cerrado de fondo:** el escaneo ahora cubre `T.Name` y `String.Symbol` (comillas,
  mayúsculas, esquema calificado citado), sin falsos positivos. +8 tests. **Suite: 170/170.**
- Cosméticos de docs cerrados: Python 3.12 (compat 3.11+), conteo de tests sincronizado a 170.

## Bitácora — Review completa + endurecimiento pre-F8
### 2026-06-19
- **Review por 4 subagentes** (informes en `docs/revisiones/`): code-architect (código+seguridad),
  tester-expert (QA), auditor (proceso), quality-reviewer (entregables). Veredicto: sólido, seguridad
  SQL real y probada (bypasses adversariales todos bloqueados), 0 críticos. David pidió arreglar TODO.
- **Arreglado (delegado a code-architect + docs por el Head):**
  - Seguridad: A1 `.env.rtf` borrado (no estaba en git; key ya rotada); M2 `hmac.compare_digest` en el
    webhook; **denylist de funciones peligrosas** en `validate_sql.py` (pg_read_file, lo_import, dblink,
    etc.) como 2ª barrera de app (antes solo las cortaba el rol DB).
  - Robustez: A2/B2 `answer_question` captura errores de Anthropic (`APIError`) + `RuntimeError` como
    recuperables, mensaje "saturado" para 429/timeout, loguea `_request_id`; CLI envuelto; M5 pool con
    `check_connection` + `max_idle` (evita fallo del primer mensaje tras pausa de Neon); M1 None-guards
    en los handlers; M3 validador detecta `FETCH FIRST`; B5 cliente Groq singleton.
  - Copy (calidad): B1 respuesta de 1 dato ya NO dice "El count es 830" (solo el valor); I1 captions
    humanos; I2 tabla multi-fila como registros legibles; mensajes más cálidos.
  - Tests: **+34** (denylist, FETCH, async handlers con `pytest-asyncio`+AsyncMock, robustez). Total **162/162**.
  - Docs (Head): `CLAUDE.md` estado F0–F7 ✅ (antes decía "F3 siguiente"); README estado real;
    nota en PRD de que nació de un spec madre; M6 docstrings `information_schema`→`pg_catalog` y Supabase→Neon.
  - Deploy (B3): `.python-version` (3.12) + `Procfile` para Railway.
- **Diferido a F8:** B4 (visibilidad de fallo de `set_webhook` vía Sentry). **Nota de mantenimiento:**
  164 warnings de `pytest-asyncio` en Python 3.14 (deprecación de event-loop-policy), inocuas.

## Bitácora Fase 7 (voz)
### 2026-06-19
- `app/transcription/transcribe.py` (NUEVO): `transcribe(audio_bytes, *, filename="audio.ogg") -> str`
  síncrono, Groq Whisper (`language="es"`), `.text.strip()`. **Interfaz intercambiable** (cambiar de
  proveedor no toca el bot). Error claro si falta `GROQ_API_KEY`; los errores de API se propagan.
- `app/interfaces/telegram_bot.py`: `handle_voice` (replica el patrón de `handle_text`: allowlist →
  rate limit → límite de duración → `get_file`/`download_as_bytearray` → `to_thread(transcribe)` →
  eco "🎤 Entendí: ..." → `procesar_pregunta` → `decidir_envio` → enviar; try/except saneado).
  Helpers puros `texto_eco` y `voz_demasiado_larga`; constantes `_TEXTO_VOZ_MUY_LARGA`/
  `_TEXTO_VOZ_NO_ENTENDIDA`. Registrado `MessageHandler(filters.VOICE, handle_voice)`.
- `config.py` + `.env.example`: nuevo setting `max_voice_duration_s` (default 120).
  (delegado a code-architect reps 1–3; verificado por el Head.)
- **Decisión de producto (David):** el bot muestra lo que entendió (eco) antes de responder.
- **Decisiones técnicas:** SDK Groq síncrono → corre en `asyncio.to_thread`; solo `filters.VOICE`
  (no audios/música); `allowed_updates` sigue `["message"]` (la voz va dentro de message). Nunca se
  expone SQL ni error (log servidor + mensaje saneado). Tests síncronos (Groq mockeado + helpers puros).
- **Suite total: 128/128 verdes** (118 previos + 10 nuevos). Cero cambios en `app/agent/*`,
  `app/output/*`, `app/main.py` ni `cli.py`. No se ejecutó Groq ni el bot en vivo.

## Bitácora Fase 6 (bot de Telegram por webhook, texto)
### 2026-06-19
- `app/interfaces/telegram_bot.py` (NUEVO): `build_application()` (registra `/start`, `/help`,
  `/reset` + `MessageHandler(TEXT & ~COMMAND)`); handlers async finos; funciones puras síncronas
  `is_allowed`, `decidir_envio` (+`EnvioPlan`), puente `procesar_pregunta` (answer_question +
  enrutar_salida); `RateLimiter` (ventana móvil 60s por chat_id, `now` inyectable, RAM).
- `app/main.py` (NUEVO): FastAPI con `lifespan` (initialize/start → `set_webhook` tolerante a
  fallo → stop/shutdown + `close_pool`), `GET /` (health Railway) y `POST /webhook`.
- `config.py` + `.env.example`: nuevo setting `webhook_secret`.
  (delegado a code-architect reps 1–6; verificado por el Head.)
- **Decisiones de producto (David):** webhook con FastAPI (no polling); comandos /start, /help, /reset.
- **Decisiones técnicas:** el cerebro síncrono corre en `asyncio.to_thread` para no bloquear el bot;
  seguridad del webhook por header `X-Telegram-Bot-Api-Secret-Token` con **fallo cerrado** (sin
  secreto → 403) + allowlist por chat_id; rate limiter en RAM (limitación v1). NUNCA se envía SQL
  (el bot usa el router, no toca `result.sql`); toda excepción → `logger.exception` (servidor) +
  mensaje saneado. Tests sin `pytest-asyncio`: lógica en funciones puras + webhook con `TestClient`
  y `Application` falsa (`AsyncMock`); `Settings` es frozen → en tests se usa `dataclasses.replace`.
- **Suite total: 118/118 verdes** (100 previos + 18 nuevos). Cero cambios en `app/agent/*`,
  `app/output/*` ni `cli.py`. No se ejecutó el bot en vivo (no hay token ni URL pública).
- **Pendiente David (para vivo en F8):** crear el bot en BotFather (`TELEGRAM_BOT_TOKEN`), poblar
  `ALLOWED_CHAT_IDS`, definir `WEBHOOK_URL` pública y un `WEBHOOK_SECRET` aleatorio. Sin esos, el
  bot no recibe nada (es esperado; se cablea en el despliegue).

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
