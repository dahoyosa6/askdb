"""Entrada por línea de comandos de AskDB.

Recibe una pregunta en lenguaje natural como argumento y delega TODO el pipeline
(generar SQL -> validar -> ejecutar, con auto-corrección) a
`answer_question`. Imprime el SQL ejecutado y la tabla de resultados si todo
salió bien, o un mensaje de error saneado si no.

Uso:
    python -m app.cli "¿cuántos pedidos hay?"

La impresión tabular usa solo la librería estándar (no añadimos dependencias).
"""

from __future__ import annotations

import logging
import sys

from config import settings

from app.agent.execute import answer_question


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

    # Todo el pipeline (generar -> validar -> ejecutar, con auto-corrección)
    # vive en answer_question. La CLI solo presenta el resultado.
    result = answer_question(question)

    if not result.ok:
        # Mensaje saneado para el usuario (nunca SQL crudo ni error interno).
        print(f"\n{result.error_message}")
        return 1

    print("\n--- SQL ejecutado ---")
    print(result.sql)

    print("\n--- Resultados ---")
    print(_render_table(result.columns, result.rows))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
