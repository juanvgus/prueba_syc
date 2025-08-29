import hmac
import os
import json
from hashlib import sha256
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from app.utilities.functions import add_user, validate_daily_session, validate_message, add_chat_message, get_user
from app.utilities.mainFunctions import messageHandlers

router = APIRouter(prefix="/webhookMeta", tags=["MetaWebhook"])

PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")
APP_SECRET = os.getenv("APP_SECRET", "")
VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN", "")

# GET /api/webhookMeta/webhookMessage  -> verificación del webhook
@router.get("/webhookMessage")
async def verify_webhook(hub_mode: str | None = None, hub_verify_token: str | None = None, hub_challenge: str | None = None):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge or "", status_code=200)
    return Response(status_code=403)

# POST /api/webhookMeta/webhookMessage -> recepción de mensajes
@router.post("/webhookMessage")
async def get_meta_message(request: Request):
    try:
        raw_body = await request.body()  # bytes
        # Verificación de firma X-Hub-Signature-256
        header = request.headers.get("x-hub-signature-256")
        if not header:
            return JSONResponse({"message": "Acceso no autorizado (sin firma)"}, status_code=200)

        try:
            scheme, header_hash = header.split("=", 1)
        except ValueError:
            return JSONResponse({"message": "Encabezado de firma inválido"}, status_code=200)

        mac = hmac.new(APP_SECRET.encode("utf-8"), msg=raw_body, digestmod=sha256).hexdigest()
        if mac != header_hash:
            return JSONResponse({"message": "Acceso no autorizado"}, status_code=200)

        # Parseo del body
        data = json.loads(raw_body.decode("utf-8"))

        phone_number_id = PHONE_NUMBER_ID
        business_phone_number_id = (
            data.get("entry", [{}])[0]
                .get("changes", [{}])[0]
                .get("value", {})
                .get("metadata", {})
                .get("phone_number_id")
        )

        if phone_number_id != business_phone_number_id:
            # Ignorado si no es nuestra App
            return JSONResponse({"message": "Application not found"}, status_code=200)

        message = (
            data.get("entry", [{}])[0]
                .get("changes", [{}])[0]
                .get("value", {})
                .get("messages", [None])[0]
        )

        message_type = message.get("type") if message else None
        if not message:
            return JSONResponse({"message": "Not found"}, status_code=200)

        # flujo

        return Response(status_code=200)

    except Exception as e:
        return JSONResponse({"error": True, "message": str(e)}, status_code=200)