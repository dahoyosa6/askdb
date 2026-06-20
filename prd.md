# PRD — AskDB · "Habla con tus Datos" (v1)

> Fuente de verdad del proyecto. Derivado del spec/contrato que escribió David.

- **Cliente:** Portafolio propio de David (producto demostrable, replicable para PYMES).
- **Fecha:** 2026-06-19
- **Responsable (De cero a uno):** David (Head of Project: Claude)
- **Estado:** Aprobado (spec madre)

---

## 1. Problema y objetivo
- **Problema real:** miles de PYMES tienen sus datos atrapados en un POS o Excel, y quien
  decide no sabe (ni quiere) escribir consultas para sacarlos. Consultar sus propios datos
  es demasiada fricción, así que deciden a ciegas.
- **Objetivo:** un agente conversacional que recibe una pregunta en lenguaje natural (texto
  o voz) por Telegram, la traduce a SQL **seguro de solo lectura**, la ejecuta contra la base
  y responde en el formato adecuado (texto / gráfica / Excel), con memoria conversacional.
- **Métrica de éxito:** Marta (usuaria ficticia) obtiene respuestas correctas a sus preguntas
  típicas sin saber SQL; el sistema es **replicable y barato de operar** para venderlo a clientes.

## 2. Usuarios
- **Usuario final:** **Marta**, dueña de una ferretería de ~15 empleados. No sabe SQL. Hoy
  revisa ventas en Excel los domingos. Preguntas típicas: "¿qué productos no he vendido en
  2 meses?", "¿quién es mi mejor cliente este trimestre?", "¿cómo van las ventas de este mes
  contra el anterior?". Cada respuesta es una decisión de compra/inventario.
- **Contexto de uso:** desde el celular, por Telegram (texto o nota de voz), informal.
- **Datos v1:** base **Northwind** (Postgres) como sustituto del POS de Marta. Estándar de la
  industria que cualquier revisor técnico reconoce.

## 3. Alcance
**Incluye (v1):**
- Pregunta en lenguaje natural (texto o voz) → SQL → resultado.
- Introspección del esquema (tablas, columnas, tipos, relaciones), cacheada, inyectada al modelo.
- Guardrails de seguridad (ver §6): solo SELECT, bloqueo DDL/DML, LIMIT, validación previa.
- Loop de auto-corrección (≤3 reintentos leyendo el error de Postgres).
- Memoria conversacional corta (follow-ups en la misma conversación).
- Selección automática de formato de salida (texto / gráfica PNG / Excel-CSV).
- Glosario de negocio (sinónimos del dominio) inyectado al contexto.

**NO incluye (explícito):**
- Insights/anomalías proactivas (solo responde lo que se le pregunta) → v2.
- Multi-tenant (la arquitectura debe *permitirlo* vía RLS, pero no se implementa).
- WhatsApp (v1 es Telegram; la API queda desacoplada para enchufarlo después).
- Dashboard web.
- Cualquier **escritura** a la base (read-only por diseño, sin excepción).
- Autenticación compleja (v1 = bot privado con allowlist de chat IDs).

## 4. Funcionalidades (historias de usuario)

### F1 — Pregunta → respuesta en texto
- **Historia:** Como Marta, quiero preguntar en español y recibir el dato, sin saber SQL.
- **Prioridad:** Must
- **Criterios:** dado un esquema cargado, cuando pregunto "¿cuántos pedidos hay?", entonces
  recibo el número en lenguaje natural.

### F2 — SQL seguro (guardrails)
- **Historia:** Como dueño del sistema, quiero que nunca se pueda escribir/borrar datos.
- **Prioridad:** Must
- **Criterios:** un intento de modificar datos es bloqueado **por la app Y por el rol de DB**.

### F3 — Auto-corrección
- **Prioridad:** Must · **Criterios:** si el SQL falla, el agente lee el error y reintenta (≤3)
  o falla con un mensaje claro, nunca un stacktrace al usuario.

### F4 — Formato de salida automático
- **Prioridad:** Must · **Criterios:** un dato → texto; tendencia/ranking → gráfica;
  detalle largo → Excel.

### F5 — Memoria conversacional
- **Prioridad:** Must · **Criterios:** un follow-up ("¿y el mes pasado?") se entiende sin repetir contexto.

### F6 — Bot de Telegram (texto y voz)
- **Prioridad:** Must · **Criterios:** allowlist de chat IDs; rate limit; nota de voz transcrita
  y procesada por el mismo pipeline.

## 5. MVP (primera versión)
Todos los "Must" de arriba: pregunta NL (texto+voz) → SQL seguro read-only → auto-corrección →
formato automático → memoria → bot Telegram con allowlist → desplegado en Railway.

## 6. Arquitectura (resumen)
- **Principio rector:** desacoplar el cerebro (API) de la interfaz (Telegram hoy, WhatsApp/web mañana).
- **Modelo de datos:** Northwind en **Neon Postgres** (14 tablas). La app lee con un rol
  **askdb_readonly** (solo SELECT). El owner solo se usa en setup.
