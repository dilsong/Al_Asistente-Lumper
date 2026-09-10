"""Validación local de licencia mediante token Fernet en licencia.json."""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Any

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from services.paths import LICENCIA_PATH, ensure_data_dir


def _fernet() -> Fernet:
    """Usa AL_LICENSE_KEY si es Fernet válido; si no, deriva una clave local de demo."""
    raw = os.environ.get("AL_LICENSE_KEY", "").strip()
    if raw:
        try:
            return Fernet(raw.encode("utf-8"))
        except (ValueError, InvalidToken):
            pass
    digest = hashlib.sha256(b"AL-ASISTENTE-DE-LUMPER-DEMO-KEY").digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _payload_demo() -> dict[str, Any]:
    return {
        "fecha_expiracion": "2027-12-31",
        "cliente": "AL Demo Warehouse",
        "licencia_id": "AL-DEMO-001",
        "modulos": ["ocr", "voz", "conteo"],
    }


def _parse_fecha(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def ensure_license_file() -> None:
    """Crea una licencia de demostración cifrada si no existe el archivo."""
    ensure_data_dir()
    if LICENCIA_PATH.exists():
        return
    token = _fernet().encrypt(json.dumps(_payload_demo(), ensure_ascii=False).encode("utf-8"))
    LICENCIA_PATH.write_text(
        json.dumps(
            {
                "token": token.decode("utf-8"),
                "cliente": "AL Demo Warehouse",
                "licencia_id": "AL-DEMO-001",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _leer_archivo() -> dict[str, Any]:
    ensure_license_file()
    return json.loads(LICENCIA_PATH.read_text(encoding="utf-8"))


def decifrar_licencia() -> dict[str, Any]:
    data = _leer_archivo()
    token = data.get("token")
    if not token:
        raise ValueError("licencia.json no contiene token cifrado")
    try:
        raw = _fernet().decrypt(token.encode("utf-8"))
    except InvalidToken as exc:
        raise ValueError("Token de licencia inválido o clave incorrecta") from exc
    payload = json.loads(raw.decode("utf-8"))
    if "fecha_expiracion" not in payload:
        raise ValueError("El token no incluye fecha_expiracion")
    return payload


def estado_licencia() -> dict[str, Any]:
    try:
        payload = decifrar_licencia()
        vencimiento = _parse_fecha(payload["fecha_expiracion"])
        vigente = date.today() <= vencimiento
        dias = (vencimiento - date.today()).days
        return {
            "valida": vigente,
            "bloqueada": not vigente,
            "fecha_expiracion": payload["fecha_expiracion"],
            "dias_restantes": max(dias, 0),
            "cliente": payload.get("cliente", ""),
            "licencia_id": payload.get("licencia_id", ""),
            "modulos": payload.get("modulos", []),
            "error": None if vigente else "La licencia expiró. Operación bloqueada.",
        }
    except Exception as exc:  # noqa: BLE001 — devolver estado usable a la API
        return {
            "valida": False,
            "bloqueada": True,
            "fecha_expiracion": None,
            "dias_restantes": 0,
            "cliente": "",
            "licencia_id": "",
            "modulos": [],
            "error": str(exc),
        }


def licencia_valida() -> bool:
    return bool(estado_licencia().get("valida"))
