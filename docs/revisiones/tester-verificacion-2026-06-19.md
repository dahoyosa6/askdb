# Verificación de QA (2ª vuelta) — AskDB

- **Fecha:** 2026-06-19
- **Revisor:** Tester Expert (De cero a uno)
- **Alcance:** verificar que los huecos del informe `tester-2026-06-19.md` quedaron cerrados tras el commit `5bc8f05`, y evaluar la CALIDAD de los tests nuevos (que no sean de humo). Solo reporte; sin tocar código ni commit.
- **Comando:** `pytest -q` sobre `venv` (Python 3.14.5), con `DATABASE_URL` read-only configurada (los tests de DB corrieron contra Neon, no se saltaron).

---

## 1. Estado de la suite (resultado EXACTO)

```
162 passed, 164 warnings in 3.41s
```

- **162 verdes, 0 fallos, 0 skips.** Subió de 128 → 162 (**+34 tests**), igual que declara el commit.
- Conteo por archivo (collect-only): validate 52 (era 41, **+11**), autocorrect 15 (era 6, **+9**), handlers async 18 (**nuevo**), router 14, telegram_bot 18, transcribe 6, generate_sql 7, schema 6, memory 6, chart 6, spreadsheet 5, conn 4, main_webhook 5.
- **Warnings (164):** son nuevos respecto al informe anterior (1 warning → 164). **Todos provienen de `pytest-asyncio` en Python 3.14**, no del código de AskDB: `DeprecationWarning: 'asyncio.set/get_event_loop_policy' is deprecated and slated for removal in Python 3.16`. **No bloqueante**, pero conviene anotarlo para mantenimiento: cuando se suba a Python 3.16 o a una versión más nueva de `pytest-asyncio`, habrá que actualizar. No afecta la corrección de los tests hoy.
- Config verificada: `pytest.ini` con `asyncio_mode = auto` (por eso las `async def` corren sin decorador). Correcto.

**Veredicto de la suite:** verde, rápida, sin red salvo los tests de DB (intencional).

---

## 2. Verificación hueco por hueco

### Hueco #1 — Handlers async → **CERRADO** (calidad alta)

`tests/test_telegram_handlers.py` existe (18 tests, `pytest-asyncio`, `AsyncMock` del `context.bot`; nunca toca red/DB/Anthropic). Verifiqué cada caso que pedí y leí los asserts y el handler real (`app/interfaces/telegram_bot.py`) para confirmar que el test prueba la realidad, no una ficción:

- **No autorizado NO llama al cerebro:** ✅ El fixture `_entorno` reemplaza `procesar_pregunta` por uno que lanza `AssertionError` si se invoca. Así, el test de no-autorizado **falla solo si el cerebro se ejecutara**. Es la forma fuerte de probar "NO se llamó". Asserts estrictos: `send_message.assert_awaited_once_with(CHAT_NO, _TEXTO_NO_AUTORIZADO)` (texto y chat exactos).
- **Rate-limit NO llama al cerebro:** ✅ mismo mecanismo, `RateLimiter(max_per_min=0)`.
- **Orden de guards (allowlist ANTES de rate limit):** ✅ test dedicado: con rate-limit en 0 y chat no autorizado, recibe `_TEXTO_NO_AUTORIZADO` (no el de rate-limit). Cierra el riesgo que señalé de reordenar guards.
- **Camino feliz texto:** ✅ envía el texto del router y assert `"SELECT" not in enviado`.
- **Camino feliz gráfica:** ✅ `send_photo` awaited y `send_message.assert_not_awaited()`.
- **Excepción del cerebro → solo `_MENSAJE_GENERICO`, NUNCA `str(exc)`/SQL:** ✅ **el test clave.** El fake lanza `RuntimeError("SELECT secreto FROM tabla -- boom interno")` y el test verifica `assert_awaited_once_with(CHAT_OK, _MENSAJE_GENERICO)` **y además** `"SELECT" not in enviado` **y** `"boom interno" not in enviado`. Esto prueba la regla dura en el punto exacto (el `except` frontera del handler). Antes no tenía red; ahora sí.
- **Voz larga:** ✅ `_TEXTO_VOZ_MUY_LARGA` y `get_file.assert_not_awaited()` (no gasta Groq).
- **Voz vacía:** ✅ transcripción "   " → `_TEXTO_VOZ_NO_ENTENDIDA`, sin llamar al cerebro.
- **Voz feliz:** ✅ eco "🎤 Entendí" + respuesta del router.
- **None-guard:** ✅ tres tests (texto, voz, comando) con `effective_chat=None/message=None` → no revienta, no envía.
- **Comandos:** ✅ /start, /help (no-autorizado), /reset (verifica que llama `memory.reset(CHAT_OK)` y confirma con `_TEXTO_RESET`).

