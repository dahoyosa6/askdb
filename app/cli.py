"""Entrada por línea de comandos de AskDB (Fase 1, punta a punta).

Recibe una pregunta en lenguaje natural como argumento, genera el SQL con
Claude, lo ejecuta en modo solo lectura, e imprime el SQL generado más la tabla
de resultados.

Uso:
    python -m app.cli "¿cuántos pedidos hay?"

Sin guardrails, sin auto-corrección, sin router de formato: eso es Fase 2-4.
Esto es el cableado punta a punta, aunque sea feo. La impresión tabular usa solo
la librería estándar (no añadimos dependencias).
"""

from __future__ import annotations

import logging
import sys

from config import settings

from app.agent.execute import run_query
from app.agent.generate_sql import generate_sql, get_client
from app.agent.glossary import get_glossary
from app.agent.schema import get_schema
from app.agent.validate_sql import SQLValidationError, validate_and_secure


def _setup_logging() -> None:
    """Configura logging básico según LOG_LEVEL del config."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _render_table(columns: list[str], rows: list[tuple]) -> str:
    """Renderiza una tabla ASCII simple a partir de columnas y filas.

    Solo librería estándar. Calcula el ancho de cada columna en función del
    contenido y arma una tabla legible para la terminal.
    """
    if not columns:
        return "(sin columnas)"

    # Convertimos todas las celdas a string para medir y alinear.
    str_rows = [[_cell(v) for v in row] for row in rows]

    widths = [len(c) for c in columns]
    for row in str_rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))

    def fmt_row(cells: list[str]) -> str:
        return " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    separator = "-+-".join("-" * w for w in widths)
    lines = [fmt_row(columns), separator]
    lines.extend(fmt_row(row) for row in str_rows)

    if not rows:
        lines.append("(0 filas)")
    else:
        lines.append(f"({len(rows)} fila{'s' if len(rows) != 1 else ''})")

    return "\n".join(lines)


def _cell(value: object) -> str:
    """Convierte una celda a string para la tabla (None -> 'NULL')."""
    if value is None:
        return "NULL"
    return str(value)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la CLI. Devuelve el código de salida del proceso."""
    _setup_logging()
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        print('Uso: python -m app.cli "tu pregunta en lenguaje natural"')
        return 2

    question = " ".join(args).strip()
    if not question:
        print("La pregunta está vacía.")
        return 2

    # 1. Esquema + glosario (esquema cacheado; introspecciona si hace falta).
    #    get_schema() sin conn usa la cache de disco/memoria; si no existe,
    #    necesitará una conexión, pero en uso normal la cache ya está poblada.
    schema = get_schema()
    glossary = get_glossary()

    # 2. Generar SQL con Claude (tool_use forzado).
    client = get_client()
    sql = generate_sql(client, question, schema, glossary)

    print("\n--- SQL generado ---")
    print(sql)

    # 3. Guardrails: validar y asegurar (solo SELECT, una sentencia, LIMIT).
    try:
        safe_sql = validate_and_secure(sql)
    except SQLValidationError as exc:
        logging.warning("SQL rechazado por los guardrails: %s", exc)
        print(f"\n⚠️  La consulta no pasó los guardrails de seguridad: {exc}")
        return 1

    if safe_sql != sql:
        print("\n--- SQL asegurado (con LIMIT) ---")
        print(safe_sql)

    # 4. Ejecutar en modo solo lectura.
    columns, rows = run_query(safe_sql)

    print("\n--- Resultados ---")
    print(_render_table(columns, rows))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
