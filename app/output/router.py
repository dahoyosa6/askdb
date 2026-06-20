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


def _plan_grafica(columns: list[str], rows: list[tuple]) -> tuple[int, int] | None:
    """Decide si un resultado es graficable y con qué par de columnas.

    Regla de gráfica (router inteligente): se grafica cuando hay EXACTAMENTE UNA
    columna numérica y AL MENOS UNA columna de eje (temporal o texto), aunque
    existan columnas descriptivas extra (p. ej. `mes` + `nombre_mes` + `facturacion`).

    Se elige UN solo eje: se PREFIERE el temporal; si no hay temporal, el primer
    eje de texto. La gráfica usa solo ese par [eje, numérica]; las columnas extra
    se ignoran al dibujar.

    Casos que NO se grafican (devuelve None):
    - 2 o más columnas numéricas -> no se puede elegir una sola serie.
    - ninguna columna numérica.
    - ninguna columna de eje usable (temporal o texto).

    Returns:
        (idx_eje, idx_numerica) si es graficable; None si no.
    """
    tipos = [_clasificar_columna([row[i] for row in rows]) for i in range(len(columns))]

    idx_numericas = [i for i, t in enumerate(tipos) if t == "numerica"]
    if len(idx_numericas) != 1:
        return None  # ninguna o varias numéricas: no hay una sola serie clara.

    idx_temporales = [i for i, t in enumerate(tipos) if t == "temporal"]
    idx_textos = [i for i, t in enumerate(tipos) if t == "texto"]

    if idx_temporales:
        idx_eje = idx_temporales[0]  # se prefiere el eje temporal.
    elif idx_textos:
        idx_eje = idx_textos[0]  # si no hay temporal, el primer texto.
    else:
        return None  # numérica sin eje usable: no graficable.

    return idx_eje, idx_numericas[0]


def _tipo_de_grafica(tipo_col_eje: str) -> str:
    """Tipo de gráfica según el tipo de la columna del eje X.

    - "linea" si el eje es temporal (una serie en el tiempo).
    - "barras" en cualquier otro caso (un ranking por categoría).
    """
    return "linea" if tipo_col_eje == "temporal" else "barras"


def _formatear_numero_esco(valor: float | Decimal) -> str:
    """Formatea un monto (float/Decimal) al estilo es-CO para una PYME.

    Redondea a `settings.text_decimals` (=2) decimales y usa separador de miles
    con PUNTO y decimales con COMA. Ej: 617085.1999999998 -> "617.085,20".

    Por qué NO se antepone "$": el agente responde sobre datos arbitrarios y no
    sabe si el número es dinero, un conteo o un ratio; anteponer moneda sería
    adivinar. Solo se da cantidad + separadores.

    Implementación: se formatea primero al estilo "en-US" (coma=miles, punto=
    decimales) con `format(..., ",.2f")` y luego se intercambian los separadores
    a es-CO mediante un marcador temporal (evita pisar el punto recién puesto).
    """
    en_us = format(valor, f",.{settings.text_decimals}f")  # p. ej. "617,085.20"
    return en_us.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _valor_legible(valor: object) -> str:
    """Formatea un valor de celda para la salida en TEXTO.

    Reglas de presentación (es-CO, PYME de habla hispana):
    - None -> "sin dato".
    - float / Decimal -> redondeo a 2 decimales + separadores es-CO (ver
      `_formatear_numero_esco`). Resuelve el bug de decimales "infinitos".
    - int -> SIN separador de miles. Un int es ambiguo entre cantidad, AÑO
      (1997, no "1.997") e IDENTIFICADOR (pedido 10248, no "10.248"); como no se
      puede distinguir por el valor, lo seguro es no aplicarle separador y así
      NUNCA romper un año o un ID. (Un conteo grande se ve sin punto; es el
      precio aceptable de no estropear años/IDs.)
    - bool -> NO es cantidad (sí/no); aunque en Python es subclase de int, se
      muestra tal cual y no se formatea como número.
    - date/datetime/str y cualquier otro tipo -> sin cambios (str(valor)).
    """
    if valor is None:
        return "sin dato"
    # bool antes que int: bool es subclase de int y NO debe formatearse.
    if isinstance(valor, bool):
        return str(valor)
    if isinstance(valor, (float, Decimal)):
        return _formatear_numero_esco(valor)
    # int (no bool): se deja entero, sin separador, para no romper años ni IDs.
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
    4. GRÁFICA si hay EXACTAMENTE 1 columna numérica + AL MENOS 1 eje (temporal o
       texto), AUNQUE existan columnas descriptivas extra. Se grafica solo el par
       [eje elegido, numérica] (eje preferido: temporal; si no, primer texto).
       Ver `_plan_grafica`. (Router inteligente: antes una columna descriptiva de
       más tiraba todo a Excel y la gráfica casi nunca salía.)
    5. tabla ancha NO graficable (> 2 columnas) -> "excel" (no se grafica y no
       cabe legible en chat; p. ej. varias numéricas, o id+texto+varias numéricas).
    6. 1 columna con varias filas -> "text" si caben (<= table_max_rows_text),
       si no "excel".
    7. Resto (2 columnas no graficables, p. ej. dos textos): "text" si cabe
       (<= table_max_rows_text), si no "excel".

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

    # 4. ¿Graficable? 1 numérica + >=1 eje (aunque haya columnas extra).
    if _plan_grafica(columns, rows) is not None:
        return "chart"

    # 5. Tabla ancha NO graficable (> 2 columnas): Excel. Llega aquí cuando hay
    #    varias numéricas o ningún eje usable; no se puede elegir una sola serie y
    #    no cabe legible en el chat, así que se entrega el detalle en Excel.
    if n_cols > 2:
        return "excel"

    # 6. Una sola columna con varias filas: texto si es corta, si no Excel.
    if n_cols == 1:
        return "text" if n_filas <= settings.table_max_rows_text else "excel"

    # 7. Dos columnas no graficables (p. ej. dos textos): texto si cabe, si no Excel.
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
            plan = _plan_grafica(columns, rows)
            # `elegir_formato` ya garantizó que es graficable; este guard es defensa.
            if plan is None:
                raise ValueError("resultado no graficable")
            idx_eje, idx_num = plan
            # PROYECCIÓN a 2 columnas: la gráfica recibe SOLO el par
            # [eje elegido, numérica], ignorando columnas descriptivas extra
            # (p. ej. `nombre_mes`). Antes se le pasaban todas las columnas.
            cols_grafica = [columns[idx_eje], columns[idx_num]]
            filas_grafica = [(fila[idx_eje], fila[idx_num]) for fila in rows]
            tipo_eje = _clasificar_columna([fila[idx_eje] for fila in rows])
            tipo = _tipo_de_grafica(tipo_eje)
            ruta = chart.generar_grafica(cols_grafica, filas_grafica, tipo=tipo)
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
