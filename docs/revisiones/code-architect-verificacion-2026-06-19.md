# Verificación de arreglos (2ª vuelta) — AskDB

- **Revisor:** Code Architect (subagente, De cero a uno)
- **Fecha:** 2026-06-19
- **Alcance:** Verificar que cada hallazgo del informe `code-architect-2026-06-19.md` quedó resuelto DE FONDO tras el commit `5bc8f05`, y cazar regresiones/bugs nuevos introducidos por los arreglos.
- **Estado de pruebas:** `pytest -q` → **162 passed** (antes 128). +34 tests (denylist, FETCH, handlers async). Python 3.14.5 del venv.
- **Tipo:** solo lectura + pruebas adversariales en vivo del validador. NO se modificó código ni se hizo commit.

> Severidades: 🔴 Crítico · 🟠 Alto · 🟡 Medio · 🟢 Bajo.

---

## Resumen ejecutivo

Los 18 hallazgos del informe anterior están **resueltos de fondo**, no parcheados: los arreglos atacan la causa, tienen tests nuevos y resisten pruebas adversariales. La seguridad de escritura/escalación sigue **intacta** (reverifiqué CTE-write, `SELECT INTO`, smuggling por `;` y comentarios, `COPY`, `SET`, `UPDATE` → todos bloqueados). El manejo de excepciones nuevo está bien acotado (tupla de tipos, no `except` desnudo: `KeyboardInterrupt`/`SystemExit`/`KeyError`/`AttributeError` siguen propagándose). El copy del router solo cambia presentación, sin tocar la heurística de enrutado. El singleton de Groq no introduce un problema real de concurrencia.

**Pero la 2ª vuelta encontró 1 hallazgo NUEVO en la propia denylist agregada (B5-NEW, 🟡 Medio):** un nombre de función entre comillas dobles —`SELECT "pg_read_file"('/etc/passwd')`, válido en Postgres— **evade la denylist**. La barrera no-evitable (rol read-only de la DB) sigue cubriendo esto hoy, así que es degradación de defensa-en-profundidad, no un agujero explotable en Northwind. Conviene cerrarlo antes de conectar una DB de cliente con rol más permisivo.

**Veredicto:** listo para F8. B5-NEW no es bloqueante (no hay regresión de seguridad real; la capa DB lo cubre), pero debe corregirse en el primer ciclo post-deploy.

---

## Tabla de verificación por ID

