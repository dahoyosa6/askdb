# Revisión de código y seguridad — AskDB

- **Revisor:** Code Architect (subagente, De cero a uno)
- **Fecha:** 2026-06-19
- **Alcance:** Toda la app (`config.py`, `app/agent/*`, `app/output/*`, `app/interfaces/telegram_bot.py`, `app/main.py`, `app/transcription/transcribe.py`, `app/cli.py`, `db/`, `scripts/`), tests y preparación para Railway (Fase 8).
- **Estado de pruebas:** `pytest -q` → **128/128 verdes** (Python 3.14.5 del venv).
- **Tipo de revisión:** solo lectura. NO se modificó código ni se hizo commit.

> Severidades: 🔴 Crítico · 🟠 Alto · 🟡 Medio · 🟢 Bajo.

---

## Resumen ejecutivo

El proyecto está **muy bien construido** para un MVP camino a producción: arquitectura limpia y desacoplada (cerebro vs. interfaz), seguridad SQL pensada en serio (3 capas reales), saneamiento de errores consistente hacia el usuario, y una suite de pruebas amplia. La defensa contra escritura/borrado es **sólida**: probé adversarialmente CTEs que modifican datos, smuggling por `;` y comentarios, `SELECT INTO`, `COPY`, `SET`, mayúsculas/minúsculas mezcladas y saltos de línea — **todos bloqueados** por el validador, y la capa de rol read-only de la DB es la barrera final no evitable.

No hay hallazgos **Críticos**. Hay **2 Altos** que conviene resolver antes de exponer el bot al público (uno de seguridad operativa, uno de robustez), y varios Medios/Bajos que son higiene y pulido. Ninguno bloquea la arquitectura.

**Conteo:** 🔴 0 · 🟠 2 · 🟡 6 · 🟢 5.

---

## 🟠 Altos

### A1 — `.env.rtf` con la API key comprometida sigue en el disco del repo
`/Users/davidhoyos/Clientes/AskDB/.env.rtf`

El `progress.md` dice que el `.env.rtf` (que tenía la API key de Anthropic en texto plano) fue **eliminado**. **No lo está**: el archivo sigue existiendo en la carpeta del repo.

- Lo bueno: `git ls-files` confirma que **NO está trackeado por Git** (el patrón `.env.*` del `.gitignore` lo cubre), y nunca se commiteó (`git log --all -- .env.rtf` está vacío). Así que **no se filtró a GitHub**.
- El riesgo: es un secreto en texto plano que sigue en disco. El `progress.md` ya marca como pendiente "rotar esa key" y dice que se hizo. Si la key vieja ya se rotó, el contenido es inerte, pero igual debe borrarse para no dejar confusión ni un secreto huérfano.

**Recomendación:** borrar `/Users/davidhoyos/Clientes/AskDB/.env.rtf` del disco (`rm`). Confirmar con David que la key de Anthropic que estaba ahí **ya fue rotada** en console.anthropic.com (el progress dice que sí; verificar). Actualizar el progress para reflejar que el archivo ya no existe.

### A2 — Errores de `generate_sql` (API de Anthropic / tool_use ausente) NO se capturan en el bucle de auto-corrección
`/Users/davidhoyos/Clientes/AskDB/app/agent/execute.py:235`

El `except` de `answer_question` solo atrapa `(SQLValidationError, psycopg.Error)`. Pero `generate_sql` (línea 223) puede lanzar:
- `RuntimeError` si el modelo no devuelve un bloque `tool_use` válido (`generate_sql.py:200,209`).
- Excepciones del SDK de Anthropic: `anthropic.RateLimitError`, `anthropic.APIConnectionError`, `anthropic.APIStatusError`, `anthropic.APITimeoutError`, etc. (caída de red, 429, 5xx, timeout).

Ninguna de esas está en el `except`, así que **se propagan fuera de `answer_question`**.

- En el **bot de Telegram** esto está cubierto: `handle_text`/`handle_voice` tienen un `try/except Exception` de frontera que loguea y devuelve mensaje saneado (telegram_bot.py:265, :329). ✅ No hay fuga al usuario final.
- En el **CLI** NO está cubierto: `cli.py:89` llama `answer_question` sin try/except, así que un fallo de la API de Anthropic imprime un **stacktrace crudo** en la terminal. El CLI es herramienta de dev (aceptable mostrar SQL/errores ahí, por diseño), así que esto es de robustez, no de fuga de seguridad. Pero un `RateLimitError` reventando el CLI con un traceback feo es mala UX para David al probar.

