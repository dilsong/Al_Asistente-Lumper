"""Presupuesto total de visión. No llama APIs."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import ocr_engine as ocr


class PresupuestoVisionTests(unittest.TestCase):
    def test_timeout_no_supera_restante(self):
        p = ocr._PresupuestoVision(10)
        self.assertGreaterEqual(p.timeout_s(18), 9)
        self.assertLessEqual(p.timeout_s(18), 10)

    def test_no_inicia_si_queda_poco(self):
        p = ocr._PresupuestoVision(0.4)
        time.sleep(0.05)
        self.assertFalse(p.puede_llamar(3.5))

    def test_primario_es_36_no_latest(self):
        self.assertEqual(ocr._MODELOS_FLASH_PRIORIDAD[0], "gemini-3.6-flash")
        self.assertEqual(ocr._PRESUPUESTO_VISION_S, 22)
        self.assertLessEqual(ocr._VISION_TIMEOUT_S, ocr._PRESUPUESTO_VISION_S)

    def test_oracle_po_sigue_completa(self):
        payload = {
            "contenedor": "HAMU2899883",
            "skus": [
                {"sku": "AXCLDYHEN-SS", "esperado": 70},
                {"sku": "AXCLDYDAR20-SS", "esperado": 24},
                {"sku": "AXCLDYDAR46-SS", "esperado": 12},
                {"sku": "AXCLDYHEN24-AB", "esperado": 60},
                {"sku": "AXCLDYHEN36-SS", "esperado": 35},
                {"sku": "AXCLDYMWS20-SS", "esperado": 14},
                {"sku": "AXCLDYMUR28-AB", "esperado": 12},
                {"sku": "AXCLDYREE36-SS", "esperado": 35},
            ],
            "_validation": {"total_ordered": 262},
        }
        invent = ocr.inventario_desde_vision(payload, formato="A")
        chequeo = ocr.evaluar_completitud(invent, ocr.extraer_meta_validacion(payload), "A")
        self.assertEqual(len(invent["skus"]), 8)
        self.assertEqual(invent["skus"][0]["sku"], "AXCLDYHEN-SS")
        self.assertEqual(sum(i["cantidad_esperada"] for i in invent["skus"]), 262)
        self.assertEqual(chequeo["estado"], "OK")


if __name__ == "__main__":
    unittest.main()