**Calidad:** ALTA, no de humo. Asserts por valor exacto (chat + texto literal), uso del "cerebro prohibido" para probar negativos, y verificación explícita de no-fuga de SQL/excepción. **Ningún test que pase sin probar nada.**

### Hueco #2 — Lectura peligrosa §5 (denylist) → **CERRADO** (calidad alta)

Implementación real verificada en `app/agent/validate_sql.py`: existe `FORBIDDEN_FUNCTIONS` (`pg_read_file`, `pg_read_binary_file`, `pg_ls_dir`, `lo_import`, `lo_export`, `dblink`) y la detección por token (Name seguido de `(`), insensible a mayúsculas. Tests (`test_validate_sql.py` §8):

- **Bloquea:** ✅ 6 vectores parametrizados (`test_bloquea_funciones_peligrosas_por_nombre`) — los mismos que reporté en vivo.
- **No falsos positivos en SELECT legítimo:** ✅ `'pg_read_file backup'` dentro de literal pasa; **y** `SELECT lo_importante FROM productos` pasa (el test del substring `lo_import` ⊂ `lo_importante` — exactamente el riesgo de una denylist mal hecha; está cubierto).
- **Documentación de comportamiento residual:** ✅ `pg_shadow` (vista, no función) pasa la capa app y lo corta el rol DB — documentado en test; `pg_sleep` igual.

**Matiz justo:** la denylist es defensa-en-profundidad por nombre, no un parser de funciones completo (no cubriría alias raros o `pg_read_file` invocado vía `EXECUTE`/dynamic — pero `EXECUTE` ya está en `FORBIDDEN_KEYWORDS`). El muro real sigue siendo el rol DB; la app es ahora 2ª barrera real y documentada. Suficiente y honesto.

### A2 — Errores de Anthropic recuperables → **CERRADO** (calidad alta)

`test_execute_autocorrect.py` §A2 (4 tests nuevos), implementación en `execute.py` (clasifica `anthropic.APIError` y subclases de saturación):

- **RateLimit agota intentos → ok=False saneado:** ✅ `result.ok is False`, `"saturado" in msg`, y **no fuga**: `"Traceback"`, `"RateLimit"`, `"429"` todos ausentes del mensaje. Estricto.
- **APIStatusError 5xx (`InternalServerError`) no se propaga:** ✅ ok=False, mensaje "saturado".
- **Error transitorio (1er intento) → reintenta y converge:** ✅ ok=True, attempts=2.
- **RuntimeError de generate (tool_use ausente) recuperable:** ✅ ok=True tras reintento.

No propaga la excepción fuera de `answer_question`; devuelve `ok=False` saneado. Bien.

### M3 — FETCH FIRST/NEXT → **CERRADO**

`validate_sql.py` `_has_top_level_limit` detecta `LIMIT` **y** `FETCH`. Tests: `test_respeta_fetch_first_y_no_inyecta_limit` y `test_fetch_first_con_offset_no_inyecta_limit` verifican que NO se añade `LIMIT` (que produciría SQL inválido) y que el `FETCH` sobrevive. Correcto.

