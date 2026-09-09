"""OCR e interpretación de Purchase Order Report e Inbound Receiving Report."""

from __future__ import annotations

import base64
import gc
import io
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from shutil import which
from typing import Any

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

logger = logging.getLogger(__name__)

try:
    import pytesseract
except Exception as exc:
    pytesseract = None
    logger.info("pytesseract no disponible (%s). Se usará visión (Gemini/OpenAI).", exc)


def _configurar_tesseract() -> None:
    """En Windows busca Tesseract local; en Linux/Render no fuerza esa ruta."""
    if pytesseract is None:
        return
    cmd = os.environ.get("TESSERACT_CMD", "").strip()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
        return
    if sys.platform.startswith("win"):
        windows = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        if windows.is_file():
            pytesseract.pytesseract.tesseract_cmd = str(windows)


def tesseract_disponible() -> bool:
    if pytesseract is None:
        return False
    try:
        cmd = getattr(pytesseract.pytesseract, "tesseract_cmd", "") or ""
        if cmd and Path(cmd).is_file():
            return True
        if not sys.platform.startswith("win"):
            return which("tesseract") is not None
    except Exception:
        return False
    return False


_configurar_tesseract()

CONTENEDOR_RE = re.compile(r"\b([A-Z]{4}\s?\d{6,7})\b")
SKU_FLEX_RE = re.compile(
    r"\b([A-Z]?\d{4,12}(?:-[A-Z0-9]{1,4})?|[A-Z]{1,3}\d{4,12}(?:-[A-Z0-9]{1,4})?"
    r"|[A-Z0-9]{5,16}(?:-[A-Z0-9]{1,4})?)\b",
    re.I,
)
INT_RE = re.compile(r"\b(\d{1,6})\b")
ENCABEZADO_TABLA_RE = re.compile(
    r"\b(product|description|pallet\s*qty|qty|quantity)\b",
    re.I,
)
PIE_TABLA_RE = re.compile(
    r"\b(notes?|comments?|received by|signature|handwrit|total\s+(qty|quantity|cases)"
    r"|page\s+\d+|gracias|thank you)\b",
    re.I,
)


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _sku_item(sku: str, qty: int, producto: str = "") -> dict[str, Any]:
    codigo = _sanear_sku(sku)
    return {
        "sku": codigo,
        "producto": (producto or codigo).strip(),
        "cantidad_esperada": max(int(qty), 0),
        "contador": 0,
        "estado": "pendiente",
        "discrepancia": 0,
        "cajas_por_paleta": 0,
    }


def _sanear_sku(token: str) -> str:
    """Quita espacios y corrige O/0, I/l/1 típicos del OCR."""
    crudo = re.sub(r"\s+", "", str(token).upper())
    limpio: list[str] = []
    for i, ch in enumerate(crudo):
        prev_d = i > 0 and crudo[i - 1].isdigit()
        next_d = i + 1 < len(crudo) and crudo[i + 1].isdigit()
        if ch in "OQ" and (prev_d or next_d):
            limpio.append("0")
        elif ch in "IL|" and (prev_d or next_d):
            limpio.append("1")
        elif ch == "S" and prev_d and next_d:
            limpio.append("5")
        elif ch == "B" and prev_d and next_d:
            limpio.append("8")
        else:
            limpio.append(ch)
    return "".join(limpio)


def _pil_a_cv(gray: Image.Image):
    import numpy as np

    return np.array(gray)


def _cv_a_pil(arr) -> Image.Image:
    return Image.fromarray(arr)


