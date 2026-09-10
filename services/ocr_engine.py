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
_ERRORES_VISION: list[str] = []


def cargar_dotenv() -> None:
    """Carga .env local sin pisar variables ya definidas (Render, sistema)."""
    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)
    except Exception:
        pass
    raiz = Path(__file__).resolve().parent.parent
    for candidato in (Path.cwd() / ".env", raiz / ".env"):
        if not candidato.is_file():
            continue
        try:
            for linea in candidato.read_text(encoding="utf-8").splitlines():
                texto = linea.strip()
                if not texto or texto.startswith("#") or "=" not in texto:
                    continue
                clave, _, valor = texto.partition("=")
                clave = clave.strip()
                valor = valor.strip().strip("'").strip('"')
                if clave and clave not in os.environ:
                    os.environ[clave] = valor
        except Exception as exc:
            print(f"[AL OCR] No se pudo leer {candidato}: {exc}", flush=True)


def _enmascarar_clave(valor: str) -> str:
    limpio = (valor or "").strip()
    if len(limpio) < 8:
        return "(corta)"
    return f"{limpio[:4]}…{limpio[-4:]}"


cargar_dotenv()

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


def _abrir_hoja(data: bytes) -> Image.Image:
    """Abre la foto, aplica EXIF y pone la hoja apaisada (Inbound es landscape)."""
    image = Image.open(io.BytesIO(data))
    image = ImageOps.exif_transpose(image)
    if image.mode != "RGB":
        rgb = image.convert("RGB")
        image.close()
        image = rgb
    ancho, alto = image.size
    if alto > ancho:
        rotada = image.rotate(90, expand=True)
        image.close()
        return rotada
    return image


def preprocess_image(data: bytes) -> Image.Image:
    """Deskew, grises, contraste y umbral adaptativo para fotos de PO."""
    image = _abrir_hoja(data)
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


def _imagen_a_jpeg_bytes(data: bytes) -> bytes:
    """Orienta la hoja (retrato → apaisado) y deja JPEG listo para visión."""
    image = _abrir_hoja(data)
    try:
        w, h = image.size
        max_lado = 1600
        scale = min(1.0, max_lado / max(w, h, 1))
        if scale < 1:
            image = image.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                getattr(Image, "Resampling", Image).LANCZOS,
            )
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=85, optimize=True)
        return buf.getvalue()
    finally:
        image.close()


def _imagen_a_jpeg_b64(data: bytes) -> str:
    return base64.b64encode(_imagen_a_jpeg_bytes(data)).decode("ascii")


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
    "You read a warehouse Inbound Receiving Report (or Purchase Order Report). "
    "The page is landscape: title at the top, table below. If text looks sideways, rotate it in your head first. "
    "Return ONLY JSON, no markdown and no extra prose. "
    'Exact shape: {"contenedor":"KKFU7868019","skus":[{"sku":"1015223027","descripcion":"HUSKY 52-13 MATTE BLK COMBO","esperado":54}]} '
    "contenedor = Trailer value (example KKFU7868019), digits/letters only. "
    "COLUMN MAPPING FOR INBOUND RECEIVING REPORT PRODUCT TABLE: "
    'sku = exact digits under the table column headed "SKU" on each product row. Example: 1015223027. '
    "Never use ASN, Trailer, Vendor/DC, BOL, Dock Door, PO, or header counts as sku. "
    "ASN example 14881711 is NOT a sku. Trailer example KKFU7868019 is NOT a sku. "
    'esperado = integer under "Exp Eaches" on that same product row. If missing, use "Total Cases" on that row. Example: 54. '
    "Never use Full Pallets, Partial Pallets, Rec Eaches, or header totals. Sample sheet: esperado is 54, not Full Pallets 27. "
    "descripcion = SKU Description on that same product row. "
    "One object per product data row. JSON only."
)