Más importante en producción: un fallo transitorio de la API de Anthropic (429/5xx/timeout) **no se reintenta** dentro del loop de auto-corrección — aborta el turno. El SDK de Anthropic ya reintenta 429/5xx con backoff internamente (2 reintentos por defecto), lo cual mitiga bastante, pero un error que agote esos reintentos sí tumba el turno.

**Recomendación:** ampliar el `except` para incluir `RuntimeError` y los errores del SDK de Anthropic (`anthropic.APIError` cubre la jerarquía), tratándolos como intento fallido recuperable y reinyectando feedback saneado — o al menos devolviendo `ok=False` con el mensaje saneado en vez de propagar. Decidir si un `RateLimitError`/timeout debe consumir un intento o devolver un mensaje específico ("estoy saturado, intenta en un momento"). En el CLI, envolver `answer_question` en un try/except que imprima el mensaje saneado.

---

## 🟡 Medios

### M1 — `update.effective_chat` / `update.message` pueden ser `None` → posible `AttributeError` en los handlers
`/Users/davidhoyos/Clientes/AskDB/app/interfaces/telegram_bot.py:233, :247, :284, :298`

Todos los handlers hacen `chat_id = update.effective_chat.id` directamente. Para un update de tipo `message`, `effective_chat` normalmente existe, pero python-telegram-bot puede entregar updates donde `effective_chat` o `update.message` sean `None` (p. ej. edición de mensaje, ciertos tipos de update). `allowed_updates=["message"]` reduce el riesgo, pero en `handle_text` además se accede a `update.message.text` (:247) y en `handle_voice` a `update.message.voice` (:298) sin verificar que `update.message` exista.

Si pasa, el `AttributeError` ocurre **antes** del try/except (en `handle_text` el acceso a `chat_id` es la primera línea, antes del try), así que no quedaría saneado por la frontera — lo atraparía el manejador de errores global de PTB, pero conviene blindarlo.

**Recomendación:** al inicio de cada handler, `if update.effective_chat is None or update.message is None: return`. Barato y elimina toda una clase de crashes.

### M2 — Comparación del secreto del webhook no es de tiempo constante
`/Users/davidhoyos/Clientes/AskDB/app/main.py:84`

`return recibido == settings.webhook_secret` usa comparación normal de strings, vulnerable en teoría a un timing attack para inferir el secreto byte a byte. En la práctica el riesgo es **bajo** (el secreto es largo y aleatorio, la red añade ruido), pero es trivial endurecerlo.

**Recomendación:** usar `hmac.compare_digest(recibido or "", settings.webhook_secret)`. El resto de la seguridad del webhook es **correcta**: fallo cerrado si no hay secreto (:81), allowlist por chat_id en los handlers, rate limiter. Bien hecho.

### M3 — `_ensure_limit` no detecta `FETCH FIRST … ROWS ONLY` → SQL inválido (rescatado por auto-corrección)
`/Users/davidhoyos/Clientes/AskDB/app/agent/validate_sql.py:124-141`

`_has_top_level_limit` solo busca el keyword `LIMIT`. Si el modelo emite `SELECT … FETCH FIRST 5 ROWS ONLY` (sintaxis SQL estándar válida en Postgres), el validador **añade** `\nLIMIT 1000` al final, produciendo `… FETCH FIRST 5 ROWS ONLY LIMIT 1000`, que es **sintácticamente inválido** y Postgres rechazará. Verificado en vivo: produce `'...FETCH FIRST 5 ROWS ONLY\nLIMIT 1000'`.

No es un agujero de seguridad (no permite escribir nada; la consulta simplemente falla) y el loop de auto-corrección probablemente lo recupere reformulando. Pero gasta un intento y es un caso límite real porque el prompt no le prohíbe `FETCH FIRST` al modelo.

**Recomendación:** o bien (a) detectar también `FETCH` en `_has_top_level_limit`, o (b) instruir al modelo en `generate_sql.py` a usar `LIMIT`, no `FETCH FIRST`. Opción (a) es más robusta.

### M4 — `cur.description` puede no reflejar bien el conteo de columnas con nombres duplicados; y filas con valores no serializables
`/Users/davidhoyos/Clientes/AskDB/app/agent/execute.py:117`

