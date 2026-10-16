"""Portrait upright no se rota. Dedup de SKU: keep-first."""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import ocr_engine as ocr


def _jpeg_portrait_marca() -> bytes:
    img = Image.new("RGB", (1200, 1600), "white")
    for x in range(0, 40):
        for y in range(0, 40):
            img.putpixel((x, y), (220, 30, 30))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


class OrientacionTests(unittest.TestCase):
    def test_abrir_hoja_no_rota_portrait(self):
        data = _jpeg_portrait_marca()
        meta = ocr._meta_imagen(data)
        self.assertEqual((meta["width"], meta["height"]), (1200, 1600))
        imagen = ocr._abrir_hoja(data)
        try:
            self.assertEqual(imagen.size, (1200, 1600))
            self.assertEqual(imagen.getpixel((10, 10))[0], 220)
        finally:
            imagen.close()

    def test_jpeg_preparado_acepta_portrait(self):
        data = _jpeg_portrait_marca()
        self.assertTrue(ocr._jpeg_ya_preparado(data))
        jpeg = ocr._imagen_a_jpeg_bytes(data)
        self.assertIs(jpeg, data)

    def test_rotacion_antigua_habria_puesto_la_marca_abajo(self):
        data = _jpeg_portrait_marca()
        imagen = Image.open(io.BytesIO(data)).convert("RGB")
        rotada = imagen.rotate(90, expand=True)
        self.assertEqual(rotada.size, (1600, 1200))
        self.assertNotEqual(rotada.getpixel((10, 10))[0], 220)


class ClienteJsTests(unittest.TestCase):
    def test_app_js_ya_no_rota_portrait(self):
        app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("ctx.rotate(-Math.PI / 2)", app)
        self.assertIn('rotacion_aplicada: "no"', app)
        self.assertIn("[AL UPLOAD] client_prepare", app)


class DedupVisionTests(unittest.TestCase):
    CAJU_LINEAS = [
        ("AXCMTBL-10-AS", 24),
        ("AXCSKY-09MRB", 42),
        ("AXCMTCOR-AG", 20),
        ("AXCMTNOV-CO", 24),
        ("AXCMTNOV-SLO", 24),
        ("AXCATROB-BR", 24),
        ("AXCMTMOR-AS", 24),
        ("AXCWIN-01-WAL", 24),
        ("AXCATDAY-WW", 42),
        ("AXCATBOY-RBL", 14),
        ("AXCATBOY-NL", 28),
        ("AXCWIN-01-WAL", 10),
        ("AXCATDAY-NL", 28),
        ("AXCMCPRE-AG", 14),
        ("AXCBRO-04-MRB", 20),
    ]

    def test_sku_repetido_suma_cantidades(self):
        payload = {
            "contenedor": "CAJU5170915",
            "skus": [
                {"sku": "AXCWIN-01-WAL", "esperado": 24},
                {"sku": "AXCWIN-01-WAL", "esperado": 10},
            ],
            "_validation": {"declared_cases": 34},
        }
        invent = ocr.inventario_desde_vision(payload, formato="A")
        filas = [i for i in invent["skus"] if i["sku"] == "AXCWIN-01-WAL"]
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["cantidad_esperada"], 34)

    def test_oracle_caju5170915_completa_tras_merge(self):
        payload = {
            "contenedor": "CAJU5170915",
            "skus": [{"sku": sku, "esperado": qty} for sku, qty in self.CAJU_LINEAS],
            "_validation": {"total_ordered": 362},
        }
        invent = ocr.inventario_desde_vision(payload, formato="A")
        meta = ocr.extraer_meta_validacion(payload)
        chequeo = ocr.evaluar_completitud(invent, meta, formato="A")
        por_sku = {item["sku"]: item["cantidad_esperada"] for item in invent["skus"]}
        self.assertEqual(invent["contenedor"], "CAJU5170915")
        self.assertEqual(len(self.CAJU_LINEAS), 15)
        self.assertEqual(len(invent["skus"]), 14)
        self.assertEqual(por_sku["AXCWIN-01-WAL"], 34)
        self.assertEqual(sum(por_sku.values()), 362)
        self.assertEqual(meta["declared_cases"], 362)
        self.assertEqual(chequeo["estado"], "OK")
        self.assertEqual(chequeo["suma_cajas"], 362)


if __name__ == "__main__":
    unittest.main()
