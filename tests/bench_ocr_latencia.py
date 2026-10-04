"""Benchmark de latencia OCR. No versiona resultados. No cambia reglas de SKU."""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import ocr_engine as ocr

FIXTURES = ROOT / "tests" / "fixtures" / "ocr"
HOJAS = (
    ("po8", FIXTURES / "purchase_order_real_02.jpg", "A"),
    ("po16", FIXTURES / "purchase_order_real_03.jpg", "A"),
    ("inbound", FIXTURES / "inbound_receiving_real_01.png", "B"),
)
MODELOS_PROBE = (
    "gemini-flash-latest",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
)
PAUSA_S = 13


def _clasificar_error(err: object) -> str:
    texto = str(err).lower()
    if "503" in texto or "unavailable" in texto or "high demand" in texto:
        return "503"
    if "429" in texto or "resource_exhausted" in texto or "too many requests" in texto:
        return "429"
    if "timeout" in texto or "timed out" in texto:
        return "timeout"
    if "404" in texto or "not found" in texto:
        return "404"
    return "error"


def _probar_modelo(jpeg: bytes, modelo: str, timeout_s: int = 20) -> dict:
    inicio = time.perf_counter()
    fila: dict = {
        "modelo": modelo,
        "ok": False,
        "status": "error",
        "ms": 0,
        "skus": 0,
        "contenedor": "",
    }
    try:
        from google import genai
        from google.genai import types

        try:
            cliente = genai.Client(
                api_key=ocr._clave_gemini(),
                http_options={"timeout": timeout_s * 1000},
            )
        except TypeError:
            cliente = genai.Client(api_key=ocr._clave_gemini())
        parte = types.Part.from_bytes(data=jpeg, mime_type="image/jpeg")
        config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json")
        resp = cliente.models.generate_content(
            model=modelo,
            contents=[ocr.VISION_PROMPT, parte],
            config=config,
        )
        parsed = ocr._parsear_json_modelo(getattr(resp, "text", "") or "")
        fila["ms"] = ocr._ms(inicio)
        if not parsed:
            fila["status"] = "no_json"
            return fila
        invent = ocr.inventario_desde_vision(parsed)
        meta = ocr.extraer_meta_validacion(parsed)
        chequeo = ocr.evaluar_completitud(invent, meta)
        fila.update(
            {
                "ok": True,
                "status": "ok",
                "skus": len(invent.get("skus") or []),
                "contenedor": invent.get("contenedor") or "",
                "completeness": chequeo.get("estado"),
                "suma": chequeo.get("suma_cajas"),
                "declared_cases": chequeo.get("declared_cases"),
            }
        )
        return fila
    except Exception as exc:
        fila["ms"] = ocr._ms(inicio)
        fila["status"] = _clasificar_error(exc)
        fila["error"] = f"{type(exc).__name__}"
        return fila


def _medir_tesseract(path: Path, formato: str) -> dict:
    data = path.read_bytes()
    inicio = time.perf_counter()
    if not ocr.tesseract_disponible():
        return {"disponible": False, "ms": 0, "skus": 0}
    texto = ocr.extraer_texto(data)
    invent = ocr.parsear_texto(texto, formato=formato) if texto.strip() else {"skus": []}
    return {
        "disponible": True,
        "ms": ocr._ms(inicio),
        "skus": len(invent.get("skus") or []),
        "contenedor": invent.get("contenedor") or "",
    }


def _pipeline(path: Path, formato: str) -> dict:
    data = path.read_bytes()
    inicio = time.perf_counter()
    invent = ocr.procesar_documento(data, formato=formato)
    total = ocr._ms(inicio)
    skus = invent.get("skus") or []
    return {
        "ms": total,
        "skus": len(skus),
        "contenedor": invent.get("contenedor") or "",
        "suma": sum(int(x.get("cantidad_esperada") or 0) for x in skus),
        "primer_sku": skus[0]["sku"] if skus else "",
    }


def _resumen(valores: list[int]) -> dict:
    if not valores:
        return {"n": 0}
    orden = sorted(valores)
    mid = len(orden) // 2
    mediana = orden[mid] if len(orden) % 2 else int((orden[mid - 1] + orden[mid]) / 2)
    return {
        "n": len(orden),
        "min": min(orden),
        "avg": int(statistics.mean(orden)),
        "mediana": mediana,
        "max": max(orden),
    }


def main() -> None:
    print("[AL BENCH] tesseract local", flush=True)
    tess = {}
    for clave, path, fmt in HOJAS:
        if not path.is_file():
            print(f"[AL BENCH] sin fixture {clave}", flush=True)
            continue
        tess[clave] = _medir_tesseract(path, fmt)
        print(f"[AL BENCH] tesseract {clave} {tess[clave]}", flush=True)

    if not ocr._clave_gemini():
        print("[AL BENCH] sin GEMINI_API_KEY", flush=True)
        return

    probes: list[dict] = []
    po8 = HOJAS[0][1]
    if po8.is_file():
        jpeg = ocr._imagen_a_jpeg_bytes(po8.read_bytes())
        for modelo in MODELOS_PROBE:
            print(f"[AL BENCH] probe {modelo}", flush=True)
            fila = _probar_modelo(jpeg, modelo)
            fila["hoja"] = "po8"
            probes.append(fila)
            print(f"[AL BENCH] probe {fila}", flush=True)
            time.sleep(PAUSA_S)

    pipelines: list[dict] = []
    plan = (("po8", 3, "A"), ("po16", 2, "A"), ("inbound", 2, "B"))
    for clave, n, fmt in plan:
        path = next(p for k, p, _ in HOJAS if k == clave)
        if not path.is_file():
            continue
        for i in range(n):
            print(f"[AL BENCH] pipeline {clave} #{i+1}", flush=True)
            t0 = time.perf_counter()
            try:
                fila = _pipeline(path, fmt)
                fila.update({"hoja": clave, "run": i + 1, "ok": True, "status": "ok"})
            except Exception as exc:
                fila = {
                    "hoja": clave,
                    "run": i + 1,
                    "ok": False,
                    "status": _clasificar_error(exc),
                    "ms": ocr._ms(t0),
                    "skus": 0,
                }
            pipelines.append(fila)
            print(f"[AL BENCH] pipeline {fila}", flush=True)
            time.sleep(PAUSA_S)

    reporte = {
        "tesseract": tess,
        "probes": probes,
        "pipelines": pipelines,
        "resumen_pipeline_ms": {
            clave: _resumen([r["ms"] for r in pipelines if r.get("hoja") == clave and r.get("ok")])
            for clave, _, _ in HOJAS
        },
    }
    salida = ROOT / "tests" / "fixtures" / "ocr" / "_bench_latencia.json"
    salida.write_text(json.dumps(reporte, indent=2), encoding="utf-8")
    print("[AL BENCH] escrito", salida, flush=True)
    print(json.dumps(reporte["resumen_pipeline_ms"], indent=2), flush=True)


if __name__ == "__main__":
    main()