`run_query` arma `columns` desde `cur.description`. Con joins que traen columnas homónimas (p. ej. dos `order_id`), `columns` tendrá nombres repetidos — el router lo maneja en Excel (`_columnas_unicas`) pero en texto (`_formatear_texto`) y en gráfica los nombres duplicados pueden confundir el emparejamiento por índice (aunque se opera por posición, así que en la práctica funciona). Es más una observación de consistencia que un bug.

Riesgo más real: tipos de celda exóticos de Postgres (arrays, JSON, `bytea`, rangos) llegan como objetos Python que `str()` renderiza de forma poco amigable o que matplotlib/pandas podrían no graficar. El router cae a texto si la gráfica/Excel falla (bien), pero un `bytea` en texto se vería como `b'\\x...'`.

**Recomendación:** bajo riesgo para Northwind (esquema conocido, sin tipos exóticos). Anotarlo como límite conocido para v2 (datos reales del cliente). Sin acción inmediata.

### M5 — El pool de conexiones no valida conexiones muertas tras inactividad (Neon pausa)
`/Users/davidhoyos/Clientes/AskDB/app/agent/execute.py:72-77`

El PRD/CLAUDE.md reconocen que **Neon free pausa la base por inactividad**. El `ConnectionPool` se crea con `min_size`, `max_size`, `open=True`, pero **sin `check`**. Tras una pausa de Neon, las conexiones en el pool pueden quedar muertas; la primera consulta tras despertar podría fallar con un error de conexión. `psycopg_pool` soporta `check=ConnectionPool.check_connection` para validar/reciclar conexiones al sacarlas del pool.

En producción esto se traduce en: el primer mensaje del día (tras pausa de Neon) podría fallar. Hoy lo rescataría parcialmente el loop de auto-corrección si el error es `psycopg.Error` (sí lo es), reintentando — pero el segundo intento usa el mismo pool, así que podría fallar igual hasta que el pool recicle.

**Recomendación:** añadir `check=ConnectionPool.check_connection` al crear el pool, y/o `max_idle` corto. Bajo costo, evita fallos del "primer mensaje tras inactividad" que son confusos para el usuario.

### M6 — Inconsistencias de documentación (docstrings/comentarios desactualizados) — riesgo de confundir a futuros agentes
Varios archivos:
- `schema.py:1-12, :32, :180` — el docstring dice que lee constraints de `information_schema`, pero el código (correctamente) lee de `pg_catalog` (esto fue el bug clave de Fase 1; el código está bien, el docstring quedó viejo). `_shorten_type` también dice "de information_schema".
- `scripts/check_conn.py:4` — docstring dice "se conecta a **Supabase**"; el proyecto migró a Neon.
- `requirements.txt:14` — comentario dice "Postgres (Supabase)"; es Neon.

No afectan el funcionamiento, pero el CLAUDE.md del proyecto insiste en que estas trampas se documenten bien para futuros agentes. Un docstring que dice "information_schema" justo donde estuvo el bug es contraproducente.

**Recomendación:** corregir esos comentarios/docstrings para que digan `pg_catalog` y Neon. Es higiene barata y valiosa dado el modelo de trabajo por sesiones.

---

## 🟢 Bajos

### B1 — Estado en RAM (memoria + rate limiter) se pierde al reiniciar y no es multi-instancia
`memory.py`, `telegram_bot.py:116-162`. Ya documentado explícitamente en el código y el PRD como limitación aceptada de v1. **Importante para Railway:** si el servicio escala a >1 réplica, la allowlist/rate-limit/memoria no se comparten y el rate limiting deja de ser efectivo. Para el demo (1 instancia) está bien. Recomendación: en Railway, mantener **1 sola réplica** hasta que v2 mueva el estado a Redis/Postgres. Anotarlo en el plan de despliegue.

### B2 — No se loguea el `request_id` de Anthropic en los errores
Cuando una llamada a la API falla, loguear `exc._request_id` (lo expone el SDK) facilita el soporte con Anthropic. Mejora de observabilidad, no bug.