def _deskew_cv(gray):
    import cv2
    import numpy as np

    invertida = cv2.bitwise_not(gray)
    coords = np.column_stack(np.where(invertida > 0))
    if len(coords) < 80:
        return gray
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    if abs(angle) < 0.4 or abs(angle) > 18:
        return gray
    h, w = gray.shape[:2]
    matriz = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    return cv2.warpAffine(
        gray,
        matriz,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _liberar_memoria_ocr(*objetos: Any) -> None:
    for obj in objetos:
        try:
            if obj is not None and hasattr(obj, "close"):
                obj.close()
        except Exception:
            pass
    gc.collect()


def preprocess_image(data: bytes) -> Image.Image:
    """Deskew, grises, contraste y umbral adaptativo para fotos de PO."""
    image = Image.open(io.BytesIO(data))
    image = ImageOps.exif_transpose(image)
    if image.mode != "RGB":
        rgb = image.convert("RGB")
        image.close()
        image = rgb
    gray = ImageOps.grayscale(image)
    image.close()
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = ImageEnhance.Contrast(gray).enhance(2.1)

    try:
        import cv2

        matriz = _pil_a_cv(gray)
        matriz = cv2.fastNlMeansDenoising(matriz, None, 18, 7, 21)
        matriz = _deskew_cv(matriz)
        matriz = cv2.adaptiveThreshold(
            matriz,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            12,
        )
        return _cv_a_pil(matriz)
    except Exception as exc:
        logger.warning("Preprocesado OpenCV no disponible (%s). Uso PIL.", exc)
        gray = ImageEnhance.Sharpness(gray).enhance(1.5)
        return gray.filter(ImageFilter.SHARPEN)


def recortar_roi_tabla(imagen: Image.Image) -> Image.Image:
    """Recorta encabezado y pie; deja el bloque central Product / Description / QTY."""
    ancho, alto = imagen.size
    izq = int(ancho * 0.03)
    der = int(ancho * 0.97)
    top = int(alto * 0.18)
    bottom = int(alto * 0.86)
    if bottom <= top + 40:
        return imagen
    return imagen.crop((izq, top, der, bottom))


def recortar_columna_codigos_barra(imagen: Image.Image) -> Image.Image:
    """Elimina la franja izquierda de códigos de barras que Tesseract lee como palos."""
    ancho, alto = imagen.size
    if ancho < 80:
        return imagen
    izq = int(ancho * 0.18)
    der = int(ancho * 0.99)
    if der <= izq + 40:
        return imagen
    return imagen.crop((izq, 0, der, alto))


def _ocr_imagen(imagen: Image.Image) -> str:
    if pytesseract is None:
        return ""
    config = "--oem 3 --psm 6"
    try:
        return pytesseract.image_to_string(imagen, lang="eng+spa", config=config) or ""
    except Exception as exc:
        if type(exc).__name__ == "TesseractNotFoundError":
            logger.info("Tesseract no está instalado. Se omite el OCR local.")
            return ""
        logger.warning("OCR eng+spa falló (%s). Reintento en inglés.", exc)
        try:
            return pytesseract.image_to_string(imagen, lang="eng", config=config) or ""
        except Exception as exc2:
            logger.info("No se pudo leer la imagen con Tesseract: %s", exc2)
            return ""


def extraer_texto(data: bytes) -> str:
    """Tesseract: página (contenedor) + tabla sin columna de códigos de barras."""
    if not tesseract_disponible():
        return ""
    imagen = preprocess_image(data)
    try:
        texto_completo = _ocr_imagen(imagen)
        tabla = recortar_columna_codigos_barra(recortar_roi_tabla(imagen))
        texto_roi = _ocr_imagen(tabla)
        partes = [bloque.strip() for bloque in (texto_completo, texto_roi) if bloque.strip()]
        return "\n".join(partes)
    finally:
        _liberar_memoria_ocr(imagen)


def _imagen_a_jpeg_b64(data: bytes) -> str:
    image = Image.open(io.BytesIO(data))
    try:
        image = ImageOps.exif_transpose(image)
        if image.mode != "RGB":
            image = image.convert("RGB")
        w, h = image.size
        max_lado = 1280
        scale = min(1.0, max_lado / max(w, h, 1))
        if scale < 1:
            image = image.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                getattr(Image, "Resampling", Image).LANCZOS,
            )
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=70, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    finally:
        image.close()


_easy_reader = None


def extraer_texto_easyocr(imagen: Image.Image) -> str:
    """OCR local con redes neuronales (tablas y fotos de baja resolución)."""
    global _easy_reader
    try:
        import easyocr
        import numpy as np
    except ImportError:
        logger.info("EasyOCR no instalado. Opcional: pip install easyocr")
        return ""
    try:
        if _easy_reader is None:
            print("[AL OCR] Cargando EasyOCR (en/es)…", flush=True)
            _easy_reader = easyocr.Reader(["en", "es"], gpu=False, verbose=False)
        resultados = _easy_reader.readtext(np.array(imagen.convert("RGB")))
        lineas = [str(item[1]).strip() for item in resultados if item and item[1]]
        texto = "\n".join(lineas)
        if texto:
            print(f"[AL OCR] EasyOCR devolvió {len(lineas)} fragmentos.", flush=True)
        return texto
    except Exception as exc:
        logger.error("EasyOCR falló: %s", exc)
        print(f"[AL OCR] EasyOCR falló: {exc}", flush=True)
        return ""


