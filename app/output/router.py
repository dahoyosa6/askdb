"""Router de formato de salida (Fase 4).

Decide automáticamente CÓMO presentar el resultado de una consulta según su
forma (número de filas y columnas y los tipos de dato), y arma el artefacto
correspondiente:

- TEXTO: un dato, una ficha de un registro, o una tabla corta. No toca disco.
- GRÁFICA (PNG): un ranking o una serie temporal (2 columnas: eje + valor).
- EXCEL (.xlsx): detalle largo o tabla ancha.

Principio rector (regla dura del proyecto): NUNCA se le expone un error interno
al usuario. Si generar la gráfica o el Excel falla por cualquier motivo, se
captura, se loguea del lado servidor y se cae a TEXTO. El usuario siempre recibe
una respuesta útil, nunca un stacktrace.

La heurística es DETERMINISTA (sin IA): mismas dimensiones -> misma decisión.
Eso la hace barata, predecible y fácil de probar.

Función pública: `enrutar_salida(result, *, generar_artefacto=True) -> OutputResult`.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from decimal import Decimal

from config import settings

# Se importan los módulos (no las funciones) a nivel de módulo a propósito: así
# los tests pueden monkeypatchear `app.output.router.chart.generar_grafica` y
# `app.output.router.spreadsheet.generar_excel` sin tocar disco.
from app.output import chart, spreadsheet

# AnswerResult solo se usa para anotación de tipo; se importa con cuidado de no
# crear un ciclo (execute no importa este módulo).
from app.agent.execute import AnswerResult

logger = logging.getLogger(__name__)


@dataclass
class OutputResult:
    """Qué entregar al usuario y por qué canal.

    Atributos:
        kind: "text" | "chart" | "excel".
        text: el texto a mostrar (siempre presente en kind="text"; opcional como
            pie/respaldo en los demás).
        file_path: ruta del artefacto generado (PNG o XLSX); None en texto o si
            no se generó artefacto.
        caption: leyenda corta para acompañar un archivo (p. ej. en Telegram).
    """

    kind: str
    text: str | None = None
    file_path: str | None = None
    caption: str | None = None


def _clasificar_columna(celdas: list) -> str:
    """Clasifica una columna por el tipo de sus celdas no-None.

    Devuelve uno de: "numerica", "temporal", "texto", "indeterminada".

    Reglas:
    - numerica: todas las no-None son int/float/Decimal. OJO: `bool` es subclase
      de `int` en Python, pero NO cuenta como numérica (un sí/no no se grafica
      como cantidad).
    - temporal: todas las no-None son date/datetime.
    - texto: cualquier otra mezcla (incluye str, bool, o tipos mezclados).
    - indeterminada: no hay celdas no-None (columna toda vacía o sin filas).
    """
    valores = [c for c in celdas if c is not None]
    if not valores:
        return "indeterminada"

    if all(isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) for v in valores):
        return "numerica"

    if all(isinstance(v, (datetime.date, datetime.datetime)) for v in valores):
        return "temporal"

    return "texto"


def _tipo_de_grafica(tipo_col_eje: str) -> str:
    """Tipo de gráfica según el tipo de la columna del eje X.

    - "linea" si el eje es temporal (una serie en el tiempo).
    - "barras" en cualquier otro caso (un ranking por categoría).
    """
    return "linea" if tipo_col_eje == "temporal" else "barras"


def _valor_legible(valor: object) -> str:
    """Formatea un valor de celda para texto (None -> 'sin dato')."""
    if valor is None:
        return "sin dato"
    return str(valor)


def _formatear_texto(columns: list[str], rows: list[tuple]) -> str:
    """Arma la representación en TEXTO de un resultado.

    Cubre los casos que la heurística manda a texto:
    - 0 filas -> mensaje de vacío.
    - 1 fila x 1 col -> SOLO el valor (sin reconstruir "El <columna> es ...", que
      filtraba nombres técnicos de columna en inglés al usuario; B1).
    - 1 fila x N cols -> ficha "col: valor · col: valor".
    - varias filas -> una entrada por registro, legible en texto plano (sin tabla
      con '|', que se desalinea en la fuente proporcional de Telegram; I2).
    """
    if len(rows) == 0:
        return "No encontré datos para esa pregunta."

    if len(rows) == 1:
        fila = rows[0]
        if len(columns) == 1:
            # B1: el caso más común ("¿cuántos pedidos hay?"). Devolvemos solo el
            # valor formateado; no exponemos el nombre técnico de la columna.
            return f"{_valor_legible(fila[0])}."
        partes = [f"{col}: {_valor_legible(val)}" for col, val in zip(columns, fila)]
        return " · ".join(partes)

    # Varias filas, 1 columna: lista simple.
    if len(columns) == 1:
        lineas = [f"- {_valor_legible(fila[0])}" for fila in rows]
        return "\n".join(lineas)

    # I2: varias filas y columnas. En vez de una tabla con '|' (que se desalinea en
    # Telegram), una entrada por registro: cada fila como "col: val · col: val",
    # separadas por una línea en blanco. Se ve bien en CLI y en Telegram sin
    # depender de parse_mode.
    bloques = []
    for fila in rows:
        partes = [f"{col}: {_valor_legible(val)}" for col, val in zip(columns, fila)]
        bloques.append(" · ".join(partes))
    return "\n\n".join(bloques)


def elegir_formato(columns: list[str], rows: list[tuple]) -> str:
    """Heurística determinista: decide el formato según la forma del resultado.

    Reglas evaluadas EN ORDEN (cortocircuito):
    1. 0 filas -> "text".
    2. 1 fila -> "text" (decisión de producto: un registro único siempre es texto).
    3. más de `chart_max_rows` filas -> "excel" (detalle largo).
    4. más de 2 columnas (con 2..chart_max_rows filas) -> "excel" (tabla ancha).
    5. 1 columna con varias filas -> "text" si caben (<= table_max_rows_text),
       si no "excel".
    6. 2 columnas con 2..chart_max_rows filas -> "chart" si hay exactamente 1
       columna numérica + 1 columna de eje (texto o temporal); si no, "text"
       (si caben) o "excel".

    Returns:
        "text" | "chart" | "excel".
    """
    n_filas = len(rows)
    n_cols = len(columns)

    # 1. Sin resultados.
    if n_filas == 0:
        return "text"

    # 2. Un solo registro: siempre texto (decisión de producto de David).
    if n_filas == 1:
        return "text"

    # 3. Detalle largo: demasiadas filas para chat o gráfica legible.
    if n_filas > settings.chart_max_rows:
        return "excel"

    # 4. Tabla ancha: más de 2 columnas no se grafica; va a Excel.
    if n_cols > 2:
        return "excel"

    # 5. Una sola columna con varias filas: texto si es corta, si no Excel.
    if n_cols == 1:
        return "text" if n_filas <= settings.table_max_rows_text else "excel"

    # 6. Exactamente 2 columnas: candidata a gráfica si una es numérica (valor)
    #    y la otra es eje (texto/categórica o temporal).
    tipos = [_clasificar_columna([row[i] for row in rows]) for i in range(n_cols)]
    numericas = [t for t in tipos if t == "numerica"]
    ejes = [t for t in tipos if t in ("texto", "temporal")]

    if len(numericas) == 1 and len(ejes) == 1:
        return "chart"

    # Dos columnas no graficables (p. ej. dos textos): texto si cabe, si no Excel.
    return "text" if n_filas <= settings.table_max_rows_text else "excel"


def enrutar_salida(
    result: AnswerResult,
    *,
    generar_artefacto: bool = True,
) -> OutputResult:
    """Decide el formato de salida y arma el `OutputResult`.

    Si `result.ok` es False, devuelve directamente el `error_message` saneado
    como texto (nunca se intenta graficar un fallo).

    Args:
        result: salida del pipeline (`answer_question`).
        generar_artefacto: si es False, decide el `kind` pero NO crea archivos.
            Útil en tests para verificar solo la decisión.

    Returns:
        OutputResult con el formato elegido y, si aplica, la ruta del artefacto.
    """
    # Caso de fallo: mostrar el mensaje saneado, sin tocar disco.
    if result.ok is False:
        return OutputResult(kind="text", text=result.error_message)

    columns = result.columns
    rows = result.rows

    kind = elegir_formato(columns, rows)

    # La rama TEXTO es PURA: no importa matplotlib, no toca disco.
    if kind == "text":
        return OutputResult(kind="text", text=_formatear_texto(columns, rows))

    # Si solo se pide la decisión (tests), no generamos archivos.
    if not generar_artefacto:
        return OutputResult(kind=kind)

    # Ramas con artefacto: gráfica o Excel. Cualquier fallo cae a TEXTO.
    if kind == "chart":
        try:
            tipos = [_clasificar_columna([row[i] for row in rows]) for i in range(len(columns))]
            # El eje es la columna no numérica (texto o temporal).
            idx_eje = next(i for i, t in enumerate(tipos) if t in ("texto", "temporal"))
            tipo = _tipo_de_grafica(tipos[idx_eje])
            ruta = chart.generar_grafica(columns, rows, tipo=tipo)
            return OutputResult(
                kind="chart",
                # I1: caption humano. No exponemos los nombres crudos de columna
                # (en inglés, técnicos) al usuario.
                file_path=ruta,
                caption="Aquí tienes la gráfica de tu consulta.",
            )
        except Exception as exc:  # noqa: BLE001 - fallback de seguridad a propósito
            # Regla dura: nunca propagar el error al usuario. Log servidor + texto.
            logger.error("enrutar_salida: falló la generación de gráfica, caigo a texto: %s", exc)
            return OutputResult(kind="text", text=_formatear_texto(columns, rows))

    # kind == "excel"
    try:
        ruta = spreadsheet.generar_excel(columns, rows)
        return OutputResult(
            kind="excel",
            # I1: caption humano que dice QUÉ contiene el archivo, sin jerga de DB.
            file_path=ruta,
            caption=f"Te adjunto el detalle completo ({len(rows)} resultados) en Excel.",
        )
    except Exception as exc:  # noqa: BLE001 - fallback de seguridad a propósito
        logger.error("enrutar_salida: falló la generación de Excel, caigo a texto: %s", exc)
        return OutputResult(kind="text", text=_formatear_texto(columns, rows))
