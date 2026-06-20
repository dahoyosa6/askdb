# AskDB — "Habla con tus Datos" 🗣️📊

Agente conversacional **text-to-SQL**: pregunta en lenguaje natural (texto o voz) por
**Telegram**, obtén la respuesta en **texto, gráfica o Excel**. Sin saber SQL.

> Pensado para PYMES: la dueña de una ferretería pregunta *"¿qué productos no he vendido
> en 2 meses?"* y recibe la respuesta al instante, sin tocar una hoja de cálculo.

La v1 corre sobre la base **Northwind** (un estándar de comercio: productos, clientes,
órdenes, empleados) como sustituto de un POS real.

## Por qué es interesante (decisiones de arquitectura)

- **El cerebro está desacoplado de la interfaz.** El núcleo es una API; Telegram es solo
  un cliente. Mañana se enchufa WhatsApp o una web sin reescribir el cerebro.
- **Seguridad en 3 capas (read-only por diseño).** Aunque el modelo generara un `DELETE`,
  rebota tres veces:
  1. **Validación de la app** (`sqlparse`): solo `SELECT`/`WITH`, una sola sentencia, sin DDL/DML.
  2. **LIMIT forzado** para no devolver millones de filas.
  3. **Rol de base de datos de solo lectura**: la barrera no-evitable. La app jamás se conecta
     con un rol que pueda escribir.
- **SQL estructurado, no parseo frágil.** Claude devuelve el SQL vía *tool use* forzado, no
  como texto suelto: sin markdown, sin preámbulos, sin sorpresas.
- **Auto-corrección.** Si la consulta falla, el agente lee el error de Postgres y reintenta
  (≤3) antes de rendirse con un mensaje claro — nunca un stacktrace al usuario.
- **Barato de operar.** Northwind en **Neon** (Postgres gratis), hosting en Railway (~5 USD/mes),
  IA con `claude-sonnet-4-6`. Costo operativo de demo ≈ 5 USD/mes.

## Arquitectura

```
[Telegram] ──► [API FastAPI: el "cerebro"] ──► [Claude] (genera SQL + redacta respuesta)
 (texto/voz)        │
                    ├─► [Transcripción]  (Groq Whisper, solo si llega voz; intercambiable)
                    ├─► [Validador SQL]  (guardrails)
                    ├─► [Neon Postgres / Northwind]  (rol read-only)
                    └─► [Formateador]    (matplotlib PNG / pandas Excel)
```

## Stack

Python 3.11+ · FastAPI · Anthropic SDK (`claude-sonnet-4-6`) · python-telegram-bot ·
psycopg3 · sqlparse · matplotlib · pandas + openpyxl · Groq (voz) · Neon (DB) · Railway (deploy).

## Cómo correrlo (local)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # y completa tus claves
python scripts/setup_db.py      # carga Northwind + crea el rol read-only (una vez)
python scripts/check_conn.py    # verifica conexión read-only + datos
pytest                          # pruebas
```

## Estado

**MVP funcional completo:** texto y voz por Telegram, seguro (validación + LIMIT + rol
read-only, con allowlist y rate limit), con memoria conversacional y formato automático
(texto / gráfica / Excel). Suite de 128+ pruebas en verde. **Pendiente:** el despliegue en
Railway (Fase 8). Ver `progress.md` para el detalle por fase.

---

Proyecto de portafolio de **David Hoyos** · Estudio *De cero a uno*.
