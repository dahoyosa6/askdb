"""Pruebas del router de formato de salida (Fase 4).

Mayormente PURAS: prueban la DECISIÓN del router sin tocar disco. Para verificar
qué formato elige se usa `generar_artefacto=False`, o se monkeypatchea a nivel de
módulo `app.output.router.chart` / `.spreadsheet` con espías que capturan la
llamada (y nunca crean archivos reales).

Convención del proyecto: monkeypatch a nivel de módulo, sin red ni DB, código y
docstrings en español.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import app.output.router as router
from app.agent.execute import AnswerResult
from app.output.router import enrutar_salida
from config import settings


class _SpyChart:
    """Espía de app.output.chart: registra la llamada y devuelve una ruta falsa."""

    def __init__(self) -> None:
        self.llamado = False
        self.tipo = None

    def generar_grafica(self, columns, rows, *, tipo, output_dir=None, nombre_base=None):
        self.llamado = True
        self.tipo = tipo
        return "/tmp/falsa_grafica.png"


class _SpySpreadsheet:
    """Espía de app.output.spreadsheet: registra la llamada y devuelve ruta falsa."""

    def __init__(self) -> None:
        self.llamado = False

    def generar_excel(self, columns, rows, *, output_dir=None, nombre_base=None):
        self.llamado = True
        return "/tmp/falsa_tabla.xlsx"


def _ok(columns, rows):
    """Atajo: un AnswerResult exitoso con esas columnas y filas."""
    return AnswerResult(ok=True, columns=columns, rows=rows, sql="SELECT ...", attempts=1)


# ---------------------------------------------------------------------------
# Casos de TEXTO (puros)
# ---------------------------------------------------------------------------

def test_un_dato_1x1_es_texto_puro(monkeypatch):
    """Un dato (1 fila x 1 col) -> texto con el valor; no se toca chart/spreadsheet."""
    spy_chart = _SpyChart()
    spy_sheet = _SpySpreadsheet()
    monkeypatch.setattr(router, "chart", spy_chart)
    monkeypatch.setattr(router, "spreadsheet", spy_sheet)

    out = enrutar_salida(_ok(["total"], [(830,)]))

    assert out.kind == "text"
    # B1: solo el valor, SIN el nombre técnico de columna ("El total es ...").
    assert out.text == "830."
    assert "total" not in out.text
    assert out.file_path is None
    # Pureza: la rama texto no debe haber tocado los generadores de artefactos.
    assert spy_chart.llamado is False
    assert spy_sheet.llamado is False


def test_registro_unico_varias_columnas_es_ficha_texto():
    """1 fila x N cols -> ficha de texto (col: valor · col: valor), sin archivo."""
    out = enrutar_salida(_ok(["cliente", "total"], [("QUICK-Stop", 110277)]))
    assert out.kind == "text"
    assert "cliente" in out.text
    assert "QUICK-Stop" in out.text
    assert "110277" in out.text
    assert out.file_path is None


def test_cero_filas_es_texto_vacio():
    """0 filas -> texto con mensaje de vacío."""
    out = enrutar_salida(_ok(["total"], []))
    assert out.kind == "text"
    assert "No encontré datos" in out.text
    assert out.file_path is None


def test_una_columna_muchas_filas_es_excel():
    """1 col con más de table_max_rows_text filas -> excel."""
    n = settings.table_max_rows_text + 5
    rows = [(f"producto_{i}",) for i in range(n)]
    out = enrutar_salida(_ok(["producto"], rows), generar_artefacto=False)
    assert out.kind == "excel"


def test_una_columna_pocas_filas_es_texto():
    """1 col con pocas filas (<= table_max_rows_text) -> texto."""
    rows = [(f"producto_{i}",) for i in range(3)]
    out = enrutar_salida(_ok(["producto"], rows))
    assert out.kind == "text"
    assert "producto_0" in out.text
    assert out.file_path is None


def test_dos_columnas_no_graficables_pocas_filas_es_texto():
    """2 columnas de texto (no graficable) y pocas filas -> texto."""
    rows = [("Bogotá", "QUICK-Stop"), ("Cali", "Save-a-lot")]
    out = enrutar_salida(_ok(["ciudad", "cliente"], rows))
    assert out.kind == "text"
    assert out.file_path is None


# ---------------------------------------------------------------------------
# Casos de GRÁFICA
# ---------------------------------------------------------------------------

def test_ranking_dos_columnas_es_grafica_barras(monkeypatch):
    """2 col (texto + numérico), <= chart_max_rows -> chart tipo 'barras'."""
    spy_chart = _SpyChart()
    monkeypatch.setattr(router, "chart", spy_chart)

    rows = [("QUICK-Stop", 110277), ("Save-a-lot", 104361), ("Ernst", 104874)]
    out = enrutar_salida(_ok(["cliente", "facturacion"], rows))

    assert out.kind == "chart"
    assert out.file_path == "/tmp/falsa_grafica.png"
    assert spy_chart.llamado is True
    assert spy_chart.tipo == "barras"


def test_serie_con_fechas_es_grafica_linea(monkeypatch):
    """2 col (date + numérico) -> chart tipo 'linea'."""
    spy_chart = _SpyChart()
    monkeypatch.setattr(router, "chart", spy_chart)

    rows = [
        (datetime.date(2026, 1, 1), 100),
        (datetime.date(2026, 2, 1), 150),
        (datetime.date(2026, 3, 1), 130),
    ]
    out = enrutar_salida(_ok(["mes", "ventas"], rows))

    assert out.kind == "chart"
    assert spy_chart.tipo == "linea"


def test_grafica_acepta_numerico_decimal(monkeypatch):
    """La columna numérica puede ser Decimal (típico de Postgres)."""
    spy_chart = _SpyChart()
    monkeypatch.setattr(router, "chart", spy_chart)

    rows = [("A", Decimal("10.5")), ("B", Decimal("20.0")), ("C", Decimal("5.0"))]
    out = enrutar_salida(_ok(["categoria", "monto"], rows))
    assert out.kind == "chart"
    assert spy_chart.tipo == "barras"


# ---------------------------------------------------------------------------
# Casos de EXCEL
# ---------------------------------------------------------------------------

def test_muchas_filas_es_excel(monkeypatch):
    """Más de chart_max_rows filas -> excel (detalle largo)."""
    spy_sheet = _SpySpreadsheet()
    monkeypatch.setattr(router, "spreadsheet", spy_sheet)

    n = settings.chart_max_rows + 1
    rows = [(f"cliente_{i}", i) for i in range(n)]
    out = enrutar_salida(_ok(["cliente", "total"], rows))

    assert out.kind == "excel"
    assert out.file_path == "/tmp/falsa_tabla.xlsx"
    assert spy_sheet.llamado is True


def test_mas_de_dos_columnas_pocas_filas_es_excel():
    """> 2 columnas (con pocas filas) -> excel (tabla ancha)."""
    rows = [("QUICK-Stop", "Bogotá", 110277), ("Save-a-lot", "Cali", 104361)]
    out = enrutar_salida(_ok(["cliente", "ciudad", "total"], rows), generar_artefacto=False)
    assert out.kind == "excel"


# ---------------------------------------------------------------------------
# Casos de FALLO y de SEGURIDAD
# ---------------------------------------------------------------------------

def test_result_no_ok_devuelve_texto_con_error_message():
    """result.ok=False -> texto con el error_message, sin tocar disco."""
    res = AnswerResult(ok=False, error_message="No pude responder esa pregunta.")
    out = enrutar_salida(res)
    assert out.kind == "text"
    assert out.text == "No pude responder esa pregunta."
    assert out.file_path is None


def test_fallback_a_texto_si_falla_generacion_de_grafica(monkeypatch):
    """Si chart.generar_grafica lanza, el router cae a texto (no propaga el error)."""

    class _ChartBomba:
        def generar_grafica(self, *args, **kwargs):
            raise RuntimeError("matplotlib explotó")

    monkeypatch.setattr(router, "chart", _ChartBomba())

    rows = [("QUICK-Stop", 110277), ("Save-a-lot", 104361), ("Ernst", 104874)]
    # No debe lanzar: el fallback captura la excepción y devuelve texto.
    out = enrutar_salida(_ok(["cliente", "facturacion"], rows))

    assert out.kind == "text"
    assert "QUICK-Stop" in out.text
    assert out.file_path is None


def test_fallback_a_texto_si_falla_generacion_de_excel(monkeypatch):
    """Si spreadsheet.generar_excel lanza, el router cae a texto."""

    class _SheetBomba:
        def generar_excel(self, *args, **kwargs):
            raise RuntimeError("openpyxl explotó")

    monkeypatch.setattr(router, "spreadsheet", _SheetBomba())

    rows = [("cliente_a", "Bogotá", 1), ("cliente_b", "Cali", 2)]
    out = enrutar_salida(_ok(["cliente", "ciudad", "total"], rows))
    assert out.kind == "text"
    assert out.file_path is None