VISION_PROMPT = (
    "You extract the product table from a warehouse Purchase Order Report or Inbound Receiving Report photo. "
    "Return ONLY valid JSON with this exact shape: "
    '{"contenedor":"","skus":[{"sku":"","descripcion":"","cajas_esperadas":0}]}. '
    "sku is the Product / SKU code (example P0845170-1). "
    "descripcion is the Description column. "
    "cajas_esperadas is the QTY / Total Cases / Exp Eaches integer (boxes expected). "
    "contenedor is Other Reference Number or Trailer if visible. "
    "Read every data row of the table. Ignore barcodes, headers, handwritten notes and footer totals."
)


def _parsear_json_modelo(crudo: str) -> dict[str, Any] | None:
    if not crudo:
        return None
    texto = crudo.strip()
    if texto.startswith("```"):
        texto = re.sub(r"^```(?:json)?", "", texto).removesuffix("```").strip()
    match = re.search(r"\{.*\}", texto, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _clave_vision(*alternativas: str) -> str:
    """Lee la clave de visión desde API_KEY o, si no hay, desde Gemini/OpenAI."""
    valor = os.environ.get("API_KEY", "").strip()
    if valor:
        return valor
    for nombre in alternativas:
        valor = os.environ.get(nombre, "").strip()
        if valor:
            return valor
    return ""


def extraer_json_openai(data: bytes) -> dict[str, Any] | None:
    api_key = _clave_vision("OPENAI_API_KEY")
    if not api_key:
        return None
    cuerpo = {
        "model": os.environ.get("OPENAI_VISION_MODEL", "gpt-4o-mini"),
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{_imagen_a_jpeg_b64(data)}"},
                    },
                ],
            }
        ],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        crudo = payload["choices"][0]["message"]["content"]
        print("[AL OCR] Visión OpenAI respondió.", flush=True)
        return _parsear_json_modelo(crudo)
    except Exception as exc:
        logger.error("OpenAI Vision falló: %s", exc)
        print(f"[AL OCR] OpenAI Vision falló: {exc}", flush=True)
        return None


