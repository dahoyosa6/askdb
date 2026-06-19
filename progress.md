# Progress — AskDB · "Habla con tus Datos"

> Diario de a bordo. Primer archivo que se lee al abrir sesión, último que se escribe al cerrar.

## Estado general
- **Fase actual:** Fase 0 (Setup) — en curso.
- **% MVP:** ~5%.
- **Próximo paso:** que David cree el proyecto Neon y pegue `NEON_ADMIN_URL` en `.env`;
  luego cargar Northwind, crear rol read-only y verificar conexión (`scripts/check_conn.py`).

## Funcionalidades (estado)
| # | Funcionalidad | Estado | Pruebas |
|---|---|---|---|
| F0 | Setup (repo, entorno, DB, rol read-only) | En curso | — |
| F1 | Core CLI (NL→SQL→ejecutar→tabla) | Pendiente | — |
| F2 | Guardrails de seguridad | Pendiente | — |
| F3 | Auto-corrección | Pendiente | — |
| F4 | Router de formato (texto/gráfica/Excel) | Pendiente | — |
| F5 | Memoria conversacional | Pendiente | — |
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

## Pendientes para David
- [ ] Crear proyecto Neon `askdb` y pegar `NEON_ADMIN_URL` en `.env` (instrucciones dadas).
- [ ] Rotar la API key de Anthropic y pegar la nueva en `.env` (`ANTHROPIC_API_KEY`).

## Accesos y enlaces
- Repo local: `/Users/davidhoyos/Clientes/AskDB`
- GitHub: (pendiente crear, público)
- Neon: (pendiente)
- Railway: (pendiente, Fase 8)
