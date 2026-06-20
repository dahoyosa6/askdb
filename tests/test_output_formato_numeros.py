"""Pruebas del formateo de NÚMEROS en la salida de TEXTO (router).

El bug que motiva estas pruebas: el agente respondía con números crudos de
decimales infinitos (p. ej. una facturación que debía verse "617.085,20" salía
como "617085.1999999998"). El cálculo es correcto; el problema es de PRESENTACIÓN.

Reglas que se prueban (es-CO, PYME de habla hispana):
- float / Decimal: redondear a 2 decimales y usar separador de miles con punto y
  decimales con coma. 617085.1999999998 -> "617.085,20".
- int: SIN separador de miles. Un año (1997) o un ID (10248) NUNCA deben verse
  "1.997" / "10.248". Por eso a los int no se les aplica separador (regla segura:
  un int es ambiguo entre cantidad / año / identificador y no se puede distinguir
  por el valor; lo seguro es no romper años ni IDs).
- bool: no es número (sí/no); no se formatea como cantidad.
- None -> "sin dato". date/datetime/str -> sin cambios.

Convención del proyecto: pruebas puras, sin red ni disco, en español.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from app.agent.execute import AnswerResult
from app.output.router import _formatear_texto, _valor_legible, enrutar_salida


def _ok(columns, rows):
    return AnswerResult(ok=True, columns=columns, rows=rows, sql="SELECT ...", attempts=1)


# ---------------------------------------------------------------------------
# _valor_legible: el corazón del formateo, valor por valor
# ---------------------------------------------------------------------------

def test_float_muchos_decimales_redondea_y_separa_miles():
    """El bug exacto reportado: 617085.1999999998 -> '617.085,20'."""
    assert _valor_legible(617085.1999999998) == "617.085,20"


def test_float_redondea_a_dos_decimales():
    assert _valor_legible(267868.18) == "267.868,18"


def test_float_pequeno_sin_miles():
    assert _valor_legible(3.5) == "3,50"


def test_float_redondeo_hacia_arriba():
    assert _valor_legible(2.005) in {"2,00", "2,01"}  # depende del redondeo binario; ambos válidos


def test_decimal_redondea_y_separa_miles():
    """Decimal (lo típico de Postgres para montos)."""
    assert _valor_legible(Decimal("267868.18")) == "267.868,18"


def test_decimal_muchos_decimales():
    assert _valor_legible(Decimal("617085.1999999998")) == "617.085,20"


def test_decimal_entero_muestra_dos_decimales():
    assert _valor_legible(Decimal("1000")) == "1.000,00"


def test_float_negativo():
    assert _valor_legible(-1234.5) == "-1.234,50"


def test_float_millones():
    assert _valor_legible(1234567.89) == "1.234.567,89"


# ---------------------------------------------------------------------------
# int: NO se le aplica separador (proteger años e IDs)
# ---------------------------------------------------------------------------

def test_int_normal_se_queda_entero_sin_separador():
    """Un conteo (830 pedidos) se queda '830', no '830'."""
    assert _valor_legible(830) == "830"


def test_int_grande_no_lleva_separador():
    """Un int grande NO lleva separador: podría ser un ID, no una cantidad."""
    assert _valor_legible(10248) == "10248"


def test_anio_no_se_formatea_como_miles():
    """REGLA CLAVE: un año (1997) NO debe verse '1.997'."""
    assert _valor_legible(1997) == "1997"


def test_anio_2026():
    assert _valor_legible(2026) == "2026"


def test_int_negativo():
    assert _valor_legible(-5) == "-5"


# ---------------------------------------------------------------------------
# bool, None, fechas, str: sin formateo numérico
# ---------------------------------------------------------------------------

def test_bool_no_se_formatea_como_cantidad():
    """bool es subclase de int en Python, pero un sí/no no es una cantidad."""
    assert _valor_legible(True) == "True"
    assert _valor_legible(False) == "False"


def test_none_es_sin_dato():
    assert _valor_legible(None) == "sin dato"


def test_str_sin_cambios():
    assert _valor_legible("QUICK-Stop") == "QUICK-Stop"


def test_str_que_parece_numero_no_se_toca():
    """Un str se respeta tal cual aunque parezca número (no es float real)."""
    assert _valor_legible("617085.1999999998") == "617085.1999999998"


def test_date_sin_cambios():
    d = datetime.date(2026, 1, 15)
    assert _valor_legible(d) == str(d)


def test_datetime_sin_cambios():
    dt = datetime.datetime(2026, 1, 15, 9, 30)
    assert _valor_legible(dt) == str(dt)


# ---------------------------------------------------------------------------
# _formatear_texto: el formateo aplicado a las formas reales (1x1, 1xN, NxN)
# ---------------------------------------------------------------------------

def test_un_dato_1x1_float_se_formatea():
    """1 fila x 1 col con un float crudo -> valor formateado + punto final."""
    texto = _formatear_texto(["facturacion"], [(617085.1999999998,)])
    assert texto == "617.085,20."


def test_un_dato_1x1_int_entero():
    """1x1 con un conteo entero -> '830.' (sin separador)."""
    assert _formatear_texto(["total"], [(830,)]) == "830."


def test_ficha_1xN_formatea_solo_los_numericos():
    """1 fila x N cols: el monto se formatea, el texto y el año intactos."""
    texto = _formatear_texto(
        ["cliente", "anio", "facturacion"],
        [("QUICK-Stop", 1997, Decimal("110277.5"))],
    )
    assert "QUICK-Stop" in texto
    assert "1997" in texto and "1.997" not in texto  # el año no se rompe
    assert "110.277,50" in texto


def test_varias_filas_formatea_numericos_por_registro():
    """Varias filas x N cols: cada monto formateado, sin romper la estructura."""
    texto = _formatear_texto(
        ["cliente", "facturacion"],
        [("QUICK-Stop", Decimal("110277.5")), ("Save-a-lot", Decimal("104361.0"))],
    )
    assert "110.277,50" in texto
    assert "104.361,00" in texto
    assert "QUICK-Stop" in texto and "Save-a-lot" in texto


def test_varias_filas_una_columna_numerica():
    """Lista de 1 columna numérica: cada valor formateado."""
    texto = _formatear_texto(["monto"], [(1234.5,), (6789.0,)])
    assert "1.234,50" in texto
    assert "6.789,00" in texto


# ---------------------------------------------------------------------------
# Integración por enrutar_salida (extremo a extremo de la rama texto)
# ---------------------------------------------------------------------------

def test_enrutar_salida_1x1_float_formatea():
    out = enrutar_salida(_ok(["facturacion"], [(617085.1999999998,)]))
    assert out.kind == "text"
    assert out.text == "617.085,20."


def test_enrutar_salida_no_antepone_simbolo_moneda():
    """No se asume moneda: nunca anteponer '$' (puede ser un conteo o un ratio)."""
    out = enrutar_salida(_ok(["valor"], [(267868.18,)]))
    assert "$" not in out.text
    assert out.text == "267.868,18."
