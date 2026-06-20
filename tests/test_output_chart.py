"""Pruebas de generación de gráficas PNG (Fase 4).

Generan archivos PNG REALES con matplotlib, pero SIEMPRE dentro de `tmp_path`
(carpeta temporal de pytest): no se escribe nada fuera. El backend es "Agg"
(headless), así que no se abre ninguna ventana.

Verifican: que el PNG se crea y pesa > 0; barras y línea; que crea la carpeta de
salida si no existe; que omite celdas None sin reventar; y que el nombre es
estable/idempotente (misma entrada -> mismo nombre).
"""

from __future__ import annotations

import datetime
import os

from app.output import chart


def test_grafica_barras_crea_png_no_vacio(tmp_path):
    """barras crea un .png con contenido (> 0 bytes)."""
    rows = [("QUICK-Stop", 110277), ("Save-a-lot", 104361), ("Ernst", 104874)]
    ruta = chart.generar_grafica(
        ["cliente", "facturacion"], rows, tipo="barras", output_dir=str(tmp_path)
    )
    assert ruta.endswith(".png")
    assert os.path.exists(ruta)
    assert os.path.getsize(ruta) > 0


def test_grafica_linea_con_fechas_crea_archivo(tmp_path):
    """línea con fechas crea el archivo PNG."""
    rows = [
        (datetime.date(2026, 3, 1), 130),
        (datetime.date(2026, 1, 1), 100),
        (datetime.date(2026, 2, 1), 150),
    ]
    ruta = chart.generar_grafica(
        ["mes", "ventas"], rows, tipo="linea", output_dir=str(tmp_path)
    )
    assert os.path.exists(ruta)
    assert os.path.getsize(ruta) > 0


def test_crea_output_dir_si_no_existe(tmp_path):
    """Si la carpeta de salida no existe, se crea (makedirs exist_ok)."""
    destino = tmp_path / "no" / "existe" / "aun"
    rows = [("A", 1), ("B", 2)]
    ruta = chart.generar_grafica(
        ["cat", "n"], rows, tipo="barras", output_dir=str(destino)
    )
    assert os.path.exists(ruta)
    assert str(destino) in ruta


def test_omite_celdas_none_sin_reventar(tmp_path):
    """Pares con valor None se filtran; no debe lanzar excepción."""
    rows = [("A", 10), ("B", None), ("C", 30)]
    ruta = chart.generar_grafica(
        ["cat", "n"], rows, tipo="barras", output_dir=str(tmp_path)
    )
    assert os.path.exists(ruta)


def test_nombre_estable_idempotente(tmp_path):
    """Misma entrada -> mismo nombre de archivo (determinista, sin fecha/azar)."""
    rows = [("A", 1), ("B", 2)]
    ruta1 = chart.generar_grafica(
        ["cat", "n"], rows, tipo="barras", output_dir=str(tmp_path)
    )
    ruta2 = chart.generar_grafica(
        ["cat", "n"], rows, tipo="barras", output_dir=str(tmp_path)
    )
    assert ruta1 == ruta2


def test_nombre_cambia_con_datos_distintos(tmp_path):
    """Datos distintos -> nombres distintos (no se pisan archivos)."""
    ruta1 = chart.generar_grafica(
        ["cat", "n"], [("A", 1)], tipo="barras", output_dir=str(tmp_path)
    )
    ruta2 = chart.generar_grafica(
        ["cat", "n"], [("A", 2)], tipo="barras", output_dir=str(tmp_path)
    )
    assert ruta1 != ruta2


def test_linea_con_fechas_tz_aware_no_revienta(tmp_path):
    """Serie temporal con fechas tz-aware (Postgres timestamptz) -> gráfica OK.

    El eje X se normaliza con `_naive` antes de ordenar/dibujar; mezclar fechas con
    y sin zona horaria rompería matplotlib.
    """
    utc = datetime.timezone.utc
    rows = [
        (datetime.datetime(1997, 3, 1, tzinfo=utc), 130),
        (datetime.datetime(1997, 1, 1, tzinfo=utc), 100),
        (datetime.datetime(1997, 2, 1, tzinfo=utc), 150),
    ]
    ruta = chart.generar_grafica(
        ["mes", "facturacion"], rows, tipo="linea", output_dir=str(tmp_path)
    )
    assert os.path.exists(ruta)
    assert os.path.getsize(ruta) > 0
