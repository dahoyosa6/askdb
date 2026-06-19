"""Glosario de negocio del dominio Northwind.

Northwind no nombra las cosas como las nombra una dueña de negocio. "Ventas",
"facturación" o "mejor cliente" no son columnas: son cálculos sobre
`order_details`. Este glosario traduce el vocabulario de negocio al modelo de
datos para que Claude no tenga que adivinar.

Se inyecta como bloque de texto en el prompt de sistema, junto al esquema.

Funciones públicas:
- `GLOSSARY` -> el texto del glosario (constante).
- `get_glossary()` -> devuelve `GLOSSARY` (punto de extensión futuro).
- `normalize(texto)` -> normalización robusta de strings (acentos/mayúsculas).
"""

from __future__ import annotations

import unicodedata

# El glosario es texto pensado para el modelo: claro, conciso, con la fórmula o
# la tabla exacta donde vive cada concepto de negocio.
GLOSSARY: str = """\
GLOSARIO DE NEGOCIO (dominio Northwind). Traduce términos de negocio al modelo
de datos. Úsalo para resolver preguntas en lenguaje natural a SQL correcto.

- VENTA / VALOR DE UNA LÍNEA: en la tabla order_details, el valor de una línea
  de pedido se calcula como unit_price * quantity * (1 - discount).
  No existe una columna "total"; siempre se calcula.
- INGRESOS / FACTURACIÓN / VENTAS TOTALES: suma de SUM(unit_price * quantity *
  (1 - discount)) sobre order_details, uniendo con orders cuando se necesite
  filtrar por fecha, cliente o empleado.
- PEDIDO / ORDEN: una fila en la tabla orders (identificada por order_id).
- DETALLE DE PEDIDO / LÍNEAS: filas en order_details (un order_id puede tener
  varias líneas, una por producto).
- MEJOR CLIENTE / CLIENTE TOP: el cliente con mayor facturación. Se agrupa por
  customers.customer_id y se ordena por la suma de ventas descendente.
- PRODUCTO MÁS VENDIDO: el producto con mayor cantidad total (SUM(quantity)) o
  mayor facturación, según pregunte el usuario; ante la duda, por cantidad.
- CLIENTE: fila en customers (company_name es el nombre comercial visible).
- EMPLEADO / VENDEDOR: fila en employees. El nombre se arma con first_name y
  last_name. orders.employee_id indica quién registró el pedido.
- PROVEEDOR: fila en suppliers (company_name es el nombre del proveedor).
- CATEGORÍA: fila en categories (category_name); products.category_id la enlaza.
- TRANSPORTADORA / TRANSPORTISTA: fila en shippers; orders.ship_via la enlaza.
- INVENTARIO / STOCK / EXISTENCIAS: products.units_in_stock.
- PRECIO DE UN PRODUCTO: products.unit_price (precio de catálogo, distinto del
  unit_price de order_details, que es el precio al que se vendió esa línea).
- FECHA DE UN PEDIDO: orders.order_date. Para "este mes", "este trimestre" o
  "el mes pasado", filtra sobre order_date.
- DESCUENTO: order_details.discount (fracción entre 0 y 1; 0.15 = 15%).
"""


def get_glossary() -> str:
    """Devuelve el texto del glosario de negocio."""
    return GLOSSARY


def normalize(text: str) -> str:
    """Normaliza un string para comparación robusta.

    Quita acentos/diacríticos, pasa a minúsculas y colapsa espacios. Útil si en
    el futuro se hace match de términos del glosario contra la pregunta del
    usuario (p. ej. "facturación" == "facturacion").
    """
    if not text:
        return ""
    # NFKD separa el carácter base de su diacrítico; descartamos los diacríticos.
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(without_accents.lower().split())
