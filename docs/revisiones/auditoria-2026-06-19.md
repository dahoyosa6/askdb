# Auditoría de proceso y alineación — AskDB

- **Fecha:** 2026-06-19
- **Auditor:** Auditor (subagente, De cero a uno)
- **Alcance:** PROCESO y alineación con directrices (`CLAUDE.md` del estudio) y `objectives.md`.
  NO se audita calidad del código ni que funcione (eso es de `code-architect` / `tester-expert`).
- **Material revisado:** `prd.md`, `progress.md`, `CLAUDE.md` del proyecto; `git log` (11 commits);
  `.gitignore`; archivos trackeados; `proyectos/INDEX.md` y stub en el cerebro del estudio.

## Veredicto

**ALINEADO CON OBSERVACIONES.** El proyecto siguió el método del estudio con un rigor alto:
PRD-first, desarrollo por fases con prueba verde antes de avanzar, commit por fase, documentación
viva al día, secretos fuera del repo, delegación correcta y registro en el cerebro. Las
desviaciones detectadas son menores o ya están reconocidas y gestionadas en `progress.md`. No hay
desvíos de alto riesgo pendientes que bloqueen la continuación a Fase 8.

---

## Checklist con evidencia

### Proceso (CLAUDE.md §3–§6)

| Criterio | Estado | Evidencia |
|---|---|---|
| PRD aprobado antes de construir | ✅ Cumple | `prd.md` "Estado: Aprobado (spec madre)"; commit `50ba562` (Fase 0) ya parte de PRD. |
| Decisiones de fondo en `prd.md` con registro de cambios | ✅ Cumple | `prd.md` §10: 9 entradas de cambio fechadas (Neon, pg_catalog, LIMIT, DoS, retries, formato, memoria, webhook, voz). Ejemplar. |
| Desarrollo por fases, una a la vez | ✅ Cumple | F0→F7 secuenciales; cada fase su commit (`git log`). CLAUDE.md regla dura "no saltar fases; cada una cierra con prueba verde". |
| TDD — prueba antes de avanzar | ✅ Cumple | Suite acumulativa verde por fase: F0 4/4 → F2 58 → F3 63 → F4 88 → F5 100 → F6 118 → F7 128. Tablero en `progress.md`. |
| `prd.md` y `progress.md` al día | ✅ Cumple | `progress.md` con bitácora por fase, estado (~90% MVP), próximo paso (F8) y pendientes de David. Permite retomar sin contexto previo. |
| Ritual de cierre por fase (progress + commit) | ✅ Cumple | 11 commits con mensajes claros por fase; último (`4fb2400` Fase 7) consistente con el estado en `progress.md`. |
| Delegación correcta (lo pesado al equipo, Head verifica) | ✅ Cumple | Bitácoras anotan "delegado a code-architect reps N; verificado por el Head" (F4–F7); F2 a tester-expert adversarial. En F1 el Head detectó y corrigió un bug que el arquitecto marcó como `xfail` (verificación real, no ciega). |

### Seguridad y datos (reglas duras del proyecto)

| Criterio | Estado | Evidencia |
|---|---|---|
| Secretos solo en `.env` (gitignored) | ✅ Cumple | `.gitignore` cubre `.env` y `.env.*` con `!.env.example`. `git ls-files` solo trackea `.env.example`. |
| Sin secretos reales en la historia de git | ✅ Cumple | Búsqueda en `git log -p --all`: solo placeholders (`sk-ant-xxxx`, `[PASSWORD]`, `PASS@host`). Ningún secreto real. |
| `.env.example` sin secretos reales | ✅ Cumple | Solo placeholders `xxxx`. |
| `config.py` única zona de constantes, sin secretos hardcodeados | ✅ Cumple | `config.py` lee de entorno (`_get(...)`); sin claves embebidas. |
| Read-only sin excepción | ✅ Cumple (como proceso) | Rol `askdb_readonly`; `progress.md` documenta DELETE rebotado a nivel DB; admin URL inerte tras setup. (La validación funcional es de tester/code-architect.) |
| Nunca exponer SQL/errores al usuario | ✅ Cumple (como proceso) | Decisión registrada en PRD §10 (F3/F4/F6) y bitácoras: error saneado + log servidor; bot usa router, no toca `result.sql`. |

### Separación herramienta vs. cliente (CLAUDE.md §6·B)