### Copy del router (B1 / vacío / captions) → **CERRADO** y **REFORZADO**

El cambio en `test_output_router.py` (las únicas 6 líneas de test tocadas en un archivo preexistente) **endurece** la aserción, no la relaja:
- 1x1: antes `"830" in out.text`; ahora `out.text == "830."` **y** `"total" not in out.text` (verifica que ya NO se filtra el nombre técnico de columna — el arreglo B1 está realmente probado).
- 0 filas: assert al copy nuevo `"No encontré datos"`.
Caption de gráfica: ahora es string estático humano (`"Aquí tienes la gráfica de tu consulta."`), por lo que el riesgo de inversión de columnas que señalé desaparece; el caption no se asierta en el router pero ya no es load-bearing.

---

## 3. Regresiones — ninguna

- Los 128 originales siguen verdes dentro de los 162.
- `git show 5bc8f05 -- tests/`: el commit **solo AÑADE** tests (autocorrect +101 líneas, validate +66, handlers +289 nuevo, transcribe +29) y modifica 6 líneas de router que **endurecen** asserts. **Ningún archivo de test borrado.**
- **No se debilitó ninguna aserción para que pasara.** El único cambio en un test viejo (router B1) va en dirección más estricta. No hay relajaciones del tipo "cambiar `==` por `in`" ni asserts comentados.

---

## 4. Huecos que QUEDAN (no bloqueantes)

1. **End-to-end real del pipeline F1** (generate→validate→run contra Neon) sigue sin test automatizado; cubierto por prueba manual en vivo (830 pedidos) registrada en progress. Aceptable para MVP; ideal para v2.
2. **Warnings de `pytest-asyncio` en Py 3.14** (164): ruido de librería, no bug. Anotar para mantenimiento (Py 3.16 los volverá errores). Opcional: fijar `filterwarnings` o subir `pytest-asyncio`.
3. **Webhook → routing real:** `test_main_webhook.py` sigue parcheando `Update.de_json`; el tramo POST→handler concreto no se prueba end-to-end (mismo estado que la 1ª vuelta; bajo riesgo, los handlers ya están cubiertos por separado).
4. **Denylist por nombre** no cubre invocación dinámica exótica (mitigado: `EXECUTE`/`PREPARE` ya bloqueados como keywords, y el rol DB es el muro real).

Ninguno bloquea F8.

---

## 5. Checklist de prueba manual EN VIVO (F8) — sigue vigente

La checklist del informe anterior (§6) se mantiene **sin cambios**: recorrer en Telegram tras desplegar a Railway (texto dato simple / gráfica / serie temporal / Excel; voz normal y muy larga; no autorizado; rate limit; /reset + follow-up con memoria; /start y /help; pregunta imposible → mensaje saneado sin SQL; webhook sin secreto → 403). Es la única capa no cubierta por automatización (integración real Telegram↔Groq↔Neon↔Anthropic).

---

## 6. Veredicto

**Tests automatizados: PASA.** 162/162 verdes. Los tres huecos de la 1ª vuelta (handlers async, denylist de lectura peligrosa, robustez ante errores de Anthropic) están **cerrados con tests de calidad alta y aserciones estrictas**, no de humo: el punto más sensible (excepción del cerebro → solo mensaje genérico, nunca SQL/`str(exc)`) ahora tiene red de seguridad explícita. Sin regresiones; ningún test debilitado.

**Veredicto para F8 (despliegue): PASA.** Se levanta la condición que dejé en la 1ª vuelta (el hueco de handlers async ya está cerrado). Recomendación previa al deploy: recorrer la checklist manual en vivo (es la única capa sin automatizar) y anotar los warnings de pytest-asyncio para mantenimiento. La denylist y la cobertura de seguridad son ahora defensa-en-profundidad real y documentada.