def _parsear_json_modelo(crudo: str) -> dict[str, Any] | None:
    if not crudo:
        return None
    texto = crudo.strip()
    if texto.startswith("```"):
        texto = re.sub(r"^```(?:json)?", "", texto).removesuffix("```").strip()
    data: Any = None
    if texto.startswith("["):
        match = re.search(r"\[.*\]", texto, re.S)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                data = None
    if data is None:
        match = re.search(r"\{.*\}", texto, re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if isinstance(data, list):
        return {"skus": data}
    if isinstance(data, dict):
        if isinstance(data.get("skus"), list):
            return data
        if data.get("sku") or data.get("esperado") is not None:
            return {"skus": [data]}
        return data
    return None


def _clave_gemini() -> str:
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY")
    return (gemini_key or "").strip()


def _clave_openai() -> str:
    oai = os.environ.get("OPENAI_API_KEY", "").strip()
    if oai:
        return oai
    api = os.environ.get("API_KEY", "").strip()
    return api if api.startswith("sk-") else ""


def _hay_clave_vision() -> bool:
    return bool(_clave_gemini() or _clave_openai())


def _registrar_error_vision(msg: str) -> None:
    texto = (msg or "").strip()
    if texto:
        _ERRORES_VISION.append(texto)
        print(f"[AL OCR] {texto}", flush=True)


def _detalle_error(exc: Exception) -> str:
    partes = [f"{type(exc).__name__}: {exc}"]
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            partes.append(f"HTTP {resp.status_code} {str(resp.text)[:800]}")
        except Exception:
            pass
    if isinstance(exc, urllib.error.HTTPError):
        try:
            partes.append(exc.read().decode("utf-8", errors="replace")[:800])
        except Exception:
            pass
    return " | ".join(partes)


def _post_json(url: str, cuerpo: dict[str, Any], headers: dict[str, str], timeout: int = 60) -> dict[str, Any]:
    try:
        import requests

        resp = requests.post(url, json=cuerpo, headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:800]}")
        return resp.json()
    except ImportError:
        req = urllib.request.Request(
            url,
            data=json.dumps(cuerpo).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            cuerpo_err = exc.read().decode("utf-8", errors="replace")[:800]
            raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {cuerpo_err}") from exc


def extraer_json_openai(data: bytes) -> dict[str, Any] | None:
    api_key = _clave_openai()
    if not api_key:
        return None
    modelo = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o-mini")
    cuerpo = {
        "model": modelo,
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
    try:
        payload = _post_json(
            "https://api.openai.com/v1/chat/completions",
            cuerpo,
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        crudo = payload["choices"][0]["message"]["content"]
        print("[AL OCR] Visión OpenAI respondió.", flush=True)
        return _parsear_json_modelo(crudo)
    except Exception as exc:
        _registrar_error_vision(f"OpenAI Vision falló: {_detalle_error(exc)}")
        return None


_MODELOS_GEMINI_CACHE: list[str] | None = None
_MODELOS_FLASH_PRIORIDAD = (
    "gemini-flash-latest",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
)


def _get_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        import requests

        resp = requests.get(url, headers=headers or {}, timeout=20)
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:800]}")
        return resp.json()
    except ImportError:
        req = urllib.request.Request(url, headers=headers or {}, method="GET")
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))


def _listar_modelos_gemini(api_key: str) -> list[str]:
    nombres: list[str] = []
    for version in ("v1beta", "v1"):
        url = f"https://generativelanguage.googleapis.com/{version}/models?key={api_key}"
        try:
            payload = _get_json(url, {"x-goog-api-key": api_key})
            for modelo in payload.get("models") or []:
                metodos = modelo.get("supportedGenerationMethods") or []
                if metodos and "generateContent" not in metodos:
                    continue
                corto = str(modelo.get("name") or "").split("/")[-1]
                if not corto or corto in nombres:
                    continue
                if any(x in corto.lower() for x in ("embed", "imagen", "tts", "audio", "robotics")):
                    continue
                nombres.append(corto)
            if nombres:
                break
        except Exception as err:
            print(f"[AL OCR] ListModels {version}: {_detalle_error(err)}", flush=True)
            continue
    return nombres


def _modelos_gemini_a_usar(api_key: str) -> list[str]:
    global _MODELOS_GEMINI_CACHE
    preferido = os.getenv("GEMINI_VISION_MODEL", "").strip()
    if _MODELOS_GEMINI_CACHE:
        modelos = list(_MODELOS_GEMINI_CACHE)
        if preferido and preferido not in modelos:
            modelos.insert(0, preferido)
        return modelos
    encontrados = _listar_modelos_gemini(api_key)
    flash = [
        m
        for m in encontrados
        if "flash" in m.lower()
        and not any(x in m.lower() for x in ("image", "tts", "live", "audio", "embed"))
    ]
    ordenados: list[str] = []
    if preferido:
        ordenados.append(preferido)
    for nombre in _MODELOS_FLASH_PRIORIDAD:
        if nombre in flash and nombre not in ordenados:
            ordenados.append(nombre)
    for nombre in flash:
        if nombre not in ordenados:
            ordenados.append(nombre)
    if any(n == "gemini-flash-latest" or n.startswith("gemini-3") for n in ordenados):
        ordenados = [n for n in ordenados if not n.startswith("gemini-2.")]
    if not ordenados:
        ordenados = [n for n in _MODELOS_FLASH_PRIORIDAD if n != "gemini-1.5-flash"]
        if preferido and preferido not in ordenados:
            ordenados.insert(0, preferido)
        print("[AL OCR] ListModels vacío; se probarán modelos Flash actuales.", flush=True)
    else:
        print(f"[AL OCR] Modelos Gemini a usar: {', '.join(ordenados[:5])}", flush=True)
    _MODELOS_GEMINI_CACHE = ordenados
    return ordenados


