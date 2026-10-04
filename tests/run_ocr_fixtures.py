"""Ejecuta OCR real sobre las dos hojas locales. No versiona resultados sensibles."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.ocr_engine import procesar_documento

FIXTURES = ROOT / "tests" / "fixtures" / "ocr"


def _correr(nombre: str, path: Path, formato: str) -> None:
    print(f"\n===== {nombre} =====", flush=True)
    if not path.is_file():
        print(f"Sin fixture: {path}", flush=True)
        return
    invent = procesar_documento(path.read_bytes(), formato=formato)
    print(f"[AL OCR TEST] contenedor={invent.get('contenedor')}", flush=True)
    print(f"[AL OCR TEST] skus={len(invent.get('skus') or [])}", flush=True)
    for item in invent.get("skus") or []:
        print(
            f"  {item.get('sku')}  esperado={item.get('cantidad_esperada')}  "
            f"producto={item.get('producto')!r}",
            flush=True,
        )


if __name__ == "__main__":
    _correr("PURCHASE ORDER 02", FIXTURES / "purchase_order_real_02.jpg", "A")
