from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"

LICENCIA_PATH = DATA_DIR / "licencia.json"
CONFIG_PATH = DATA_DIR / "config_usuario.json"
INVENTARIO_PATH = DATA_DIR / "inventario_sesion.json"
CHAT_PATH = DATA_DIR / "sesion_chat.json"
CSV_EXPORT_PATH = DATA_DIR / "inventario_sesion.csv"


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