def extraer_json_gemini(data: bytes) -> dict[str, Any] | None:
    api_key = _clave_gemini()
    if not api_key:
        return None
    modelos = _modelos_gemini_a_usar(api_key)
    jpeg = _imagen_a_jpeg_bytes(data)
    parsed = extraer_json_gemini_sdk(jpeg, api_key, modelos)
    if parsed:
        return parsed
    imagen_b64 = base64.b64encode(jpeg).decode("ascii")
    ultimo_error = ""
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    for modelo in modelos[:3]:
        cuerpo = {
            "contents": [
                {
                    "parts": [
                        {"text": VISION_PROMPT},
                        {"inline_data": {"mime_type": "image/jpeg", "data": imagen_b64}},
                    ]
                }
            ],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        for version in ("v1beta", "v1"):
            url = (
                f"https://generativelanguage.googleapis.com/{version}/models/{modelo}:generateContent"
                f"?key={api_key}"
            )
            try:
                payload = _post_json(url, cuerpo, headers)
                if payload.get("error"):
                    raise RuntimeError(payload["error"])
                candidatos = payload.get("candidates") or []
                if not candidatos:
                    raise RuntimeError(f"sin candidates: {json.dumps(payload)[:500]}")
                crudo = candidatos[0]["content"]["parts"][0]["text"]
                parsed = _parsear_json_modelo(crudo)
                if parsed:
                    print(f"[AL OCR] Visión Gemini respondió ({modelo}).", flush=True)
                    return parsed
                raise RuntimeError("respuesta sin JSON de SKUs")
            except Exception as err:
                ultimo_error = f"Gemini ({modelo}/{version}) falló: {_detalle_error(err)}"
                print(f"[AL OCR] {ultimo_error}", flush=True)
                if "404" not in str(err).lower() and "not found" not in str(err).lower():
                    break
    if ultimo_error:
        _registrar_error_vision(ultimo_error)
    return None


def extraer_json_gemini_sdk(data: bytes, api_key: str, modelos: list[str]) -> dict[str, Any] | None:
    try:
        from google import genai
        from google.genai import types
    except Exception:
        return None
    try:
        cliente = genai.Client(api_key=api_key)
        jpeg = data if data[:2] == b"\xff\xd8" else _imagen_a_jpeg_bytes(data)
        parte = types.Part.from_bytes(data=jpeg, mime_type="image/jpeg")
        config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json")
        for modelo in modelos[:2]:
            try:
                resp = cliente.models.generate_content(
                    model=modelo,
                    contents=[VISION_PROMPT, parte],
                    config=config,
                )
                parsed = _parsear_json_modelo(getattr(resp, "text", "") or "")
                if parsed:
                    print(f"[AL OCR] Visión Gemini respondió ({modelo}).", flush=True)
                    return parsed
            except Exception as exc:
                print(f"[AL OCR] Gemini ({modelo}) falló: {_detalle_error(exc)}", flush=True)
                continue
    except Exception as exc:
        print(f"[AL OCR] Cliente google.genai: {_detalle_error(exc)}", flush=True)
    return None


def _log_estado_claves() -> None:
    gem = _clave_gemini()
    oai = _clave_openai()
    if gem:
        print(f"[AL OCR] GEMINI_API_KEY configurada ({_enmascarar_clave(gem)})", flush=True)
    if oai:
        print(f"[AL OCR] OPENAI_API_KEY configurada ({_enmascarar_clave(oai)})", flush=True)
    if not gem and not oai:
        print(
            "[AL OCR] Sin clave de visión. Defina GEMINI_API_KEY, OPENAI_API_KEY o API_KEY en .env",
            flush=True,
        )


_log_estado_claves()


def _qty_esperado_fila(fila: dict[str, Any]) -> int:
    """Cajas de la fila: Exp Eaches / esperado. Nunca Full Pallets."""
    prohibidas = {
        "full_pallets",
        "full pallets",
        "paletas",
        "paletas_completas",
        "pallets",
        "tihi",
        "ti/hi",
        "rec_eaches",
        "rec eaches",
    }
    for clave in (
        "esperado",
        "exp_eaches",
        "Exp Eaches",
        "exp eaches",
        "total_cases",
        "Total Cases",
        "cajas_esperadas",
        "cantidad_esperada",
        "qty",
        "QTY",
        "cantidad",
    ):
        if clave not in fila:
            continue
        if str(clave).strip().lower() in prohibidas:
            continue
        valor = fila.get(clave)
        if valor in (None, ""):
            continue
        try:
            n = int(float(str(valor).replace(",", "")))
        except ValueError:
            continue
        if n > 0:
            return n
    return 0


def _parece_encabezado_no_sku(sku: str) -> bool:
    """Descarta ASN, Trailer ISO y etiquetas de cabecera."""
    codigo = _sanear_sku(sku)
    if CONTENEDOR_RE.fullmatch(codigo):
        return True
    encabezado = {
        "ASN",
        "BOL",
        "TRAILER",
        "VENDOR",
        "SKU",
        "SKUS",
        "PALLET",
        "PALLETS",
        "EACHES",
        "CASES",
        "INBOUND",
        "RECEIVING",
        "REPORT",
        "HUSKY",
    }
    return codigo in encabezado


def inventario_desde_vision(payload: dict[str, Any], formato: str | None = None) -> dict[str, Any]:
    skus: list[dict[str, Any]] = []
    vistos: set[str] = set()
    filas = payload.get("skus") if isinstance(payload, dict) else payload
    if isinstance(payload, list):
        filas = payload
    for fila in filas or []:
        if not isinstance(fila, dict):
            continue
        sku = _sanear_sku(str(fila.get("sku") or fila.get("SKU") or ""))
        if not sku or len(sku) < 4 or sku in vistos:
            continue
        if _parece_encabezado_no_sku(sku):
            continue
        if _es_ruido_sku(sku):
            continue
        if sku.replace("-", "").isalpha():
            continue
        desc = str(
            fila.get("descripcion")
            or fila.get("SKU Description")
            or fila.get("Description")
            or fila.get("description")
            or sku
        )
        if _parece_texto_ocr_basura(desc):
            continue
        qty = _qty_esperado_fila(fila)
        vistos.add(sku)
        skus.append(_sku_item(sku, qty, desc[:80]))
    contenedor = ""
    if isinstance(payload, dict):
        contenedor = str(payload.get("contenedor") or payload.get("trailer") or "").strip()
    return {
        "contenedor": re.sub(r"\s+", "", contenedor.upper()),
        "formato": (formato or "B").upper(),
        "fecha_carga": _ahora(),
        "skus": skus,
    }


def procesar_documento(data: bytes, formato: str | None = None) -> dict[str, Any]:
    """Visión (Gemini / OpenAI) lee la hoja; Tesseract solo si no hay API o falla."""
    global _ERRORES_VISION
    _ERRORES_VISION = []
    imagen = None
    tabla = None
    try:
        if not _hay_clave_vision():
            print(
                "[AL OCR] Visión no disponible: falta GEMINI_API_KEY / OPENAI_API_KEY / API_KEY.",
                flush=True,
            )
        else:
            print("[AL OCR] Enviando hoja a visión (Gemini / OpenAI)…", flush=True)
        vision = extraer_json_gemini(data) or extraer_json_openai(data) if _hay_clave_vision() else None
        if vision:
            invent_v = inventario_desde_vision(vision, formato=formato)
            if invent_v.get("skus"):
                return invent_v
            print("[AL OCR] Visión respondió sin SKUs útiles.", flush=True)
        elif _hay_clave_vision():
            detalle = " | ".join(_ERRORES_VISION[-3:]) or "sin detalle"
            print(f"[AL OCR] Visión falló. Respaldo local ligero (Tesseract). Detalle: {detalle}", flush=True)
        else:
            print("[AL OCR] Respaldo local ligero (Tesseract). EasyOCR no se cargará.", flush=True)

        texto = extraer_texto(data)
        inventario = parsear_texto(texto, formato=formato) if texto.strip() else {
            "contenedor": "",
            "formato": (formato or "A").upper(),
            "fecha_carga": _ahora(),
            "skus": [],
        }
        inventario["skus"] = [
            item
            for item in (inventario.get("skus") or [])
            if item.get("sku")
            and not str(item.get("sku", "")).replace("-", "").isalpha()
            and not _parece_encabezado_no_sku(str(item.get("sku")))
            and not _es_ruido_sku(str(item.get("sku")))
            and not _parece_texto_ocr_basura(str(item.get("producto") or ""))
        ]
        if inventario.get("skus") and _lectura_local_confiable(inventario, texto):
            return inventario
        if inventario.get("skus"):
            print("[AL OCR] Respaldo Tesseract descartado: lectura ilegible.", flush=True)
            inventario["skus"] = []

        easy_forzado = os.environ.get("AL_EASYOCR", "").strip().lower() in {"1", "true", "yes"}
        if _hay_clave_vision() and not easy_forzado:
            print(
                "[AL OCR] EasyOCR omitido: hay clave de visión. No se carga el modelo pesado.",
                flush=True,
            )
            return inventario

        if not easy_forzado:
            print("[AL OCR] EasyOCR omitido (defina AL_EASYOCR=1 para activarlo).", flush=True)
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


def ultimo_error_vision() -> str:
    return " | ".join(_ERRORES_VISION[-3:])


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
        "ASN",
        "BOL",
        "TRAILER",
        "VENDOR",
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
    if limpio.isalpha():
        return True
    if len(limpio) < 6:
        return True
    return False


def _parece_texto_ocr_basura(texto: str) -> bool:
    """Detecta lecturas giradas tipo QDee... / S3TVS ONOTSAS."""
    t = (texto or "").strip()
    if not t:
        return False
    raro = sum(1 for c in t if not (c.isalnum() or c.isspace() or c in "-./#&+()"))
    if raro >= 3:
        return True
    if re.search(r"[a-z]{2,}[A-Z]{3,}[a-z]", t):
        return True
    letras = [c for c in t if c.isalpha()]
    if len(letras) >= 12:
        minus = sum(1 for c in letras if c.islower())
        ratio = minus / len(letras)
        if 0.12 < ratio < 0.88 and re.search(r"[A-Z]{4,}", t) and re.search(r"[a-z]{4,}", t):
            return True
    return False


def _lectura_local_confiable(inventario: dict[str, Any], texto: str) -> bool:
    skus = inventario.get("skus") or []
    if not skus:
        return False
    if any(_parece_texto_ocr_basura(str(item.get("producto") or "")) for item in skus):
        return False
    if any(len(re.sub(r"\D", "", str(item.get("sku") or ""))) >= 9 for item in skus):
        return True
    upper = (texto or "").upper()
    return "INBOUND" in upper or "HUSKY" in upper or "EXP EACHES" in upper


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
    """Inbound Receiving Report: Trailer, columna SKU, Exp Eaches."""
    contenedor = _buscar_contenedor(texto, [r"TRAILER", r"CONTAINER", r"CONTENEDOR"])
    asn = ""
    match_asn = re.search(r"\bASN[:\s]+(\d{5,12})", texto, re.I)
    if match_asn:
        asn = match_asn.group(1)
    esperado = None
    match_exp = re.search(r"exp\s*eaches[:\s]*(\d{1,6})", texto, re.I)
    if match_exp:
        esperado = int(match_exp.group(1))
    if esperado is None:
        match_cases = re.search(r"total\s*cases[:\s]*(\d{1,6})", texto, re.I)
        if match_cases:
            esperado = int(match_cases.group(1))

    zona = _zona_tabla(texto)
    skus: list[dict[str, Any]] = []
    vistos: set[str] = set()
    desc = ""
    match_desc = re.search(r"\b(HUSKY[\w\s\-]{4,40})", texto, re.I)
    if match_desc:
        desc = re.sub(r"\s+", " ", match_desc.group(1)).strip()

    candidatos = re.findall(r"\b(\d{9,12})\b", zona or texto)
    for codigo in candidatos:
        if codigo == asn:
            continue
        sku = _sanear_sku(codigo)
        if _es_ruido_sku(sku) or sku in vistos:
            continue
        qty = esperado if esperado is not None else (_qty_de_linea(zona or texto) or 0)
        vistos.add(sku)
        skus.append(_sku_item(sku, qty, desc or sku))

    if not skus:
        for linea in _limpiar_lineas(zona):
            if re.search(r"\b(ASN|TRAILER|VENDOR|BOL|FULL PALLETS|DOCK DOOR)\b", linea, re.I):
                continue
            fila = _parsear_fila_producto(linea)
            if not fila:
                continue
            sku, descripcion, qty = fila
            if sku == asn or sku in vistos:
                continue
            vistos.add(sku)
            skus.append(_sku_item(sku, esperado if esperado is not None else qty, descripcion or desc))

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