def extraer_json_gemini(data: bytes) -> dict[str, Any] | None:
    api_key = _clave_vision("GEMINI_API_KEY")
    if not api_key:
        return None
    modelo = os.environ.get("GEMINI_VISION_MODEL", "gemini-2.0-flash")
    cuerpo = {
        "contents": [
            {
                "parts": [
                    {"text": VISION_PROMPT},
                    {"inline_data": {"mime_type": "image/jpeg", "data": _imagen_a_jpeg_b64(data)}},
                ]
            }
        ],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        f"?key={api_key}"
    )
    req = urllib.request.Request(
        url,
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        crudo = payload["candidates"][0]["content"]["parts"][0]["text"]
        print("[AL OCR] Visión Gemini respondió.", flush=True)
        return _parsear_json_modelo(crudo)
    except Exception as exc:
        logger.error("Gemini Vision falló: %s", exc)
        print(f"[AL OCR] Gemini Vision falló: {exc}", flush=True)
        return None


def inventario_desde_vision(payload: dict[str, Any], formato: str | None = None) -> dict[str, Any]:
    skus: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for fila in payload.get("skus") or payload.get("items") or []:
        if not isinstance(fila, dict):
            continue
        sku = _sanear_sku(str(fila.get("sku") or fila.get("SKU") or fila.get("Product") or ""))
        if not sku or _es_ruido_sku(sku) or sku in vistos:
            continue
        qty_raw = (
            fila.get("cajas_esperadas")
            or fila.get("qty")
            or fila.get("QTY")
            or fila.get("cantidad")
            or fila.get("cantidad_esperada")
            or 0
        )
        try:
            qty = int(float(str(qty_raw).replace(",", "") or 0))
        except ValueError:
            qty = 0
        desc = str(fila.get("descripcion") or fila.get("Description") or fila.get("description") or sku)
        vistos.add(sku)
        skus.append(_sku_item(sku, qty, desc[:80]))
    contenedor = str(payload.get("contenedor") or payload.get("trailer") or "").strip()
    return {
        "contenedor": re.sub(r"\s+", "", contenedor.upper()),
        "formato": (formato or "A").upper(),
        "fecha_carga": _ahora(),
        "skus": skus,
    }


def procesar_documento(data: bytes, formato: str | None = None) -> dict[str, Any]:
    """Visión (Gemini / OpenAI) lee la hoja; Tesseract/EasyOCR solo si no hay API o falla."""
    imagen = None
    tabla = None
    try:
        print("[AL OCR] Enviando hoja a visión (Gemini / OpenAI)…", flush=True)
        vision = extraer_json_gemini(data) or extraer_json_openai(data)
        if vision:
            invent_v = inventario_desde_vision(vision, formato=formato)
            if invent_v.get("skus"):
                return invent_v
            print("[AL OCR] Visión respondió sin SKUs útiles.", flush=True)
        else:
            print("[AL OCR] Visión no disponible o falló. Respaldo local…", flush=True)

        texto = extraer_texto(data)
        inventario = parsear_texto(texto, formato=formato) if texto.strip() else {
            "contenedor": "",
            "formato": (formato or "A").upper(),
            "fecha_carga": _ahora(),
            "skus": [],
        }
        if inventario.get("skus"):
            return inventario

        print("[AL OCR] Tesseract no halló SKUs. Probando EasyOCR…", flush=True)
        imagen = preprocess_image(data)
        tabla = recortar_columna_codigos_barra(recortar_roi_tabla(imagen))
        texto_easy = extraer_texto_easyocr(tabla) or extraer_texto_easyocr(imagen)
        if texto_easy.strip():
            inventario = parsear_texto(f"{texto}\n{texto_easy}", formato=formato)
            if inventario.get("skus"):
                return inventario

        return inventario
    finally:
        _liberar_memoria_ocr(tabla, imagen)
        data = b""


def detectar_formato(texto: str) -> str:
    upper = texto.upper()
    if "INBOUND RECEIVING" in upper or "TRAILER" in upper or "EXP EACHES" in upper:
        return "B"
    if "PURCHASE ORDER" in upper or "OTHER REFERENCE" in upper or "PALLET QTY" in upper:
        return "A"
    if "TRAILER" in upper and "SKU" in upper:
        return "B"
    return "A"


def _limpiar_lineas(texto: str) -> list[str]:
    lineas = []
    for raw in texto.splitlines():
        linea = re.sub(r"[ \t]+", " ", raw).strip()
        if linea:
            lineas.append(linea)
    return lineas


def _zona_tabla(texto: str) -> str:
    """Descarta encabezado y notas del pie; conserva filas Product / QTY."""
    lineas = _limpiar_lineas(texto)
    if not lineas:
        return ""
    inicio = 0
    fin = len(lineas)
    for i, linea in enumerate(lineas):
        hits = len(ENCABEZADO_TABLA_RE.findall(linea))
        if hits >= 2 or re.search(r"\bproduct\b.*\bqty\b", linea, re.I):
            inicio = i + 1
            break
    for i in range(inicio, len(lineas)):
        if PIE_TABLA_RE.search(lineas[i]):
            fin = i
            break
    bloque = lineas[inicio:fin] if inicio else lineas[:fin]
    if not bloque:
        bloque = lineas[2:-2] if len(lineas) > 6 else lineas
    return "\n".join(bloque)


def _buscar_contenedor(texto: str, patrones: list[str]) -> str:
    upper = texto.upper()
    for patron in patrones:
        match = re.search(patron + r"[:\s]+([A-Z0-9\- ]{5,20})", upper)
        if match:
            candidato = re.sub(r"\s+", "", match.group(1))
            iso = CONTENEDOR_RE.search(candidato)
            return iso.group(1).replace(" ", "") if iso else candidato
    iso = CONTENEDOR_RE.search(upper)
    return iso.group(1).replace(" ", "") if iso else ""


def _es_ruido_sku(token: str) -> bool:
    ruido = {
        "PURCHASE",
        "ORDER",
        "REPORT",
        "INBOUND",
        "RECEIVING",
        "TRAILER",
        "PRODUCT",
        "OTHER",
        "REFERENCE",
        "NUMBER",
        "TOTAL",
        "CASES",
        "EACHES",
        "QTY",
        "SKU",
        "PAGE",
        "DATE",
        "PALLET",
        "DESCRIPTION",
        "DESC",
    }
    limpio = _sanear_sku(token).replace("-", "")
    if limpio in ruido:
        return True
    if limpio.isalpha() and len(limpio) < 5:
        return True
    if len(limpio) < 5:
        return True
    return False


def _qty_de_linea(linea: str) -> int | None:
    nums = [int(n) for n in INT_RE.findall(linea) if 0 < int(n) < 100000]
    if not nums:
        return None
    return nums[-1]


def _parsear_fila_producto(linea: str) -> tuple[str, str, int] | None:
    """Product (P0845170-1) + Description + QTY al final."""
    etiqueta = re.search(
        r"(?:product|sku|item|codigo|código)[:\s#]*([A-Z0-9][A-Z0-9\-]{4,18})",
        linea,
        re.I,
    )
    if etiqueta:
        sku = _sanear_sku(etiqueta.group(1))
        resto = linea[etiqueta.end() :]
        qty = _qty_de_linea(resto) or _qty_de_linea(linea)
        if qty is None or _es_ruido_sku(sku):
            return None
        desc = re.sub(r"\b\d+\b", " ", resto).strip(" -|")
        return sku, desc[:80], qty

    tokens = SKU_FLEX_RE.findall(linea)
    qty = _qty_de_linea(linea)
    if not tokens or qty is None:
        return None
    sku = _sanear_sku(tokens[0])
    if _es_ruido_sku(sku):
        return None
    desc = linea
    desc = re.sub(re.escape(tokens[0]), " ", desc, flags=re.I)
    desc = re.sub(r"\b\d+\b", " ", desc)
    desc = re.sub(r"\s+", " ", desc).strip(" -|")
    return sku, desc[:80], qty


def parsear_formato_a(texto: str) -> dict[str, Any]:
    """Purchase Order Report: Other Reference Number, Product, Description, QTY."""
    contenedor = _buscar_contenedor(
        texto,
        [r"OTHER REFERENCE NUMBER", r"OTHER REF(?:ERENCE)?(?: NO\.?| NUMBER)?", r"CONTAINER"],
    )
    zona = _zona_tabla(texto)
    skus: list[dict[str, Any]] = []
    vistos: set[str] = set()

    for linea in _limpiar_lineas(zona):
        if ENCABEZADO_TABLA_RE.fullmatch(linea.replace(" ", "")):
            continue
        fila = _parsear_fila_producto(linea)
        if not fila:
            continue
        sku, descripcion, qty = fila
        if sku in vistos:
            continue
        vistos.add(sku)
        skus.append(_sku_item(sku, qty, descripcion))

    if not skus:
        skus = _fallback_pares(zona or texto)

    return {
        "contenedor": contenedor,
        "formato": "A",
        "fecha_carga": _ahora(),
        "skus": skus,
    }


def parsear_formato_b(texto: str) -> dict[str, Any]:
    """Inbound Receiving Report: Trailer, SKU, Exp Eaches / Total Cases."""
    contenedor = _buscar_contenedor(texto, [r"TRAILER", r"CONTAINER", r"CONTENEDOR"])
    zona = _zona_tabla(texto)
    skus: list[dict[str, Any]] = []
    vistos: set[str] = set()

    for linea in _limpiar_lineas(zona):
        fila = _parsear_fila_producto(linea)
        if not fila:
            continue
        sku, descripcion, qty = fila
        if sku in vistos:
            continue
        vistos.add(sku)
        skus.append(_sku_item(sku, qty, descripcion))

    if not skus:
        skus = _fallback_pares(zona or texto)

    return {
        "contenedor": contenedor,
        "formato": "B",
        "fecha_carga": _ahora(),
        "skus": skus,
    }


def _fallback_pares(texto: str) -> list[dict[str, Any]]:
    """Cualquier código alfanumérico de Product + último entero como QTY."""
    skus: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for linea in _limpiar_lineas(texto):
        tokens = [_sanear_sku(t) for t in SKU_FLEX_RE.findall(linea)]
        qty = _qty_de_linea(linea)
        if not tokens or qty is None:
            continue
        sku = tokens[0]
        if _es_ruido_sku(sku) or sku in vistos:
            continue
        vistos.add(sku)
        skus.append(_sku_item(sku, qty))
    return skus


def parsear_texto(texto: str, formato: str | None = None) -> dict[str, Any]:
    fmt = (formato or detectar_formato(texto)).upper()
    if fmt == "B":
        return parsear_formato_b(texto)
    return parsear_formato_a(texto)


def inventario_demo() -> dict[str, Any]:
    """Contenedor de prueba para validar voz y sufijos sin documento."""
    items = [
        ("88771245", "Filtro hidráulico A", 48),
        ("55330045", "Banda transportadora", 36),
        ("88771980", "Filtro hidráulico B", 24),
        ("12000080", "Aceite 5W SAE", 60),
        ("33664890", "Rodamiento industrial", 12),
        ("99110022", "Kit empaques", 18),
        ("77440015", "Cadena montacargas", 8),
        ("44116078", "Lámpara LED bahía", 42),
    ]
    return {
        "contenedor": "MSCU4588123",
        "formato": "DEMO",
        "fecha_carga": _ahora(),
        "skus": [_sku_item(sku, qty, nombre) for sku, nombre, qty in items],
    }


def mensaje_carga(inventario: dict[str, Any]) -> str:
    skus = inventario.get("skus") or []
    total_cajas = sum(int(item.get("cantidad_esperada") or 0) for item in skus)
    contenedor = inventario.get("contenedor") or "SIN-ID"
    return (
        f"Contenedor {contenedor} cargado con {len(skus)} SKUs "
        f"y {total_cajas} cajas totales. Listo para iniciar."
    )
