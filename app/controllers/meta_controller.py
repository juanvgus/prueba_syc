import os
import hmac
import hashlib
import json
from typing import Any, Dict, Optional
from fastapi import Request
from fastapi.responses import JSONResponse
from app.utilities.functions import validate_message, add_chat_messages, message_handlers


async def get_meta_message(request: Request):
    """
    Webhook de Meta/WhatsApp:
      - Verifica phone_number_id de la app
      - Valida firma HMAC SHA256 (x-hub-signature-256)
      - Evita reprocesar mensajes
      - Enruta al handler por tipo de mensaje
    """
    try:
        # Lee el cuerpo crudo primero (para firmar) y reúsalo para JSON
        raw_body: bytes = await request.body()
        payload: Dict[str, Any] = json.loads(raw_body or b"{}")

        phone_number_id = os.getenv("PHONE_NUMBER_ID")
        business_phone_number_id = (
            payload.get("entry", [{}])[0]
                  .get("changes", [{}])[0]
                  .get("value", {})
                  .get("metadata", {})
                  .get("phone_number_id")
        )

        if phone_number_id != business_phone_number_id:
            print("Ignorado, no es nuestra app!!!!")
            return JSONResponse({"message": "Application not found"}, status_code=200)

        # ----- Verificación HMAC -----
        app_secret = os.getenv("APP_SECRET", "")
        header_sig = request.headers.get("x-hub-signature-256")  
        provided = header_sig.split("=", 1)[1] if header_sig and "=" in header_sig else None
        computed = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

        if not (provided and hmac.compare_digest(computed, provided)):
            print("Acceso no autorizado!!!!!!!")
            return JSONResponse({"message": "Acceso no autorizado"}, status_code=200)

        # ----- Extrae el mensaje entrante -----
        message = (
            payload.get("entry", [{}])[0]
                  .get("changes", [{}])[0]
                  .get("value", {})
                  .get("messages", [None])[0]
        )

        if not message:
            return JSONResponse({"message": "Not found"}, status_code=200)
        message_type = message.get("type")
        from_id = message.get("from")
        message_id = message.get("id")

        # ----- Evita reprocesar -----
        if await validate_message(from_id, message_id):
            return JSONResponse({"message": "Mensaje ya procesado"}, status_code=200)
        # ----- Flujo principal -----
        await add_chat_messages(from_id, message, False)
        handler = message_handlers.get(message_type, message_handlers["default"])
        await handler(message, business_phone_number_id)
        return JSONResponse({"ok": True}, status_code=200)

    except Exception as e:
        return JSONResponse({"message": str(e)}, status_code=200)