| Criterio | Estado | Evidencia |
|---|---|---|
| Trabajo de AskDB en su propia carpeta | ✅ Cumple | Todo el código y docs viven en `/Users/davidhoyos/Clientes/AskDB/`. |
| Sin contaminar docs de herramienta del estudio | ✅ Cumple | `grep` en `Sistema-de-diseno/`, `Skills/`, `Agentes/`: AskDB no aparece. Solo en `proyectos/INDEX.md` y su stub (correcto). |
| Registrado en `proyectos/INDEX.md` + stub | ✅ Cumple | Entrada en INDEX (local + GitHub + stub + estado) y `proyectos/askdb/overview.md` presente. |

### Alineación con objetivos (objectives.md)

| Criterio | Estado | Evidencia |
|---|---|---|
| Sirve a un objetivo del estudio | ✅ Cumple | "Crear productos propios" + "Construir portafolio mostrable en GitHub": repo público, proyecto insignia replicable. |
| Respeta restricciones (barato, replicable, sin programar a mano) | ✅ Cumple | Costo demo ≈5 USD/mes (Neon $0); Neon elegido sobre Supabase justo por costo; arquitectura desacoplada para replicar. |
| Dentro de alcance (no en "fuera de alcance") | ✅ Cumple | Es software a la medida con IA; v2 (insights, multi-tenant, WhatsApp) explícitamente diferido en PRD §9. |

---

## Desviaciones por severidad

### Alto riesgo
- Ninguno.

### Medio riesgo
1. **Entrevista por rondas (AskUserQuestion) no documentada.** El CLAUDE.md §3 exige "al menos 3–5
   rondas" de interrogatorio antes de cerrar el PRD. Aquí el PRD nació de un "spec/contrato que
   escribió David" (PRD encabezado y estado "Aprobado (spec madre)"). Es **defendible** (el dueño
   trajo el spec maduro y completo, cubre los 12 temas mínimos), pero el `progress.md` solo dice
   "Entrevista cerrada" en una línea, sin dejar traza de qué se preguntó/confirmó.
   - **Corrección de raíz:** cuando el insumo de partida es un spec ya escrito (no una entrevista),
     dejarlo explícito en el PRD con una línea — "PRD derivado de spec del dueño; entrevista por
     rondas no aplica porque el alcance vino cerrado" — y, si quedó algún vacío de los 12 temas, una
     mini-ronda de validación. Evita la duda de si se saltó la fase obligatoria.

### Bajo riesgo
2. **Pendiente de higiene sin cerrar: rotación de API key comprometida.** El `progress.md` registra
   que se halló un `.env.rtf` con la key de Anthropic en texto plano (eliminado) y marca la rotación
   como hecha (`[x]`). Verificado: la key no está en la historia de git. Riesgo residual mínimo, ya
   gestionado; se deja como nota de cierre, no como acción.
   - **Corrección de raíz:** ya aplicada (key rotada, `.gitignore` desde commit 0). Sin acción.
3. **Deriva de versión de Python entre docs y entorno.** CLAUDE.md/PRD declaran "Python 3.11+" pero
   el `venv` corre 3.14. El propio `progress.md` (plan F8) ya lo señala como cosa a fijar para
   Railway. No es contradicción de proceso, es deuda menor a resolver en despliegue.
   - **Corrección de raíz:** fijar la versión de runtime (p. ej. `runtime`/`railway.json` o
     `.python-version`) y alinear el número citado en los docs antes de cerrar F8.
4. **`ANTHROPIC_MODEL` por defecto = `claude-sonnet-4-6`.** Observación de alineación con el stack,
   no de proceso: conviene verificar que ese identificador de modelo sea el vigente del catálogo
   Anthropic antes de producción (la verificación técnica corresponde a `code-architect`/
   `integrations-expert`, no a esta auditoría). El default es configurable vía entorno, así que el
   riesgo de proceso es bajo.

---

## Recomendaciones (corrección de raíz, no parches)

1. **Antes de F8 (despliegue):** correr el code-review de seguridad por subagente que el propio
   `progress.md` ya planificó, y dejar su veredicto en `docs/revisiones/`. Es el momento correcto
   (paso a producción) según `objectives.md` ("la seguridad no se negocia").
2. **Cerrar las dos derivas menores antes de marcar F8:** fijar la versión de Python en config de
   despliegue y validar el ID del modelo Anthropic. Ambas son baratas y evitan sorpresas en prod.
3. **Patrón a institucionalizar:** este proyecto es un buen ejemplo de PRD con registro de cambios y
   delegación con verificación del Head. Vale como referencia para otros proyectos del estudio.
4. **Recordatorio §9 del estudio:** al entrar AskDB a producción (F8), activar la guardia de
   producción y el pulso de analítica listados en `Automatizaciones.md` (es el primer proyecto en
   prod).

---

*Auditoría de proceso. No modifica código ni archivos del proyecto, no hace commit.*
