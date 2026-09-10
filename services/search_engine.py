"""Búsqueda inversa por sufijo (derecha a izquierda)."""

from __future__ import annotations

from typing import Any


def normalizar_codigo(valor: str) -> str:
    return "".join(ch for ch in str(valor).upper() if ch.isalnum())


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
    hits = [item for item in skus if normalizar_codigo(item.get("sku", "")).endswith(sufijo)]

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
