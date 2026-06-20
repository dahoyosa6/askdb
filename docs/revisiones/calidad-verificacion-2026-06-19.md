# Revisión de calidad (no-código) — AskDB · SEGUNDA VUELTA (verificación)

- **Fecha:** 2026-06-19
- **Revisor:** Quality Reviewer (De cero a uno)
- **Alcance:** verificar que los hallazgos del informe `calidad-2026-06-19.md` (B1, I1–I4,
  M1–M7) quedaron bien resueltos tras el commit `5bc8f05`, y buscar con ojo fresco nuevas
  inconsistencias o copy que chirríe.
- **NO incluye:** corrección/funcionalidad del código (corresponde a code-architect/tester).
- **Veredicto:** **Aprobado sin reservas** (para el copy y la coherencia de docs). Todos los
  hallazgos previos quedan RESUELTOS. Lo único que falta para la insignia de portafolio son las
  capturas/GIF reales del bot, que dependen de F8 (no es un defecto de calidad pendiente).

---

## Estado hallazgo por hallazgo

### B1 — RESUELTO
`router.py:118-123`. La rama 1 fila × 1 columna ahora devuelve `f"{_valor_legible(fila[0])}."`
con comentario explicando que es el caso más común y que ya NO se expone el nombre técnico.
Marta ya no verá "El count es 830." sino **"830."**.

