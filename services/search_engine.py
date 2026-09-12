"""Búsqueda inversa por sufijo (derecha a izquierda)."""

from __future__ import annotations

from typing import Any


def sku_como_texto(valor: Any) -> str:
    """SKU siempre es texto: no se convierte a int (conserva ceros a la izquierda)."""
    if valor is None:
        return ""
    return str(valor).strip()


def normalizar_codigo(valor: Any) -> str:
    return "".join(ch for ch in sku_como_texto(valor).upper() if ch.isalnum())


def coincide_por_sufijo(sku: Any, consulta: Any) -> bool:
    """True si el SKU termina en la consulta (endsWith), tras recortar espacios."""
    sufijo = normalizar_codigo(consulta)
    if not sufijo:
        return True
    return normalizar_codigo(sku).endswith(sufijo)


def extraer_sufijo(dictado: str, minimo: int = 2) -> str:
    codigo = normalizar_codigo(dictado)
    if not codigo:
        return ""
    return codigo[-max(minimo, 1) :]


def buscar_por_sufijo(
    skus: list[dict[str, Any]],
    dictado: str,
    minimo: int = 2,
) -> dict[str, Any]:
    """Busca SKUs cuyo código termina en el sufijo dictado.

    Por defecto usa los últimos `minimo` caracteres. Si el operador dicta
    más dígitos, se usa todo el sufijo normalizado (búsqueda más precisa).
    """
    codigo = normalizar_codigo(dictado)
    if not codigo:
        return {
            "sufijo": "",
            "coincidencias": [],
            "total": 0,
            "unica": False,
            "requiere_desambiguacion": False,
            "mensaje": "No se dictó ningún código.",
        }

    sufijo = codigo if len(codigo) >= minimo else codigo
    hits = [item for item in skus if coincide_por_sufijo(item.get("sku", ""), sufijo)]

    total = len(hits)
    unica = total == 1
    requiere = total > 1
    if total == 0:
        mensaje = f"Ningún SKU termina en {sufijo}."
    elif unica:
        sku = hits[0]
        mensaje = (
            f"SKU {sku.get('sku')} confirmado. "
            f"Esperadas {sku.get('cantidad_esperada', 0)} cajas, "
            f"contadas {sku.get('contador', 0)}."
        )
    else:
        mensaje = (
            f"Hay {total} productos que terminan en {sufijo}. "
            "Dicta un carácter más o selecciónalo en pantalla."
        )

    return {
        "sufijo": sufijo,
        "coincidencias": hits,
        "total": total,
        "unica": unica,
        "requiere_desambiguacion": requiere,
        "mensaje": mensaje,
    }
