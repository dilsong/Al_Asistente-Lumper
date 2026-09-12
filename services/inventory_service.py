"""Lógica de conteo, estados de SKU, KPIs y discrepancias."""

from __future__ import annotations

from typing import Any

from services.persistence import get_store
from services.search_engine import buscar_por_sufijo, coincide_por_sufijo, normalizar_codigo, sku_como_texto


def desglose_paletas(cajas: int, factor: int) -> dict[str, Any]:
    cajas = max(int(cajas or 0), 0)
    factor = int(factor or 0)
    if factor <= 0:
        return {
            "cajas_por_paleta": 0,
            "paletas_completas": 0,
            "cajas_parciales": cajas,
            "desglose_paletas": "Defina cajas por paleta",
            "mensaje_paletas": "Define las cajas por paleta de este producto.",
        }
    completas = cajas // factor
    parcial = cajas % factor
    etiqueta = (
        f"{completas} Paletas completas | 1 Parcial ({parcial} cajas)"
        if parcial
        else f"{completas} Paletas completas"
    )
    if parcial:
        voz = (
            f"Llevas {completas} paletas completas y 1 parcial de {parcial} cajas "
            "para este producto."
        )
    else:
        voz = f"Llevas {completas} paletas completas y ninguna parcial para este producto."
    return {
        "cajas_por_paleta": factor,
        "paletas_completas": completas,
        "cajas_parciales": parcial,
        "desglose_paletas": etiqueta,
        "mensaje_paletas": voz,
    }


def _asegurar_sku_texto(item: dict[str, Any]) -> dict[str, Any]:
    item["sku"] = sku_como_texto(item.get("sku"))
    return item


def _recalcular_estado(item: dict[str, Any]) -> dict[str, Any]:
    _asegurar_sku_texto(item)
    esperado = int(item.get("cantidad_esperada") or 0)
    contador = int(item.get("contador") or 0)
    factor = int(item.get("cajas_por_paleta") or 0)
    item["cajas_por_paleta"] = max(factor, 0)
    item["discrepancia"] = max(contador - esperado, 0)
    if contador > esperado:
        item["estado"] = "exceso"
    elif esperado > 0 and contador >= esperado:
        item["estado"] = "completado"
    elif contador > 0:
        item["estado"] = "en_proceso"
    else:
        item["estado"] = "pendiente"
    item.update(desglose_paletas(contador, item["cajas_por_paleta"]))
    return item


def cargar_inventario() -> dict[str, Any]:
    data = get_store().load_inventory()
    for item in data.get("skus", []):
        _recalcular_estado(item)
    return data


def guardar_inventario(data: dict[str, Any]) -> dict[str, Any]:
    for item in data.get("skus", []):
        _recalcular_estado(item)
    get_store().save_inventory(data)
    return data


def kpis(inventario: dict[str, Any] | None = None) -> dict[str, Any]:
    inventario = inventario or cargar_inventario()
    skus = inventario.get("skus") or []
    esperadas = sum(int(i.get("cantidad_esperada") or 0) for i in skus)
    contadas = sum(int(i.get("contador") or 0) for i in skus)
    cajas_pendientes = sum(
        max(int(i.get("cantidad_esperada") or 0) - int(i.get("contador") or 0), 0) for i in skus
    )
    skus_pendientes = sum(
        1 for i in skus if int(i.get("contador") or 0) < int(i.get("cantidad_esperada") or 0)
    )
    avance = round((min(contadas, esperadas) / esperadas) * 100, 1) if esperadas else 0.0
    paletas_pendientes = 0
    for item in skus:
        factor = int(item.get("cajas_por_paleta") or 0)
        if factor <= 0:
            continue
        resto = max(int(item.get("cantidad_esperada") or 0) - int(item.get("contador") or 0), 0)
        if resto:
            paletas_pendientes += (resto + factor - 1) // factor
    paletas_definidas = any(int(i.get("cajas_por_paleta") or 0) > 0 for i in skus)
    return {
        "contenedor": inventario.get("contenedor") or "",
        "formato": inventario.get("formato") or "",
        "cajas_pendientes": cajas_pendientes,
        "skus_pendientes": skus_pendientes,
        "paletas_pendientes": paletas_pendientes,
        "paletas_definidas": paletas_definidas,
        "avance": avance,
        "cajas_esperadas": esperadas,
        "cajas_contadas": contadas,
        "skus_totales": len(skus),
    }


