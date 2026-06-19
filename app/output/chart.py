"""Generación de gráficas PNG a partir de un resultado tabular.

Esta capa toma `(columns, rows)` de una consulta y produce un archivo PNG con
una gráfica de barras o de línea. La decisión de SI conviene una gráfica (y de
qué tipo) la toma el router (`app/output/router.py`); aquí solo se dibuja.

Reglas de diseño:
- Backend headless: se fuerza el backend "Agg" ANTES de importar pyplot, para
  poder dibujar en un servidor sin pantalla (Railway, tests).
- Nombre de archivo DETERMINISTA (sin fecha ni azar): la misma entrada produce
  siempre el mismo nombre. Así es idempotente y fácil de probar.
- Se cierra SIEMPRE la figura (`plt.close`) para no fugar memoria en un proceso
  de larga vida (el bot corre indefinidamente).
"""

from __future__ import annotations

import hashlib
import os
import re

import matplotlib

# IMPORTANTE: fijar el backend headless ANTES de importar pyplot. En este orden
# matplotlib no intenta abrir una ventana (no hay pantalla en el servidor).
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (debe ir tras matplotlib.use)

from config import settings

# Umbrales de legibilidad para decidir barras horizontales (barh): si hay muchas
# categorías o etiquetas largas, las verticales se enciman y no se leen.
_MAX_BARRAS_VERTICALES = 8
_LARGO_ETIQUETA_PARA_HORIZONTAL = 12


def _slug(texto: str) -> str:
    """Convierte un texto en un fragmento seguro para nombre de archivo."""
    limpio = re.sub(r"[^a-zA-Z0-9]+", "_", texto.lower()).strip("_")
    return limpio[:40] or "datos"


def _hash8(columns: list[str], rows: list[tuple]) -> str:
    """Hash corto y estable de (columnas, filas) para nombrar el archivo.

    Determinista: misma entrada -> mismo hash. No usa fecha ni azar, de modo que
    regenerar la misma gráfica no crea archivos nuevos.
    """
    h = hashlib.sha1(repr(columns).encode() + repr(rows).encode())
    return h.hexdigest()[:8]


def _indice_columna_numerica(columns: list[str], rows: list[tuple]) -> int:
    """Devuelve el índice de la primera columna cuyos valores son numéricos.

    Se inspeccionan las celdas no-None. Si ninguna es claramente numérica se
    asume la última columna como eje Y (caso de borde defensivo; el router solo
    manda aquí pares graficables).
    """
    n_cols = len(columns)
    for i in range(n_cols):
        valores = [row[i] for row in rows if row[i] is not None]
        if valores and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in valores):
            return i
    return n_cols - 1


def generar_grafica(
    columns: list[str],
    rows: list[tuple],
    *,
    tipo: str,
    output_dir: str | None = None,
    nombre_base: str | None = None,
) -> str:
    """Dibuja una gráfica de `rows` y devuelve la ruta del PNG generado.

    Args:
        columns: nombres de las dos columnas (eje y valor).
        rows: filas (cada una con 2 valores: eje, valor).
        tipo: "linea" (serie temporal, se ordena por X) o "barras" (ranking,
            respeta el orden del SQL, que ya viene ordenado).
        output_dir: carpeta de salida; por defecto `settings.output_dir`.
        nombre_base: prefijo opcional para el nombre del archivo.

    Returns:
        Ruta absoluta/relativa del archivo PNG creado.
    """
    carpeta = output_dir if output_dir is not None else settings.output_dir
    os.makedirs(carpeta, exist_ok=True)

    # Identificar cuál columna es la numérica (eje Y) y cuál es el eje (X).
    idx_y = _indice_columna_numerica(columns, rows)
    idx_x = 1 - idx_y if len(columns) == 2 else (0 if idx_y != 0 else 1)

    nombre_x = columns[idx_x]
    nombre_y = columns[idx_y]

    # Filtrar pares donde el valor (y) es None: matplotlib no los grafica bien.
    pares = [(row[idx_x], row[idx_y]) for row in rows if row[idx_y] is not None]

    if tipo == "linea":
        # Una serie temporal se lee en orden cronológico del eje X.
        pares.sort(key=lambda p: p[0])
    # En "barras" se respeta el orden del SQL (un ranking ya viene ordenado).

    xs = [p[0] for p in pares]
    ys = [p[1] for p in pares]
    etiquetas = [str(x) for x in xs]

    fig, ax = plt.subplots(figsize=(8, 5))
    try:
        if tipo == "linea":
            ax.plot(xs, ys, marker="o")
            ax.set_xlabel(nombre_x)
            ax.set_ylabel(nombre_y)
            fig.autofmt_xdate()  # rota fechas si las hay
        else:
            # Barras horizontales si hay muchas categorías o etiquetas largas:
            # se leen mejor que verticales encimadas.
            etiqueta_larga = any(len(e) > _LARGO_ETIQUETA_PARA_HORIZONTAL for e in etiquetas)
            horizontal = len(etiquetas) > _MAX_BARRAS_VERTICALES or etiqueta_larga
            if horizontal:
                # invertir para que el mayor quede arriba respetando el orden.
                ax.barh(etiquetas[::-1], ys[::-1])
                ax.set_xlabel(nombre_y)
                ax.set_ylabel(nombre_x)
            else:
                ax.bar(etiquetas, ys)
                ax.set_xlabel(nombre_x)
                ax.set_ylabel(nombre_y)

        ax.set_title(f"{nombre_y} por {nombre_x}")
        fig.tight_layout()

        prefijo = _slug(nombre_base) if nombre_base else "grafica"
        slug_cols = _slug(f"{nombre_x}_{nombre_y}")
        nombre = f"{prefijo}_{slug_cols}_{_hash8(columns, rows)}.png"
        ruta = os.path.join(carpeta, nombre)
        fig.savefig(ruta)
        return ruta
    finally:
        # SIEMPRE cerrar la figura: en un proceso de larga vida (el bot) dejar
        # figuras abiertas fuga memoria.
        plt.close(fig)
