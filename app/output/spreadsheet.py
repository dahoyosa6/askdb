"""Generación de archivos Excel (.xlsx) a partir de un resultado tabular.

Se usa cuando el resultado es un detalle largo o una tabla ancha: en vez de
volcar decenas de filas/columnas en el chat, se entrega un Excel descargable.

La decisión de SI conviene Excel la toma el router; aquí solo se escribe el
archivo con pandas + openpyxl (ya en el stack del proyecto).

Detalle importante: pandas exige nombres de columna ÚNICOS al construir el
DataFrame. Un SELECT con joins puede traer columnas repetidas (p. ej. dos
`order_id`); por eso se desambiguan ANTES de armar el DataFrame.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import re

import pandas as pd

from config import settings


def _naive(valor: object) -> object:
    """Convierte un datetime con zona horaria a "naive" (sin tz). Lo demás intacto.

    openpyxl NO admite escribir un datetime con `tzinfo` en un .xlsx y revienta con
    "Excel does not support datetimes with timezones". Postgres/Neon devuelve
    columnas `timestamptz` como datetimes tz-aware (p. ej. `1997-01-01 00:00:00+00:00`),
    así que cualquier consulta sobre fechas con zona horaria tumbaba la generación de
    Excel.

    Estrategia: se normaliza a UTC y luego se quita la tz (`astimezone(UTC)` +
    `replace(tzinfo=None)`). Se elige UTC (no la hora local) para que el instante
    quede bien definido y reproducible sin importar la zona del servidor; el dato
    de Northwind ya viene en UTC, así que el valor mostrado no cambia.

    Solo toca datetimes con `tzinfo`. Números, texto, None, fechas sin hora
    (`date`) y datetimes ya "naive" se devuelven sin cambios.
    """
    if isinstance(valor, datetime.datetime) and valor.tzinfo is not None:
        return valor.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return valor


def _filas_naive(rows: list[tuple]) -> list[tuple]:
    """Aplica `_naive` a cada celda de cada fila (saneo previo a escribir Excel)."""
    return [tuple(_naive(celda) for celda in fila) for fila in rows]


def _slug(texto: str) -> str:
    """Convierte un texto en un fragmento seguro para nombre de archivo."""
    limpio = re.sub(r"[^a-zA-Z0-9]+", "_", texto.lower()).strip("_")
    return limpio[:40] or "datos"


def _hash8(columns: list[str], rows: list[tuple]) -> str:
    """Hash corto y estable de (columnas, filas) para nombrar el archivo."""
    h = hashlib.sha1(repr(columns).encode() + repr(rows).encode())
    return h.hexdigest()[:8]


def _columnas_unicas(columns: list[str]) -> list[str]:
    """Desambigua nombres de columna repetidos: total, total -> total, total_2.

    pandas no admite columnas con el mismo nombre al construir el DataFrame. Se
    conserva la primera aparición y se sufija las siguientes con _2, _3, ...
    """
    vistos: dict[str, int] = {}
    resultado: list[str] = []
    for nombre in columns:
        if nombre not in vistos:
            vistos[nombre] = 1
            resultado.append(nombre)
        else:
            vistos[nombre] += 1
            resultado.append(f"{nombre}_{vistos[nombre]}")
    return resultado


def generar_excel(
    columns: list[str],
    rows: list[tuple],
    *,
    output_dir: str | None = None,
    nombre_base: str | None = None,
) -> str:
    """Escribe `rows` en un .xlsx y devuelve la ruta del archivo generado.

    Args:
        columns: nombres de columna (pueden venir repetidos; se desambiguan).
        rows: filas del resultado. Las celdas None quedan vacías en el Excel.
        output_dir: carpeta de salida; por defecto `settings.output_dir`.
        nombre_base: prefijo opcional para el nombre del archivo.

    Returns:
        Ruta del archivo .xlsx creado.
    """
    carpeta = output_dir if output_dir is not None else settings.output_dir
    os.makedirs(carpeta, exist_ok=True)

    columnas = _columnas_unicas(columns)
    # Saneo: openpyxl no escribe datetimes con zona horaria (Postgres devuelve
    # `timestamptz` tz-aware). Se normalizan a naive ANTES de armar el DataFrame.
    df = pd.DataFrame(_filas_naive(rows), columns=columnas)

    prefijo = _slug(nombre_base) if nombre_base else "tabla"
    slug_cols = _slug("_".join(columns))
    nombre = f"{prefijo}_{slug_cols}_{_hash8(columns, rows)}.xlsx"
    ruta = os.path.join(carpeta, nombre)

    df.to_excel(ruta, index=False, engine="openpyxl")
    return ruta
