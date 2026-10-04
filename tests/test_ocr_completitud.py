"""Validación de lectura incompleta y recuperación dirigida (sin UI)."""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import ocr_engine as ocr

FIXTURES = ROOT / "tests" / "fixtures" / "ocr"
INBOUND = FIXTURES / "inbound_receiving_real_01.png"
PURCHASE = FIXTURES / "purchase_order_real_01.png"


def _jpeg_blanco() -> bytes:
    img = Image.new("RGB", (800, 500), "white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


class CompletitudInboundTests(unittest.TestCase):
    def test_inbound_coherente_no_recupera(self):
        inventario = {
            "contenedor": "KKFU7868019",
            "skus": [ocr._sku_item("1015223027", 54)],
        }
        meta = {"declared_skus": 1, "declared_cases": 54}
        chequeo = ocr.evaluar_completitud(inventario, meta, formato="B")
        self.assertEqual(chequeo["estado"], "OK")
        self.assertEqual(chequeo["extracted"], 1)
        self.assertEqual(chequeo["declared_skus"], 1)

    def test_omision_simulada_incompleta(self):
        inventario = {
            "contenedor": "KKFU7868019",
            "skus": [
                ocr._sku_item("1111111111", 10),
                ocr._sku_item("2222222222", 10),
                ocr._sku_item("3333333333", 10),
            ],
        }
        meta = {"declared_skus": 5, "declared_cases": 100}
        chequeo = ocr.evaluar_completitud(inventario, meta, formato="B")
        self.assertEqual(chequeo["estado"], "INCOMPLETE")
        self.assertEqual(chequeo["extracted"], 3)
        self.assertEqual(chequeo["declared_skus"], 5)

    def test_sin_metadatos_no_verificable(self):
        inventario = {"skus": [ocr._sku_item("1015223027", 54)]}
        chequeo = ocr.evaluar_completitud(inventario, {}, formato="B")
        self.assertEqual(chequeo["estado"], "UNVERIFIABLE")


class CompletitudPurchaseTests(unittest.TestCase):
    def test_total_quantity_menor_es_incompleta(self):
        inventario = {
            "skus": [
                ocr._sku_item("P0845170-1", 2),
                ocr._sku_item("P0845170-2", 2),
            ],
        }
        meta = {"declared_cases": 8}
        chequeo = ocr.evaluar_completitud(inventario, meta, formato="A")
        self.assertEqual(chequeo["estado"], "INCOMPLETE")

    def test_total_quantity_coherente_ok(self):
        inventario = {
            "skus": [
                ocr._sku_item("P0845170-1", 4),
                ocr._sku_item("P0845170-2", 4),
            ],
        }
        meta = {"declared_cases": 8}
        chequeo = ocr.evaluar_completitud(inventario, meta, formato="A")
        self.assertEqual(chequeo["estado"], "OK")

    @unittest.skipUnless(PURCHASE.is_file(), "fixture PO ausente")
    def test_total_quantity_no_lo_pisa_la_geometria(self):
        data = PURCHASE.read_bytes()
        inventario = {
            "skus": [ocr._sku_item(f"SKU{i:04d}AA", 1) for i in range(8)],
        }
        meta = {"declared_cases": 8}
        chequeo = ocr.evaluar_completitud(inventario, meta, formato="A", data=data)
        self.assertEqual(chequeo["estado"], "OK")
        self.assertIsNone(chequeo["expected_rows"])


class FusionYMetaTests(unittest.TestCase):
    def test_fusion_deduplica_y_conserva_cantidad(self):
        primero = [ocr._sku_item("AAA11111", 10)]
        extra = [ocr._sku_item("AAA11111", 99), ocr._sku_item("BBB22222", 5)]
        fusion, n = ocr.fusionar_skus_recuperados(primero, extra)
        skus = {item["sku"]: item["cantidad_esperada"] for item in fusion}
        self.assertEqual(n, 1)
        self.assertEqual(skus["AAA11111"], 10)
        self.assertEqual(skus["BBB22222"], 5)

    def test_meta_no_usa_total_cases_como_fila(self):
        payload = {
            "contenedor": "KKFU7868019",
            "skus": [{"sku": "1015223027", "esperado": 54, "total_cases": 54}],
            "_validation": {"declared_skus": 1, "declared_cases": 54},
        }
        invent = ocr.inventario_desde_vision(payload, formato="B")
        meta = ocr.extraer_meta_validacion(payload)
        self.assertEqual(invent["skus"][0]["cantidad_esperada"], 54)
        self.assertNotIn("_validation", invent)
        self.assertEqual(meta["declared_skus"], 1)
        self.assertEqual(meta["declared_cases"], 54)

    def test_total_cases_no_rellena_cantidad_de_fila(self):
        payload = {"skus": [{"sku": "1015223027", "Total Cases": 54}]}
        invent = ocr.inventario_desde_vision(payload, formato="B")
        self.assertEqual(invent["skus"], [])


class RecuperacionSimuladaTests(unittest.TestCase):
    def test_omision_activa_recuperacion(self):
        imagen = _jpeg_blanco()
        primera = {
            "contenedor": "KKFU7868019",
            "skus": [
                {"sku": "1111111111", "esperado": 10},
                {"sku": "2222222222", "esperado": 20},
                {"sku": "3333333333", "esperado": 30},
            ],
            "_validation": {"declared_skus": 5, "declared_cases": 100},
        }
        segunda = {
            "skus": [
                {"sku": "4444444444", "esperado": 20},
                {"sku": "5555555555", "esperado": 20},
            ]
        }
        prompts: list[str | None] = []

        def fake_vision(_data, jpeg=None, prompt=None):
            prompts.append(prompt)
            if prompt and "already found these SKUs" in prompt:
                return segunda
            return primera

        with patch.object(ocr, "extraer_json_gemini", side_effect=fake_vision), patch.object(
            ocr, "extraer_json_openai", return_value=None
        ):
            invent = ocr.procesar_documento(imagen, formato="B")

        self.assertEqual(invent["contenedor"], "KKFU7868019")
        self.assertEqual(len(invent["skus"]), 5)
        self.assertTrue(any(p and "already found these SKUs" in p for p in prompts))
        self.assertNotIn("_validation", invent)
        self.assertTrue(all(item.get("producto") == "" for item in invent["skus"]))


class ValidadorCostoTests(unittest.TestCase):
    @unittest.skipUnless(INBOUND.is_file(), "fixture inbound ausente")
    def test_validador_inbound_es_barato(self):
        data = INBOUND.read_bytes()
        inventario = {"skus": [ocr._sku_item("1015223027", 54)]}
        meta = {"declared_skus": 1, "declared_cases": 54}
        chequeo = ocr.evaluar_completitud(inventario, meta, formato="B", data=data)
        self.assertEqual(chequeo["estado"], "OK")
        self.assertLess(chequeo["validator_ms"], 150)

    @unittest.skipUnless(PURCHASE.is_file(), "fixture PO ausente")
    def test_validador_po_geom_es_barato(self):
        data = PURCHASE.read_bytes()
        filas, ms = ocr.estimar_filas_producto(data)
        print(f"[AL OCR TEST] po_geom_rows={filas} validator={ms}ms", flush=True)
        self.assertLess(ms, 150)


if __name__ == "__main__":
    unittest.main()
