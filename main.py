"""AL - Asistente de Lumper. API FastAPI + PWA estática."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from services import chat_service, inventory_service, license_manager
from services.ocr_engine import inventario_demo, mensaje_carga, procesar_documento
from services.paths import CSV_EXPORT_PATH, STATIC_DIR, ensure_data_dir
from services.persistence import CsvFileStore, get_store

app = FastAPI(title="AL - Asistente de Lumper", version="1.0.0")
ensure_data_dir()
license_manager.ensure_license_file()

RUTAS_LIBRES = {
    "/api/health",
    "/api/license",
    "/api/license/status",
}


class BuscarBody(BaseModel):
    dictado: str = Field(..., min_length=1)
    minimo: int | None = Field(default=None, ge=1, le=12)


class ConteoBody(BaseModel):
    sku: str = Field(..., min_length=1)
    cantidad: int = Field(..., ge=0)
    modo: Literal["sumar", "editar"] = "sumar"


class PaletaBody(BaseModel):
    sku: str = Field(..., min_length=1)
    cajas_por_paleta: int = Field(..., ge=0, le=9999)


class ChatBody(BaseModel):
    rol: Literal["operador", "al", "sistema"]
    texto: str = Field(..., min_length=1)
    meta: dict[str, Any] | None = None


class ChatSyncBody(BaseModel):
    mensajes: list[dict[str, Any]]


@app.middleware("http")
async def licencia_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in RUTAS_LIBRES:
        estado = license_manager.estado_licencia()
        if estado.get("bloqueada"):
            return JSONResponse(
                {
                    "detail": estado.get("error") or "Licencia expirada. Operación bloqueada.",
                    "bloqueado": True,
                    "licencia": estado,
                },
                status_code=403,
            )
    return await call_next(request)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "app": "AL", "version": "1.0.0"}


@app.get("/api/license")
@app.get("/api/license/status")
def license_status() -> dict[str, Any]:
    return license_manager.estado_licencia()


@app.get("/api/config")
def config_usuario() -> dict[str, Any]:
    return get_store().load_config()


@app.get("/api/inventario")
def get_inventario() -> dict[str, Any]:
    inventario = inventory_service.cargar_inventario()
    return {"inventario": inventario, "kpis": inventory_service.kpis(inventario)}


@app.get("/api/kpis")
def get_kpis() -> dict[str, Any]:
    return inventory_service.kpis()


@app.get("/api/inventario/pendientes")
def get_pendientes() -> dict[str, Any]:
    return inventory_service.pendientes()


@app.get("/api/inventario/estatus")
def get_estatus() -> dict[str, Any]:
    return inventory_service.estatus_contenedor()


@app.post("/api/inventario/buscar")
def post_buscar(body: BuscarBody) -> dict[str, Any]:
    cfg = get_store().load_config()
    minimo = body.minimo if body.minimo is not None else int(cfg.get("sufijo_default") or 2)
    return inventory_service.buscar(body.dictado, minimo=minimo)


@app.post("/api/inventario/conteo")
def post_conteo(body: ConteoBody) -> dict[str, Any]:
    try:
        return inventory_service.aplicar_conteo(body.sku, body.cantidad, body.modo)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/inventario/paleta")
def post_paleta(body: PaletaBody) -> dict[str, Any]:
    try:
        return inventory_service.actualizar_paleta(body.sku, body.cajas_por_paleta)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/ocr/upload")
async def upload_documento(
    archivo: UploadFile = File(...),
    formato: str | None = Form(default=None),
) -> dict[str, Any]:
    nombre = (archivo.filename or "").lower()
    contenido = await archivo.read()
    if not contenido:
        raise HTTPException(status_code=400, detail="Archivo vacío")

    if nombre.endswith(".csv"):
        tmp = ensure_data_dir() / "_upload_tmp.csv"
        tmp.write_bytes(contenido)
        inventario = CsvFileStore.import_skus(tmp, formato="CSV")
        tmp.unlink(missing_ok=True)
    else:
        inventario = procesar_documento(contenido, formato=formato)

    if not inventario.get("skus"):
        raise HTTPException(
            status_code=422,
            detail="El documento no devolvió SKUs. Pruebe otro recorte o el modo demo.",
        )

    inventory_service.guardar_inventario(inventario)
    voz = mensaje_carga(inventario)
    return {
        "ok": True,
        "mensaje": voz,
        "inventario": inventario,
        "kpis": inventory_service.kpis(inventario),
    }


@app.post("/api/ocr/demo")
def cargar_demo() -> dict[str, Any]:
    inventario = inventario_demo()
    inventory_service.guardar_inventario(inventario)
    voz = mensaje_carga(inventario)
    return {
        "ok": True,
        "mensaje": voz,
        "inventario": inventario,
        "kpis": inventory_service.kpis(inventario),
    }


@app.get("/api/export/csv")
def export_csv() -> FileResponse:
    path = get_store().export_inventory_csv(CSV_EXPORT_PATH)
    return FileResponse(path, filename="inventario_sesion.csv", media_type="text/csv")


@app.get("/api/chat")
def get_chat() -> dict[str, Any]:
    return {"mensajes": chat_service.listar_mensajes()}


@app.post("/api/chat")
def post_chat(body: ChatBody) -> dict[str, Any]:
    mensaje = chat_service.agregar_mensaje(body.rol, body.texto, body.meta)
    return {"mensaje": mensaje, "mensajes": chat_service.listar_mensajes()}


@app.put("/api/chat")
def put_chat(body: ChatSyncBody) -> dict[str, Any]:
    return {"mensajes": chat_service.reemplazar_chat(body.mensajes)}


@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    # 0.0.0.0: accesible desde teléfonos/tablets en la misma Wi-Fi.
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