### B3 — Sin pin de versión de Python para Railway (el venv usa 3.14)
No hay `runtime.txt`, `.python-version`, `Procfile`, ni `railway.json`/`nixpacks.toml`. **Riesgo para Fase 8:** Railway elegirá una versión de Python por defecto (probablemente 3.11–3.13) distinta del 3.14 local. El código usa `from __future__ import annotations` y sintaxis moderna de tipos (`str | None`), que funciona en 3.10+, así que **debería** correr en cualquier 3.11+. Pero conviene fijar la versión para reproducibilidad y definir el comando de arranque. Recomendación (para deployments-expert en F8): añadir un pin de Python (p. ej. `.python-version` con `3.12`) y un `Procfile`/`railway.json` con `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. El `app/main.py` ya lee `$PORT` indirectamente vía el comando uvicorn; el healthcheck `GET /` ya existe (✅).

### B4 — `set_webhook` en el lifespan es tolerante a fallo (no tumba el arranque) — bien, pero puede dejar el bot "vivo pero sordo"
`/Users/davidhoyos/Clientes/AskDB/app/main.py:45-54`. Si `set_webhook` falla (token inválido, sin red), el servidor arranca igual y el healthcheck responde 200, pero el bot no recibe nada. Es una decisión razonable (no tumbar el server), pero en producción conviene que un fallo de registro de webhook sea visible (alerta/Sentry), no solo un `logger.exception`. Recomendación: cuando se conecte Sentry (F8), asegurar que ese log se capture.

### B5 — `transcribe()` crea un cliente Groq nuevo por cada nota de voz
`/Users/davidhoyos/Clientes/AskDB/app/transcription/transcribe.py:50`. Crea `Groq(...)` en cada llamada. Costo bajo (es solo construcción de cliente HTTP), pero igual que con Anthropic/pool, podría ser singleton. Optimización menor, sin impacto funcional.

---

## Lo que está MUY bien (para no perderlo de vista)

- **Seguridad SQL en 3 capas, real y probada.** Validador por tokens del parser (no por texto, evita falsos positivos en literales), bloqueo de escritura/DDL/admin, una sola sentencia, sin `;`, sin comentarios, LIMIT forzado, + rol DB read-only + `SET TRANSACTION READ ONLY` + `statement_timeout`. Probé bypasses adversariales y no encontré ninguno que permita escribir/borrar.
- **DoS por funciones (`pg_sleep`) cortado por `statement_timeout` (8s)**, verificado e2e en Fase 2. `pg_read_file`/`pg_sleep` pasan el validador (son funciones SELECT) pero la capa DB (rol sin superuser) y el timeout son la defensa correcta — defensa en profundidad bien entendida.
- **Cero fuga de SQL/errores al usuario en Telegram.** Todos los caminos (éxito, fallo de validación, error de Postgres, fallo de gráfica/Excel) terminan en mensaje saneado en español; los detalles solo van al log del servidor. El CLI muestra SQL/errores a propósito (es dev tool), correcto.
- **Secretos:** `.gitignore` cubre `.env` y `.env.*`; solo `.env.example` está trackeado y tiene solo placeholders; no hay secretos hardcodeados ni se loguea la API key ni el `DATABASE_URL`. El `DATABASE_URL` de runtime usa el rol `askdb_readonly` (verificado).
- **Modelo de IA correcto:** `claude-sonnet-4-6` es un ID válido y vigente (verificado).
- **`asyncio.to_thread`** usado bien para no bloquear el event loop con el cerebro síncrono y con Groq.
- **Descriptores de archivo:** los `with open(...)` para enviar foto/documento a Telegram cierran bien; `chart.py` cierra SIEMPRE la figura matplotlib (`plt.close` en `finally`) — clave en un proceso de larga vida.

---

## Veredicto

**Casi listo para producción (Fase 8), pero NO desplegar sin resolver A1 y A2.**

Bloqueantes antes de exponer el bot:
1. **A1** — borrar `.env.rtf` del disco y confirmar que la key de Anthropic ya fue rotada.
2. **A2** — capturar los errores de la API de Anthropic / `RuntimeError` en `answer_question` (o al menos devolver mensaje saneado en vez de propagar), para que un 429/timeout/5xx no tumbe el turno ni reviente el CLI.

Recomendado antes del despliegue (rápidos y de alto valor): M1 (None-guard en handlers), M2 (`hmac.compare_digest`), M5 (`check` en el pool por la pausa de Neon), B3 (pin de Python + Procfile/railway.json — corresponde a deployments-expert en F8), y mantener **1 sola réplica** en Railway (B1).

El resto (M3, M4, M6, B2, B4, B5) son higiene/pulido que pueden ir después del primer despliegue.

La arquitectura y la postura de seguridad son de nivel senior. No hay deuda técnica grave. Con A1+A2 resueltos, el proyecto está en condiciones de pasar a despliegue.