def buscar(dictado: str, minimo: int | None = None) -> dict[str, Any]:
    inventario = cargar_inventario()
    cfg_min = minimo if minimo is not None else 2
    resultado = buscar_por_sufijo(
        inventario.get("skus") or [],
        sku_como_texto(dictado),
        minimo=cfg_min,
    )
    resultado["contenedor"] = inventario.get("contenedor") or ""
    return resultado


def _encontrar_sku(skus: list[dict[str, Any]], sku: str) -> dict[str, Any] | None:
    objetivo = normalizar_codigo(sku)
    if not objetivo:
        return None
    exactos = [item for item in skus if normalizar_codigo(item.get("sku", "")) == objetivo]
    if exactos:
        return exactos[0]
    hits = [item for item in skus if coincide_por_sufijo(item.get("sku", ""), objetivo)]
    if len(hits) == 1:
        return hits[0]
    return None


def aplicar_conteo(sku: str, cantidad: int, modo: str) -> dict[str, Any]:
    if cantidad < 0:
        raise ValueError("La cantidad no puede ser negativa")
    inventario = cargar_inventario()
    item = _encontrar_sku(inventario.get("skus") or [], sku)
    if not item:
        raise KeyError(f"SKU {sku} no está en la sesión")

    anterior = int(item.get("contador") or 0)
    if modo == "sumar":
        item["contador"] = anterior + cantidad
        accion = "suma"
    elif modo == "editar":
        item["contador"] = cantidad
        accion = "edicion"
    else:
        raise ValueError("Modo inválido. Use sumar o editar.")

    _recalcular_estado(item)
    guardar_inventario(inventario)

    exceso = int(item.get("discrepancia") or 0)
    alerta = None
    mensaje = (
        f"SKU {item['sku']}: {item['contador']} de {item['cantidad_esperada']} cajas."
    )
    if exceso > 0:
        alerta = f"Atención: Discrepancia detectada. Exceso de {exceso} cajas"
        mensaje = alerta + ". " + mensaje

    return {
        "ok": True,
        "accion": accion,
        "sku": item,
        "alerta_discrepancia": alerta,
        "mensaje": mensaje,
        "kpis": kpis(inventario),
        "inventario": inventario,
    }


def pendientes() -> dict[str, Any]:
    inventario = cargar_inventario()
    metricas = kpis(inventario)
    pendientes_sku = [
        item
        for item in inventario.get("skus") or []
        if int(item.get("contador") or 0) < int(item.get("cantidad_esperada") or 0)
    ]
    return {
        **metricas,
        "mensaje_skus": f"Faltan {metricas['skus_pendientes']} SKUs por completar.",
        "mensaje_cajas": (
            f"Faltan {metricas['cajas_pendientes']} cajas del contenedor "
            f"{metricas['contenedor'] or 'actual'}."
        ),
        "skus": pendientes_sku,
    }


def estatus_contenedor() -> dict[str, Any]:
    inventario = cargar_inventario()
    metricas = kpis(inventario)
    completo = bool(metricas["skus_totales"]) and metricas["cajas_pendientes"] == 0
    if not metricas["skus_totales"]:
        mensaje = "No hay un contenedor cargado."
    elif completo:
        mensaje = "¡El contenedor se ha descargado por completo!"
    elif not metricas.get("paletas_definidas"):
        mensaje = (
            f"Faltan {metricas['skus_pendientes']} SKUs por sacar y "
            f"{metricas['cajas_pendientes']} cajas en total (paletas no definidas)."
        )
    else:
        mensaje = (
            f"Faltan {metricas['skus_pendientes']} SKUs por sacar, "
            f"{metricas['cajas_pendientes']} cajas en total y "
            f"{metricas['paletas_pendientes']} paletas en total."
        )
    return {
        **metricas,
        "completo": completo,
        "mensaje": mensaje,
        "inventario": inventario,
    }


def actualizar_paleta(sku: str, cajas_por_paleta: int) -> dict[str, Any]:
    if cajas_por_paleta < 0:
        raise ValueError("Cajas por paleta no puede ser negativa")
    inventario = cargar_inventario()
    item = _encontrar_sku(inventario.get("skus") or [], sku)
    if not item:
        raise KeyError(f"SKU {sku} no está en la sesión")
    item["cajas_por_paleta"] = int(cajas_por_paleta)
    _recalcular_estado(item)
    guardar_inventario(inventario)
    return {
        "ok": True,
        "sku": item,
        "mensaje": (
            f"SKU {item['sku']}: {item['cajas_por_paleta']} cajas por paleta. "
            f"{item['desglose_paletas']}."
        ),
        "kpis": kpis(inventario),
        "inventario": inventario,
    }
