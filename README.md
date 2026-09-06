# AL - Asistente de Lumper

PWA hands-free para operadores de montacargas. FastAPI sirve la interfaz instalable, el inventario local y el control de licencia.

## Arranque

```bash
python -m pip install -r requirements.txt
python main.py
```

Abra `http://127.0.0.1:8000` en Chrome o Edge (Web Speech API). En el teléfono use la misma red: `http://<IP-de-esta-PC>:8000`.

Tesseract OCR es opcional. Sin él puede cargar `data/ejemplo_inbound.csv` o el botón **Cargar demo**.

## Voz

1. Toque el micrófono y permita el permiso.
2. Diga **Oye AL** y luego el comando:
   - `buscar 45`
   - `suma 3` / `van 2 al 80`
   - `edita 12` / `fija en 10`
   - `cuantos skus faltan`
   - `cuantas cajas faltan`

La búsqueda usa el sufijo (derecha a izquierda, 2 caracteres por defecto).

## Licencia

`data/licencia.json` guarda un token Fernet. Si `fecha_expiracion` ya pasó, la API bloquea la operación. En producción defina `AL_LICENSE_KEY`.

## MySQL futuro

Hoy persiste JSON/CSV (`AL_STORAGE=json`). El contrato `MySQLStore` queda listo para `AL_STORAGE=mysql` + `DATABASE_URL`.


📲 *Instrucciones para instalar AL - Asistente de Lumper*

Hola [Nombre del Operador], para instalar la aplicación en tu iPhone/Teléfono sigue estos sencillos pasos:

1️⃣ Abre el siguiente enlace únicamente desde el navegador **Safari** en tu iPhone:
👉 https://tu-enlace-de-la-app.com

2️⃣ En la parte inferior de Safari, toca el botón **Compartir** (el icono del cuadrado con una flecha hacia arriba 📤).

3️⃣ Desplázate hacia abajo en las opciones y selecciona **"Agregar a inicio"** (Add to Home Screen).

4️⃣ Toca **"Agregar"** arriba a la derecha.

¡Listo! Verás el icono de **AL** directamente en la pantalla de inicio de tu teléfono como cualquier aplicación. Ábrela y autoriza el uso de la cámara y el micrófono cuando te lo solicite.