"""Historial de conversación Operador ↔ AL persistido en sesion_chat.json."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from services.persistence import get_store


def listar_mensajes() -> list[dict[str, Any]]:
    return list(get_store().load_chat().get("mensajes") or [])


def agregar_mensaje(rol: str, texto: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    chat = get_store().load_chat()
    mensaje = {
        "id": str(uuid4()),
        "rol": rol if rol in {"operador", "al", "sistema"} else "sistema",
        "texto": texto.strip(),
        "ts": datetime.now().isoformat(timespec="seconds"),
        "meta": meta or {},
    }
    chat.setdefault("mensajes", []).append(mensaje)
    get_store().save_chat(chat)
    return mensaje


def reemplazar_chat(mensajes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    get_store().save_chat({"mensajes": mensajes})
    return mensajes