> **Opinión de producto (lo que pediste).** "830." a secas es CORRECTO y muy superior a la frase
> rota anterior: sin jerga, sin filtración de DB. ¿Es demasiado seco? En contexto NO: la persona
> acaba de preguntar "¿cuántos pedidos hay?" y recibe "830." justo debajo de su propia pregunta —
> el par pregunta/respuesta da el contexto, igual que un asistente que contesta "830" en un chat.
> El punto final lo hace verse como respuesta, no como dato suelto. Aprobado tal cual. La única
> mejora futura (NO bloqueante, para v2) sería que Claude redacte la frase completa ("Tienes 830
> pedidos en total."); pero eso es alcance nuevo y la solución actual cumple el objetivo de no
> sonar a base de datos. Bien resuelto.

### I1 — RESUELTO
Captions ahora humanos, sin nombres de columna en inglés.
- Gráfica (`router.py:244`): `caption="Aquí tienes la gráfica de tu consulta."`
- Excel (`router.py:258`): `caption=f"Te adjunto el detalle completo ({len(rows)} resultados) en Excel."`
Ambos en español, cálidos y sin exponer nombres crudos de Northwind. El de Excel además dice
cuántos resultados trae, que era justo lo que faltaba. Resuelto.

### I2 — RESUELTO
`router.py:127-140`. La tabla multi-fila ya no usa `col | col | col`. Ahora:
- varias filas × 1 col → lista con guiones (`- valor`).
- varias filas × N cols → un bloque por registro (`col: val · col: val`) separados por línea en
  blanco. Legible en Telegram (fuente proporcional) y en CLI, sin depender de `parse_mode`. Resuelto.

### I3 — RESUELTO
`CLAUDE.md:44-48` ahora dice "F0 Setup ✅ … F7 Voz ✅ (128 tests)" y "F8 Railway → siguiente".
Ya no aparece "F2 ✅ · F3 siguiente". Coincide con `progress.md` (F7 completa, F8 siguiente).
La contradicción que detecté quedó cerrada.

### I4 — RESUELTO (lo cierra I3)
El trío PRD / progress / CLAUDE.md cuenta la misma historia: F0–F7 completas, F8 pendiente,
mismo nombre de proyecto, mismo id de modelo (`claude-sonnet-4-6`) en los 4 docs. README "Estado"
ahora es concreto ("MVP funcional completo… Pendiente: despliegue en Railway (Fase 8)"). Coherente.

### M1 — RESUELTO
`telegram_bot.py:58-61`. `_MENSAJE_GENERICO` ahora: "Uy, no pude resolver esa pregunta. Intenta
decirla de otra forma, más concreta (por ejemplo, nombrando el dato o el periodo)." Más cálido y
accionable, exactamente la mejora sugerida. Resuelto.

### M3 — RESUELTO
`router.py:116`. Mensaje sin resultados ahora "No encontré datos para esa pregunta." (primera
persona, cercano), en lugar de "No se encontraron resultados." Resuelto.

### Nota de origen del PRD — PRESENTE
`prd.md:8` ("Aprobado (spec madre)") y `prd.md:10-14` explican que el PRD se derivó de un
spec/contrato ya escrito por David y por eso no hubo entrevista por rondas. Cierra la duda de
proceso que un auditor/reclutador podría tener. Bien.

### Menores ya OK de antes (sin cambios necesarios)
- **M4** (`/help`): sigue usando "ventas por mes de 1997" (válido: Northwind tiene 1996–1998) y
  ejemplos genéricos que funcionan. OK.
- **M2, M5, M6, M7**: sin regresiones; el id de modelo y el nombre del proyecto siguen escritos
  igual en todos los docs.

---

## Ojo fresco: nuevas inconsistencias o copy que chirríe

1. **`README.md:53` vs `CLAUDE.md:53` — comando de carga divergente (MENOR, ya señalado como
   matiz en I/M anterior, sigue vivo).** El README dice `python scripts/setup_db.py` y el CLAUDE.md
   "Cómo correrlo" dice `python scripts/check_conn.py`. Verifiqué: **ambos scripts existen**
   (`scripts/setup_db.py` y `scripts/check_conn.py`), así que ninguno está roto. La diferencia es
   intencional/correcta (setup carga datos una vez; check_conn verifica), pero al lector le conviene
   que el README aclare que `check_conn.py` es el paso siguiente de verificación. No es bloqueante
   ni una contradicción real; es una mejora menor de claridad. No estaba mal resuelto: simplemente
   no era foco de esta vuelta.

2. **Conteo de tests inconsistente entre docs (MENOR, cosmético).** `progress.md` (la fuente de
   estado) dice **162/162** tras el endurecimiento; pero `CLAUDE.md:46` dice "128 tests", el
   README "128+ pruebas" y `progress.md:70` aún pide "pytest debe dar 128/128 antes de tocar nada".
   No es falso (128 fue el total al cerrar F7; 162 es tras la review), pero un lector ve dos cifras.
   Sugerencia (no bloqueante): alinear CLAUDE.md y README a "162 pruebas" ya que es el estado actual,
   o escribir "160+ pruebas". Es el único número que no quedó sincronizado tras los arreglos.

3. **Copy del usuario: sin fugas técnicas.** Repasé TODAS las constantes de texto de
   `telegram_bot.py` (_TEXTO_START, _TEXTO_HELP, _TEXTO_NO_AUTORIZADO, _TEXTO_RATE_LIMIT,
   _TEXTO_RESET, _TEXTO_VOZ_*, texto_eco) y los textos del router. **Ningún texto técnico se cuela
   al usuario**: no hay SQL, ni nombres de columna en inglés, ni stacktrace, ni jerga. Tono "tú",
   cálido y consistente. El eco de voz `🎤 Entendí: "..."` sigue siendo un acierto de UX.

Ningún cambio del commit introdujo copy que chirríe ni una nueva contradicción de fondo. Los dos
puntos de arriba son cosméticos de docs (números/comando), no afectan lo que ve Marta.

---

## ¿Listo como pieza de portafolio?

Sí, salvo lo visual que ya estaba previsto. La narrativa (cerebro desacoplado + seguridad en 3
capas + read-only por diseño), el README, el `.env.example` (sigue excelente) y la coherencia del
trío de docs están a la altura. Lo único que eleva de "muy bueno" a "destaca" son **2–3 capturas o
un GIF del bot respondiendo** (texto / gráfica / Excel), que se harán tras F8 (despliegue) o con un
túnel local. Eso NO es un hallazgo de calidad pendiente: es contenido que aún no se puede generar.

---

## Resumen de severidades (segunda vuelta)

| ID previo | Estado ahora |
|-----------|--------------|
| B1 (bloqueante) | RESUELTO |
| I1 | RESUELTO |
| I2 | RESUELTO |
| I3 | RESUELTO |
| I4 | RESUELTO (lo cierra I3) |
| M1, M3 | RESUELTOS |
| Nota origen PRD | PRESENTE |
| **Nuevo (menor, cosmético)** | Conteo de tests 128 vs 162 sin sincronizar en CLAUDE.md/README |
| **Nuevo (menor, cosmético)** | README usa `setup_db.py` y CLAUDE.md `check_conn.py` (ambos existen, no roto) |

**Veredicto final: Aprobado sin reservas** en lo que me corresponde (copy del usuario + coherencia
de entregables). Los dos menores nuevos son cosméticos de documentación y NO bloquean ni la demo ni
el portafolio. Recomendación opcional al cerrar: alinear el conteo de tests a 162 en CLAUDE.md y
README para que el número sea uno solo en todo el repo.