- **Flujo:** mensaje → (voz→transcribir) → esquema+glosario+historial → Claude genera SQL →
  **validar** → ejecutar read-only → (si falla, auto-corregir ≤3) → elegir formato → responder.
- **Integraciones externas:** Anthropic (claude-sonnet-4-6), Telegram, Groq (voz), Neon (DB).
- **Decisiones técnicas / trade-offs:**
  - **Neon en vez de Supabase** para la DB: free tier de Supabase tope a 2 proyectos (Saku +
    Momentum, ambos en uso); Pro costaría ~$44/mes. La v1 no usa features propias de Supabase
    (solo Postgres SELECT), así que Neon da una base dedicada, aislada y **gratis**. Código idéntico.
  - **tool_use forzado** para que Claude devuelva SQL limpio (sin markdown).
  - **psycopg3 directo + pool** para control fino de `statement_timeout` y transacción read-only.
  - **Seguridad en 3 capas:** validación sqlparse (app) + LIMIT forzado + rol DB read-only.
  - **transcribe() como interfaz** intercambiable (Groq hoy).

## 7. Costos recurrentes estimados
- Hosting (Railway): ~5 USD/mes (Fase 8).
- Base de datos (Neon free): **0 USD**.
- IA (Anthropic, claude-sonnet-4-6): por uso; bajo en demo (~$3/M input, $15/M output).
- Voz (Groq Whisper): free tier.
- **Total operativo demo: ≈ 5 USD/mes.**

## 8. Riesgos
- Que el modelo alucine columnas → mitigado con introspección de esquema + glosario.
- Inyección/escritura maliciosa → mitigado con triple capa de seguridad.
- Northwind no representa exactamente un POS real → es un sustituto reconocido; v2 conecta datos reales.
- Neon free pausa/limita por inactividad → aceptable para demo; documentar.

## 9. Fuera de alcance / futuro (v2+)
- Insights proactivos, multi-tenant (RLS), WhatsApp, dashboard web, datos reales del cliente.

## 10. Registro de cambios al PRD
- 2026-06-19 — Creación del PRD desde el spec madre.
- 2026-06-19 — **DB cambia de Supabase a Neon** (límite free tier de Supabase; Neon gratis y aislado).
- 2026-06-19 — **Introspección de esquema vía `pg_catalog`, no `information_schema`**: bajo un rol
  de solo-SELECT, las vistas de constraints de `information_schema` salen vacías; sin esto Claude
  no vería PK/FK y alucinaría los joins. (Decisión técnica, Fase 1.)
- 2026-06-19 — **Inyección de LIMIT por append, no por envoltura**: añadir `LIMIT n` al final solo
  si no hay LIMIT a nivel superior. Envolver en subconsulta rompía `SELECT *` con columnas
  duplicadas (joins). Si el modelo pone su propio LIMIT, se respeta (cap duro en v2). (Fase 2.)
- 2026-06-19 — **DoS por funciones (`pg_sleep`) se mitiga con `statement_timeout` (8s)**, no en la
  capa de validación de la app (esa capa solo bloquea escritura/DDL). (Fase 2.)
- 2026-06-19 — **Auto-corrección: `max_sql_retries` (=3) = 3 intentos de generación EN TOTAL**
  (incluye el primero), no "1 intento + 3 reintentos". Al fallar un intento (`SQLValidationError`
  o `psycopg.Error`), se reinyecta el error saneado como `error_feedback` al siguiente
  `generate_sql`. Al agotar los 3, se devuelve un mensaje claro en español SIN SQL crudo ni error
  interno (el error real solo se loguea del lado servidor). (Fase 3.)
- 2026-06-19 — **Formato de salida (F4): "detalle largo" = Excel `.xlsx`** (no CSV; openpyxl ya
  instalado, más amigable para una PYME). **"Un dato" = cualquier resultado de 1 fila → texto**
  en el chat (un valor = frase; varias columnas = ficha en lista), nunca un archivo por una sola
  fila. (Decisiones de producto de David.)
- 2026-06-19 — **Heurística de formato DETERMINISTA (sin IA)** por forma del resultado (nº filas/
  columnas + tipos): gratis, predecible y testeable. Gráfica solo con 2 columnas (1 numérica +
  1 eje): línea si el eje es fecha, barras si es categórico. Si generar gráfica/Excel falla, el
  router cae a texto (nunca expone el error). El router vive en la capa de salida; `answer_question`
  permanece puro (solo datos). (Fase 4.)
- 2026-06-19 — **Memoria conversacional (F5) en RAM, no en la base.** La DB es read-only (regla
  dura), así que el historial NO puede persistirse ahí. Se usa un store en memoria del proceso
  (`dict` por `chat_id`). Consecuencia aceptada: se pierde al reiniciar el bot (persistencia = v2).
  Se recuerda **pregunta + SQL ejecutado** (no las filas), acotado a `memory_window` (=6 mensajes
  = 3 pares). El historial viaja en `messages` (no en `system`), así no rompe el prompt-caching.
  Se guarda solo en turnos exitosos. (Decisiones de producto de David + técnicas, Fase 5.)
