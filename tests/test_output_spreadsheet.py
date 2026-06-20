"""Pruebas de generación de Excel (.xlsx) (Fase 4).

Generan archivos .xlsx REALES con pandas + openpyxl, siempre dentro de
`tmp_path` (no se escribe fuera). Verifican: que el archivo se crea y se puede
reabrir con pandas conservando filas/columnas; que columnas duplicadas se
desambiguan (total, total_2); que las celdas None quedan vacías; y que crea la
carpeta de salida si no existe.
"""

from __future__ import annotations

import datetime
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


# ---------------------------------------------------------------------------
# BUG arreglado: datetime CON zona horaria (Postgres `timestamptz`)
# ---------------------------------------------------------------------------

def test_datetime_tz_aware_no_revienta_y_genera_archivo(tmp_path):
    """Una celda datetime tz-aware (Postgres timestamptz) YA NO tumba el Excel.

    Antes openpyxl lanzaba "Excel does not support datetimes with timezones".
    Reproduce el caso real: "facturación mes a mes de 1997" devuelve `mes` como
    1997-01-01 00:00:00+00:00 (tz-aware desde Neon).
    """
    utc = datetime.timezone.utc
    columns = ["mes", "facturacion"]
    rows = [
        (datetime.datetime(1997, 1, 1, tzinfo=utc), 61258),
        (datetime.datetime(1997, 2, 1, tzinfo=utc), 38484),
    ]
    # No debe lanzar ninguna excepción.
    ruta = spreadsheet.generar_excel(columns, rows, output_dir=str(tmp_path))
    assert os.path.exists(ruta)

    df = pd.read_excel(ruta, engine="openpyxl")
    assert len(df) == 2
    # El instante se conserva (mismo valor en UTC, ahora sin tz).
    assert df.iloc[0]["mes"] == datetime.datetime(1997, 1, 1)


def test_tz_offset_no_utc_se_normaliza_al_instante_utc(tmp_path):
    """Un datetime con offset distinto de UTC se normaliza al MISMO instante en UTC."""
    bogota = datetime.timezone(datetime.timedelta(hours=-5))
    columns = ["momento", "n"]
    # 2020-01-01 00:00 en Bogotá (-05) == 2020-01-01 05:00 UTC.
    rows = [(datetime.datetime(2020, 1, 1, 0, 0, tzinfo=bogota), 1)]
    ruta = spreadsheet.generar_excel(columns, rows, output_dir=str(tmp_path))
    df = pd.read_excel(ruta, engine="openpyxl")
    assert df.iloc[0]["momento"] == datetime.datetime(2020, 1, 1, 5, 0)


def test_naive_no_altera_numeros_texto_none_ni_fechas_sin_tz():
    """El saneo de tz NO toca números, texto, None, date ni datetimes ya naive."""
    naive_dt = datetime.datetime(2020, 5, 5, 12, 0)
    solo_fecha = datetime.date(2020, 5, 5)
    assert spreadsheet._naive(830) == 830
    assert spreadsheet._naive("texto") == "texto"
    assert spreadsheet._naive(None) is None
    assert spreadsheet._naive(solo_fecha) is solo_fecha
    assert spreadsheet._naive(naive_dt) is naive_dt
