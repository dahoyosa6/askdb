"""Pruebas de generación de Excel (.xlsx) (Fase 4).

Generan archivos .xlsx REALES con pandas + openpyxl, siempre dentro de
`tmp_path` (no se escribe fuera). Verifican: que el archivo se crea y se puede
reabrir con pandas conservando filas/columnas; que columnas duplicadas se
desambiguan (total, total_2); que las celdas None quedan vacías; y que crea la
carpeta de salida si no existe.
"""

from __future__ import annotations

import math
import os

import pandas as pd

from app.output import spreadsheet


def test_crea_xlsx_reabrible_con_pandas(tmp_path):
    """Crea un .xlsx que pandas puede releer con las mismas filas y columnas."""
    columns = ["cliente", "total"]
    rows = [("QUICK-Stop", 110277), ("Save-a-lot", 104361)]
    ruta = spreadsheet.generar_excel(columns, rows, output_dir=str(tmp_path))

    assert ruta.endswith(".xlsx")
    assert os.path.exists(ruta)

    df = pd.read_excel(ruta, engine="openpyxl")
    assert list(df.columns) == columns
    assert len(df) == 2
    assert df.iloc[0]["cliente"] == "QUICK-Stop"
    assert int(df.iloc[0]["total"]) == 110277


def test_columnas_duplicadas_se_desambiguan(tmp_path):
    """Columnas con el mismo nombre -> total, total_2 (pandas exige unicidad)."""
    columns = ["total", "total"]
    rows = [(1, 2), (3, 4)]
    ruta = spreadsheet.generar_excel(columns, rows, output_dir=str(tmp_path))

    df = pd.read_excel(ruta, engine="openpyxl")
    assert list(df.columns) == ["total", "total_2"]


def test_celdas_none_quedan_vacias(tmp_path):
    """Una celda None se escribe vacía (pandas la relee como NaN)."""
    columns = ["cliente", "telefono"]
    rows = [("QUICK-Stop", None), ("Save-a-lot", "555-1234")]
    ruta = spreadsheet.generar_excel(columns, rows, output_dir=str(tmp_path))

    df = pd.read_excel(ruta, engine="openpyxl")
    # La primera fila tiene teléfono vacío -> NaN al releer.
    assert isinstance(df.iloc[0]["telefono"], float) and math.isnan(df.iloc[0]["telefono"])
    assert df.iloc[1]["telefono"] == "555-1234"


def test_crea_output_dir_si_no_existe(tmp_path):
    """Si la carpeta de salida no existe, se crea."""
    destino = tmp_path / "sub" / "carpeta"
    ruta = spreadsheet.generar_excel(["a"], [(1,), (2,)], output_dir=str(destino))
    assert os.path.exists(ruta)
    assert str(destino) in ruta


def test_nombre_estable_idempotente(tmp_path):
    """Misma entrada -> mismo nombre de archivo (determinista)."""
    columns = ["a", "b"]
    rows = [(1, 2), (3, 4)]
    ruta1 = spreadsheet.generar_excel(columns, rows, output_dir=str(tmp_path))
    ruta2 = spreadsheet.generar_excel(columns, rows, output_dir=str(tmp_path))
    assert ruta1 == ruta2
