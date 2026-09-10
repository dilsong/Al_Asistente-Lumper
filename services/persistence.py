"""Capa de persistencia local (JSON/CSV) con adaptador MySQL preparado."""

from __future__ import annotations

import csv
import json
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from services.paths import (
    CHAT_PATH,
    CONFIG_PATH,
    CSV_EXPORT_PATH,
    INVENTARIO_PATH,
    ensure_data_dir,
)

INVENTARIO_VACIO: dict[str, Any] = {
    "contenedor": "",
    "formato": "",
    "fecha_carga": None,
    "skus": [],
}

CONFIG_DEFAULT: dict[str, Any] = {
    "wake_word": "oye al",
    "sufijo_default": 2,
    "idioma": "es-ES",
    "confianza_minima": 0.55,
    "longitud_minima": 2,
    "comandos": {
        "BUSCAR": ["buscar", "encontrar", "ubica", "dame"],
        "SUMAR": ["suma", "agrega", "ponle", "van"],
        "EDITAR": ["edita", "cambia", "fija en", "reemplaza"],
        "PENDIENTES_SKU": ["cuantos skus faltan", "skus pendientes"],
        "PENDIENTES_CAJAS": ["cuantas cajas faltan", "resto del contenedor", "cajas faltantes"],
        "PALETAS": [
            "cuantas paletas van",
            "cuantas paletas",
            "paletas van",
            "cuantas paletas llevo",
        ],
        "ESTATUS": ["estatus", "status", "estado del contenedor", "como vamos"],
    },
}

CHAT_VACIO: dict[str, Any] = {"mensajes": []}


def _leer_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _escribir_json(path: Path, data: Any) -> None:
    ensure_data_dir()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class StorageBackend(ABC):
    """Contrato único para JSON local hoy y MySQL mañana."""

    @abstractmethod
    def load_inventory(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def save_inventory(self, data: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def load_chat(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def save_chat(self, data: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def load_config(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def export_inventory_csv(self, dest: Path | None = None) -> Path:
        raise NotImplementedError


class JsonFileStore(StorageBackend):
    def load_inventory(self) -> dict[str, Any]:
        data = _leer_json(INVENTARIO_PATH, INVENTARIO_VACIO)
        data.setdefault("skus", [])
        data.setdefault("contenedor", "")
        data.setdefault("formato", "")
        return data

    def save_inventory(self, data: dict[str, Any]) -> None:
        _escribir_json(INVENTARIO_PATH, data)

    def load_chat(self) -> dict[str, Any]:
        data = _leer_json(CHAT_PATH, CHAT_VACIO)
        data.setdefault("mensajes", [])
        return data

    def save_chat(self, data: dict[str, Any]) -> None:
        _escribir_json(CHAT_PATH, data)

    def load_config(self) -> dict[str, Any]:
        if not CONFIG_PATH.exists():
            _escribir_json(CONFIG_PATH, CONFIG_DEFAULT)
            return dict(CONFIG_DEFAULT)
        cfg = _leer_json(CONFIG_PATH, CONFIG_DEFAULT)
        merged = dict(CONFIG_DEFAULT)
        merged.update(cfg)
        comandos = dict(CONFIG_DEFAULT["comandos"])
        comandos.update(cfg.get("comandos") or {})
        merged["comandos"] = comandos
        return merged

    def export_inventory_csv(self, dest: Path | None = None) -> Path:
        inventario = self.load_inventory()
        dest = dest or CSV_EXPORT_PATH
        ensure_data_dir()
        with dest.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "contenedor",
                    "sku",
                    "producto",
                    "cantidad_esperada",
                    "contador",
                    "estado",
                    "discrepancia",
                    "cajas_por_paleta",
                    "paletas_completas",
                    "cajas_parciales",
                ],
            )
            writer.writeheader()
            for item in inventario.get("skus", []):
                writer.writerow(
                    {
                        "contenedor": inventario.get("contenedor", ""),
                        "sku": item.get("sku", ""),
                        "producto": item.get("producto", ""),
                        "cantidad_esperada": item.get("cantidad_esperada", 0),
                        "contador": item.get("contador", 0),
                        "estado": item.get("estado", ""),
                        "discrepancia": item.get("discrepancia", 0),
                        "cajas_por_paleta": item.get("cajas_por_paleta", 0),
                        "paletas_completas": item.get("paletas_completas", 0),
                        "cajas_parciales": item.get("cajas_parciales", 0),
                    }
                )
        return dest


class CsvFileStore:
    """Importación auxiliar de reportes tabulares (.csv)."""

    @staticmethod
    def import_skus(path: Path, contenedor: str = "", formato: str = "CSV") -> dict[str, Any]:
        skus: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                sku = (
                    row.get("sku")
                    or row.get("SKU")
                    or row.get("Product")
                    or row.get("producto")
                    or ""
                ).strip()
                if not sku:
                    continue
                qty_raw = (
                    row.get("cantidad_esperada")
                    or row.get("QTY")
                    or row.get("qty")
                    or row.get("Total Cases")
                    or row.get("Exp Eaches")
                    or "0"
                )
                try:
                    qty = int(float(str(qty_raw).replace(",", "")))
                except ValueError:
                    qty = 0
                factor_raw = (
                    row.get("cajas_por_paleta")
                    or row.get("TiHi")
                    or row.get("pallet_factor")
                    or "0"
                )
                try:
                    factor = int(float(str(factor_raw).replace(",", "") or 0))
                except ValueError:
                    factor = 0
                skus.append(
                    {
                        "sku": sku,
                        "producto": (row.get("producto") or row.get("Product") or sku).strip(),
                        "cantidad_esperada": qty,
                        "contador": 0,
                        "estado": "pendiente",
                        "discrepancia": 0,
                        "cajas_por_paleta": max(factor, 0),
                    }
                )
                if not contenedor:
                    contenedor = (
                        row.get("contenedor")
                        or row.get("Trailer")
                        or row.get("Other Reference Number")
                        or ""
                    ).strip()
        return {
            "contenedor": contenedor,
            "formato": formato,
            "fecha_carga": datetime.now().isoformat(timespec="seconds"),
            "skus": skus,
        }


class MySQLStore(StorageBackend):
    """Adaptador futuro. Activar con AL_STORAGE=mysql y DATABASE_URL."""

    def __init__(self) -> None:
        self.dsn = os.environ.get("DATABASE_URL", "")

    def _no_disponible(self) -> None:
        raise NotImplementedError(
            "MySQLStore está preparado como contrato, pero aún no está conectado. "
            "Use AL_STORAGE=json (default) o implemente el driver con DATABASE_URL."
        )

    def load_inventory(self) -> dict[str, Any]:
        self._no_disponible()
        return INVENTARIO_VACIO

    def save_inventory(self, data: dict[str, Any]) -> None:
        self._no_disponible()

    def load_chat(self) -> dict[str, Any]:
        self._no_disponible()
        return CHAT_VACIO

    def save_chat(self, data: dict[str, Any]) -> None:
        self._no_disponible()

    def load_config(self) -> dict[str, Any]:
        self._no_disponible()
        return CONFIG_DEFAULT

    def export_inventory_csv(self, dest: Path | None = None) -> Path:
        self._no_disponible()
        return dest or CSV_EXPORT_PATH


def get_store() -> StorageBackend:
    backend = os.environ.get("AL_STORAGE", "json").strip().lower()
    if backend == "mysql":
        return MySQLStore()
    return JsonFileStore()
