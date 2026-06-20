# Auditoría de verificación (2ª vuelta) — AskDB

- **Fecha:** 2026-06-19
- **Auditor:** Auditor (subagente, De cero a uno)
- **Alcance:** Verificar que las desviaciones de PROCESO señaladas en la 1ª auditoría
  (`auditoria-2026-06-19.md`) se cerraron, y que el propio proceso de review+arreglo
  (rigor y trazabilidad) se hizo bien. NO se audita calidad del código ni funcionamiento.
- **Material revisado:** `prd.md`, `progress.md`, `CLAUDE.md` del proyecto; los 4 informes en
  `docs/revisiones/`; `git log` (12 commits) y `git show 5bc8f05`; `.gitignore`, archivos
  trackeados, búsqueda de secretos en `git log -p --all`; `.python-version`, `Procfile`, tests.

## Veredicto

**ALINEADO. Apto para pasar a Fase 8.** Las desviaciones de la 1ª vuelta están cerradas con
evidencia. El proceso de review+arreglo fue riguroso y trazable: 4 informes guardados, un commit
único que mapea cada hallazgo a su arreglo, y una prueba por cada endurecimiento. Solo queda 1
deriva cosmética de bajo riesgo (número de versión de Python en un doc) y los pendientes de David
para producción, ya correctamente listados. Ninguno bloquea F8.

---

## Estado de cada desviación previa

| # (1ª vuelta) | Desviación | Estado | Evidencia |
|---|---|---|---|
| Media 1 | Entrevista por rondas no documentada (PRD nació de spec madre) | ✅ **Cerrada** | `prd.md` líneas 10–14: nota "Origen del PRD (proceso)" explica que se derivó de un spec ya escrito por David que cubre los 12 temas mínimos, por eso no aplicó la entrevista por rondas, y que las decisiones posteriores se validaron una a una en §10. Exactamente la corrección de raíz propuesta. |
| Baja 2 | Higiene de la API key comprometida / `.env.rtf` | ✅ **Cerrada** | El code-architect halló que el `.env.rtf` seguía en disco (A1). Tras el fix: `ls .env*` ya no lo muestra; `git ls-files` no trackea ningún `.rtf`; `git log --all -- .env.rtf` vacío (nunca commiteado); búsqueda de patrón `sk-ant-…` real en `git log -p --all` no arroja secretos (solo placeholders). Key rotada (progress, prueba en vivo OK). |
| Baja 3 | Deriva de versión de Python (docs 3.11+ vs venv 3.14) | 🟡 **Parcial** | Resuelto para despliegue: `.python-version` = **3.12** + `Procfile` creados (deuda de F8 cerrada). Pero `CLAUDE.md` línea 13 aún dice "Python 3.11+". Inconsistencia cosmética, no de proceso. |
| Baja 4 | Verificar ID de modelo Anthropic vigente | ⚪ **Fuera de mi alcance** | Es verificación técnica (code-architect/integrations); el default sigue configurable por entorno. No es desvío de proceso. |
| — Deriva de estado en docs (quality reviewer: CLAUDE.md "F3 siguiente") | ✅ **Cerrada** | `CLAUDE.md` del proyecto líneas 44–48 ahora declara F0–F7 ✅ (128 tests) y **F8 → siguiente**, coherente con `progress.md` (F0–F7 ✅, F8 pendiente). |

## Evaluación del proceso de review + arreglo

| Criterio | Estado | Evidencia |
|---|---|---|
| 4 informes de la 1ª vuelta guardados | ✅ Cumple | `docs/revisiones/`: `code-architect-`, `tester-`, `auditoria-`, `calidad-2026-06-19.md`. Rigurosos: severidades, citas `archivo:línea`, pruebas adversariales documentadas (CTEs que escriben, smuggling por `;`, COPY, SET → todos bloqueados). |
| `progress.md` registra la review y el lote de arreglos con su commit | ✅ Cumple | Sección "Bitácora — Review completa + endurecimiento pre-F8": lista los 4 subagentes, el veredicto (0 críticos), los arreglos por categoría (seguridad/robustez/copy/tests/docs/deploy) y lo diferido (B4 Sentry → F8). |
| El commit documenta qué se arregló | ✅ Cumple | `5bc8f05` mapea cada arreglo a su hallazgo (A1, M2, denylist; A2/B2, M5, M1, M3, B5; B1, I1, I2; +34 tests; docs; deploy). Coautoría declarada. |
| "Un arreglo → su prueba" | ✅ Cumple | El commit suma **+34 tests** (total 162/162): denylist y FETCH en `test_validate_sql.py` (+66 líneas); handlers async con `pytest-asyncio`/AsyncMock en `test_telegram_handlers.py` (+289 líneas, 18 tests async); robustez de `answer_question` en `test_execute_autocorrect.py` (+101 líneas). |
| Reglas duras como proceso siguen vigentes | ✅ Cumple | Read-only (rol `askdb_readonly`, DELETE rebota a nivel DB); no exponer SQL/errores (mensaje saneado + log servidor, reforzado: copy ya no filtra nombre de columna); `config.py` única zona; separación herramienta/cliente intacta (todo en `/Clientes/AskDB/`, registrado en INDEX + stub). Los arreglos **refuerzan** estas reglas (2ª barrera de denylist en app, `hmac.compare_digest` en webhook). |
| Pendientes de producción claros | ✅ Cumple | `progress.md` lista los de David para F8: BotFather (`TELEGRAM_BOT_TOKEN`), `ALLOWED_CHAT_IDS`, `WEBHOOK_SECRET`, `GROQ_API_KEY`; y el diferido B4 (Sentry para visibilidad de `set_webhook`). |

## Desviaciones residuales por severidad

### Alto / Medio
- Ninguno.

### Bajo
1. **`CLAUDE.md` (proyecto) línea 13 dice "Python 3.11+"**, mientras `.python-version` fija 3.12 y el
   venv corre 3.14. Cosmético, no contradice el proceso.
   - **Corrección de raíz:** alinear el número citado en `CLAUDE.md` con `.python-version` (3.12) al
     cerrar F8. Barato; evita confusión futura.

## Recomendaciones (no bloqueantes para F8)

1. Al marcar F8 hecha, alinear la versión de Python en `CLAUDE.md` (residual baja #1).
2. **Recordatorio §9 del estudio (CLAUDE.md del estudio):** AskDB es el primer proyecto en entrar a
   producción → al desplegar en F8, activar la **guardia de producción** y el **pulso de analítica**
   listados en `Automatizaciones.md`. Es el momento correcto según `objectives.md` ("la seguridad no
   se negocia").
3. Patrón a institucionalizar: review por 4 subagentes + commit único que mapea hallazgo→arreglo→test
   es un buen estándar de cierre de hito; vale como referencia para otros proyectos.

---

*Auditoría de proceso (verificación). No modifica código ni archivos del proyecto, no hace commit.*