| ID | Hallazgo original | Estado | Evidencia |
|----|-------------------|--------|-----------|
| **A1** | `.env.rtf` con key en disco | ✅ RESUELTO | `ls .env.rtf` → *No such file*. No estaba trackeado por git (verificado antes). Borrado de fondo. |
| **A2 / B2** | `answer_question` no captura errores de Anthropic/`RuntimeError`; no loguea request_id; CLI sin envolver | ✅ RESUELTO | `execute.py:67-72` define `_ERRORES_RECUPERABLES = (SQLValidationError, psycopg.Error, RuntimeError, anthropic.APIError)`; loop los trata como recuperables y reinyecta feedback saneado (`:281-311`), nunca propaga. Mensaje saneado `_MENSAJE_FALLO`/`_MENSAJE_SATURADO` (`:50-59`). `_request_id` logueado para saturación y otros `APIError` (`:294-302`). CLI envuelto en try/except con mensaje saneado (`cli.py:94-98`). |
| **M1** | None-guards en handlers | ✅ RESUELTO | `telegram_bot.py:236-237` (handle_text), `:290-291` (handle_voice), `:345` (cmd_start): `if update.effective_chat is None or update.message is None: return` ANTES de cualquier acceso. |
| **M2** | Webhook secret sin tiempo constante | ✅ RESUELTO | `main.py:87` `return hmac.compare_digest(recibido or "", settings.webhook_secret)`. Fallo cerrado intacto (`:82-83` rechaza si no hay secreto). No volvió a comparación normal. |
| **M3** | `_has_top_level_limit` no detecta FETCH → LIMIT inválido | ✅ RESUELTO | `validate_sql.py:178-180` detecta `LIMIT` **y** `FETCH`. Probado: `… FETCH FIRST 5 ROWS ONLY` y `… fetch next 3 rows only` PASAN **sin** inyectar LIMIT (no produce SQL inválido). `LIMIT` existente se respeta; sin límite se inyecta. |
| **M5** | Pool sin `check` (pausa de Neon) | ✅ RESUELTO | `execute.py:112-113` `check=ConnectionPool.check_connection` + `max_idle=120.0`. Valida/recicla conexiones zombi al sacarlas. (Ver nota de rendimiento abajo: impacto bajo y aceptable.) |
| **M6** | Docstrings desactualizados (information_schema / Supabase) | ✅ RESUELTO | `schema.py:3-9,39-40,91` ahora distinguen bien: columnas/tipos de `information_schema.columns`, PK/FK de `pg_catalog` (esto es **correcto**, coincide con el código). `check_conn.py:3` dice Neon. `requirements.txt:9` dice "Postgres (Neon)". |
| **B1** | Estado en RAM, no multi-instancia | ✅ RESUELTO (doc) | Documentado en PRD/progress; mantener 1 réplica en Railway. Sin cambio de código (correcto para v1). |
| **B2** | No loguea request_id de Anthropic | ✅ RESUELTO | Incluido en A2: `getattr(exc, "_request_id", None)` logueado (`execute.py:294-302`). |
| **B3** | Sin pin de Python / Procfile | ✅ RESUELTO | `.python-version` y `Procfile` añadidos en el commit. (Detalle fino corresponde a deployments-expert en F8.) |
| **B4** | `set_webhook` tolerante a fallo | ✅ ACEPTADO | Decisión razonable; se cubrirá con Sentry en F8. Sin cambio. |
| **B5** | Cliente Groq por llamada | ✅ RESUELTO | `transcribe.py:32-45` singleton perezoso `_get_client()` (mismo patrón que pool/Anthropic). |
| **§5** | Denylist de funciones peligrosas: ¿falsos positivos / huecos? | ⚠️ RESUELTO con 1 hueco nuevo | Ver detalle abajo. Cubre mayúsculas, espacios y **esquema calificado** (`pg_catalog.pg_read_file` → BLOCK). Sin falsos positivos en columnas/literales/alias. **Hueco:** identificador entre comillas dobles (B5-NEW). |

**Conteo de verificación:** 11 RESUELTOS de fondo · 2 aceptados por diseño (B1 doc, B4) · 0 NO RESUELTOS · 1 hallazgo NUEVO.

---

## §5 — Denylist: pruebas adversariales (detalle)

Ejecuté el validador real (`validate_and_secure`) contra una batería. Resultados:

**Bloquea correctamente (defensa OK):**
- `pg_read_file('/etc/passwd')` → BLOCK
- `PG_READ_FILE(...)` / `Pg_Read_File(...)` (mayúsculas/mixto) → BLOCK
- `pg_read_file ('...')` (espacio antes del paréntesis) → BLOCK
- `pg_read_file\n('...')` (salto de línea) → BLOCK
- `pg_catalog.pg_read_file('...')` (**esquema calificado**) → BLOCK
- `dblink`, `lo_import`, `lo_export`, `pg_ls_dir`, `pg_read_binary_file` → BLOCK

**NO da falsos positivos (consultas legítimas PASAN):**
- columna `lo_importante`, literal `'pg_read_file'`, alias `dblink_count`, columna `import_date` → todas PASS. La heurística (Name seguido de `(`) es correcta.

**Seguridad de escritura/escalación reverificada (todas BLOCK):**
- CTE-write `WITH x AS (DELETE … RETURNING *) SELECT …`, `SELECT … INTO newt`, smuggling por `;`, smuggling por comentario `/* */ ;`, `COPY`, `SET ROLE`, `UPDATE`.

---

## Hallazgo NUEVO

### 🟡 B5-NEW — Función entre comillas dobles evade la denylist
`/Users/davidhoyos/Clientes/AskDB/app/agent/validate_sql.py:153-162`

`SELECT "pg_read_file"('/etc/passwd')` **PASA** el validador (debería BLOCK). En Postgres ese SQL es una llamada **válida** a la función (las comillas dobles son una forma legítima de citar identificadores/nombres de función). Variantes verificadas que también evaden: `"pg_catalog"."pg_read_file"(1)`, `pg_catalog."pg_read_file"(1)`, `"dblink"(1,2)`, `"lo_import"(1)`.

