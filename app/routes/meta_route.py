# routes/meta_webhook.py
import os
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import PlainTextResponse
from controllers.meta_controller import get_meta_message  

router = APIRouter()

@router.post("/webhookMessage")
async def webhook_message(request: Request):
    raw_body: bytes = await request.body()
    request.state.raw_body = raw_body
    return await get_meta_message(request)

@router.get("/webhookMessage")
async def verify_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == os.getenv("WEBHOOK_VERIFY_TOKEN"):
        print("Webhook verified successfully!")
        return PlainTextResponse(hub_challenge or "", status_code=200)
    raise HTTPException(status_code=403, detail="Forbidden")