**Causa raíz:** sqlparse tokeniza `"pg_read_file"` como `Token.Literal.String.Symbol`, **no** como `Token.Name`. El chequeo de la denylist exige `actual.ttype is T.Name` (`:154`), así que el caso citado nunca entra a la comparación. El `.value.strip('"').lower()` de la línea `:157` (que el comentario presenta como si manejara las comillas) **nunca se ejecuta** para este caso — el comentario es engañoso.

**Severidad: Medio.** No es explotable hoy: el rol read-only de la DB (barrera no-evitable, ya verificado: `pg_read_file` rebota con InsufficientPrivilege) cubre esto. Es degradación de la **segunda barrera de defensa-en-profundidad** que el propio commit quiso fortalecer — y justo el escenario para el que se creó la denylist (DB de cliente con rol más permisivo) es donde fallaría.

**Recomendación:** incluir `T.Literal.String.Symbol` en el chequeo (o normalizar el nombre quitando comillas para ambos ttypes) y añadir un test con `"pg_read_file"(...)`. Cierra el hueco sin tocar la lógica de escritura. No bloquea F8.

---

## Regresiones evaluadas (sin hallazgos)

- **`except _ERRORES_RECUPERABLES` ¿captura de más?** No. Es una **tupla de tipos concretos**, no `except Exception` ni `except:`. `KeyboardInterrupt`/`SystemExit` (no heredan de `Exception`) y errores de programación (`KeyError`, `AttributeError`, `TypeError`, `NameError`) **propagan** y se verán. `RuntimeError` es el único amplio; sus fuentes en el loop son legítimamente recuperables (tool_use ausente de `generate_sql`). Las `RuntimeError` de config (falta `ANTHROPIC_API_KEY` en `get_client()`, falta `DATABASE_URL` en `get_schema()`) se lanzan **antes** del loop (`execute.py:255-258`), así que propagan correctamente y no se enmascaran. Un fallo transitorio de API ya no tumba el turno: se reintenta o devuelve `ok=False` saneado. ✅
- **Pool con `check` — ¿rendimiento / nuevos modos de fallo?** `check_connection` hace un ping ligero al sacar la conexión del pool; costo marginal frente a la latencia de la consulta y de la API de IA. Si la conexión está muerta (pausa de Neon), el pool la recicla en vez de devolver una zombi → menos fallos, no más. `max_idle=120s` cierra ociosas antes de que Neon las mate. `run_query` ya hace `conn.rollback()` en error antes de devolver al pool (`:170`). Sin nuevo modo de fallo. ✅
- **Singleton de Groq — ¿concurrencia bajo `to_thread`?** `_get_client()` no tiene lock; dos notas de voz concurrentes podrían crear dos clientes en la carrera del `is None`. Inocuo: gana la última escritura, el cliente Groq es stateless para `.create()`. Mismo patrón que pool/Anthropic ya existentes. No es regresión. ✅
- **Copy del router — ¿rompe casos?** Solo cambia strings de presentación en `_formatear_texto` y captions (`router.py`); la heurística `elegir_formato` (decisión texto/gráfica/Excel) está **intacta**. Tests cubren los caminos (162 verdes). ✅
- **None-guards — ¿rompen `cmd_start`/otros?** `cmd_start` chequea solo `effective_chat` (no usa `update.message`), correcto. ✅

---

## Veredicto

**Listo para Fase 8 (despliegue).** Los 2 bloqueantes anteriores (A1, A2) están resueltos de fondo, los Medios recomendados (M1, M2, M5) también, y la seguridad de escritura/escalación sigue siendo de nivel senior y reverificada. La suite creció a 162 tests verdes.

**Único pendiente recomendado (no bloqueante): B5-NEW** — cerrar el hueco de la denylist con nombres de función entre comillas dobles. Hoy lo cubre el rol read-only de la DB; corregirlo antes de conectar AskDB a una base de cliente con un rol más permisivo. Es un cambio de ~2 líneas + 1 test.
