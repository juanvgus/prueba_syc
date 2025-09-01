"""
Servicio de asistencia para trámites vehiculares (consulta de deuda y pago).

- Autenticación contra SCI TOTAL
- Consulta de deuda por placa
- Creación de transacción (link de pago)
- Extracción de placa desde lenguaje natural con OpenAI
- Redacción de mensajes de WhatsApp listos para el usuario

Requisitos:
- python -m pip install requests pydantic openai
- Variables de entorno:
    OPENAI_API_KEY=<tu_api_key>
    NEXT_PUBLIC_TOTAL_SCI_API_URL=http://pagossi.sycpruebas.com/SCITOTAL
    UAPI=usr_total_fintrace
    PAPI=PruebasTotal123
"""

import os
import re
import json
import requests
from typing import Any, Dict, Optional, Tuple, Union
from pydantic import BaseModel, field_validator
from openai import OpenAI
from datetime import datetime, timedelta
from fastapi import HTTPException
from app.models.ChatMessages import ChatMessages
from app.models.report import Report

# =========================
# Configuración / Constantes
# =========================

BASE_URL = os.getenv("NEXT_PUBLIC_TOTAL_SCI_API_URL")
UAPI = os.getenv("UAPI")
PAPI = os.getenv("PAPI")
GRAPH_API_URL = os.getenv("GRAPH_API_URL")
GRAPH_API_TOKEN = os.getenv("GRAPH_API_TOKEN")

# Debe estar en el entorno. Evita hardcodear.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Mensaje inicial de bienvenida
INITIAL_MESSAGE = (
    "Hola 👋 Soy tu asistente de trámites vehiculares. Te ayudo a consultar deudas, sanciones, "
    "fecha límite y a generar el pago en minutos. ¿Cuál es la placa del vehículo? (ej.: ABC123 o ABC12D)"
)

# Prompt del redactor de WhatsApp
WHATSAPP_SYSTEM_PROMPT = (
    "Eres un redactor para WhatsApp. Escribe un único mensaje claro y corto (3–5 líneas, máx. 450 caracteres) "
    "en español de Colombia. Usa EXCLUSIVAMENTE los datos que te paso. "
    "Incluye: placa, vigencia, municipio y dpto de matrícula (muniMatr/deptoMatr), TOTAL a pagar (total) "
    "y fecha límite (fechaLim) en formato DD/MM/AAAA. Si 'sancion' > 0 o 'interes' > 0, menciónalos brevemente. "
    "Formatea montos en COP con separador de miles y SIN decimales (ej: $917.688). "
    "No inventes campos, no uses emojis, no devuelvas JSON."
)

# Cliente OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

# Reutiliza una sesión HTTP (mejor performance y control de timeouts)
HTTP_TIMEOUT = 60
session = requests.Session()


# =========================
# Utilidades
# =========================

def format_cop(value: Any) -> str:
    """
    Formatea un número como COP sin decimales y con separador de miles '.'.
    Si value no es convertible a int, se retorna str(value).
    """
    try:
        return f"{int(value):,}".replace(",", ".")
    except Exception:
        return str(value)


def format_ddmmyyyy(iso_datetime: str) -> str:
    """
    Convierte una fecha ISO (YYYY-MM-DDTHH:MM:SS[.sss][Z]) a DD/MM/YYYY.
    Si falla, retorna la entrada sin cambios.
    """
    if not iso_datetime:
        return ""
    try:
        return datetime.fromisoformat(iso_datetime.replace("Z", "")).strftime("%d/%m/%Y")
    except Exception:
        try:
            y, m, d = iso_datetime[:10].split("-")
            return f"{d}/{m}/{y}"
        except Exception:
            return iso_datetime


# =========================
# Modelos y validación
# =========================

class VehicleData(BaseModel):
    """
    Datos de vehículo extraídos por LLM.
    Se normaliza la placa: mayúsculas y sin caracteres no alfanuméricos.
    """
    placa: Optional[str] = None
    marca: Optional[str] = None
    modelo: Optional[str] = None
    anio: Optional[str] = None
    color: Optional[str] = None
    otros: Optional[str] = None

    @field_validator('placa', mode='before')
    @classmethod
    def _norm_placa(cls, v):
        if v is None:
            return v
        return re.sub(r'[^A-Za-z0-9]', '', str(v)).upper() or None

# =========================
# Llamadas a la API SCI TOTAL
# =========================

async def authenticate() -> str:
    """
    POST /Autenticacion
    Content-Type: application/x-www-form-urlencoded

    Retorna el token (string) o lanza HTTPException si falla.
    """
    url = f"{BASE_URL}/Autenticacion"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {"Username": UAPI, "Password": PAPI}

    resp = session.post(url, headers=headers, data=data, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    body = resp.json()

    token = body.get("token")
    error_count = body.get("response", {}).get("errorCount")
    errors = body.get("response", {}).get("errors")

    if (error_count not in (None, 0)) or (errors not in (None, 0)) or not token:
        raise HTTPException(f"Fallo autenticación: {json.dumps(body, ensure_ascii=False)}")

    return token


async def consultar_deuda(placa: str, id_cliente: str = "1") -> Dict[str, Any]:
    """
    POST /TotalApp/DeudaPlaca/127
    Content-Type: application/json

    Llama authenticate() para obtener el Bearer token y consulta la deuda por placa.
    Retorna dict con la respuesta completa del API o lanza HTTPException.
    """
    token = await authenticate()
    url = f"{BASE_URL}/TotalApp/DeudaPlaca/127"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"idCliente": id_cliente, "placa": placa}

    resp = session.post(url, headers=headers, json=payload, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    body = resp.json()

    error_count = body.get("response", {}).get("errorCount")
    errors = body.get("response", {}).get("errors")
    if (error_count not in (None, 0)) or (errors not in (None, 0)):
        raise HTTPException(f"Error al consultar deuda: {json.dumps(body, ensure_ascii=False)}")

    return body


async def crear_transaccion(deuda_item: Dict[str, Any]) -> Dict[str, Any]:
    """
    POST /TotalApp/CrearTransaccion
    Content-Type: application/json

    Recibe un único item de 'informacionDepartamental' (deuda_item) y arma el body según el API.
    Retorna la respuesta de la pasarela (dict) o lanza HTTPException.
    """
    br = {
        "email": "test@example.com",
        "valorTotal": str(deuda_item["total"]),
        "iva": "0",
        "descripcionPago": "Pago de trámites desde plataforma TOTAL",
        "idParametro": "127",  
        "idCliente": "910",    
        "dispersion": [
            {
                "palabraClave": "RECAUDO_IUVA",
                "referencia": str(deuda_item["declaracion"]),
                "valor": str(deuda_item["total"]),
                "impuesto": "0",
                "descripcion": (
                    "NOTIFICACION IUVA GENERADO DE TOTAL. EL MONTO INCLUYE EL VALOR DE LA "
                    f"SISTEMATIZACIÓN (PLACA: {deuda_item['placa']} VIGENCIA: {deuda_item['vigencia']})"
                ),
                "liquidacion": "",
                "entityCode": "",
                "serviceCode": ""
            }
        ]
    }

    token = await authenticate()
    url = f"{BASE_URL}/TotalApp/CrearTransaccion"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    resp = session.post(url, headers=headers, json=br, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    body = resp.json()

    error_count = body.get("response", {}).get("errorCount")
    errors = body.get("response", {}).get("errors")
    if (error_count not in (None, 0)) or (errors not in (None, 0)):
        raise HTTPException(f"Error al crear transacción: {json.dumps(body, ensure_ascii=False)}")

    return body


# =========================
# LLM: extracción de placa y redacción
# =========================

async def extract_vehicle_data_chat(message: str) -> Dict[str, Any]:
    """
    Usa OpenAI para extraer campos (placa, marca, modelo, anio, color, otros) del texto libre del usuario.
    Retorna un dict con solo los campos presentes. Si no hay datos, retorna {}.
    """
    sys = (
        "Eres un extractor de datos. Devuelve sólo los campos presentes: "
        "placa, marca, modelo, anio, color, otros."
    )

    resp = client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        temperature=0,
        response_format=VehicleData,  # ← mapeo directo a Pydantic
        messages=[
            {"role": "system", "content": sys},
            {"role": "user", "content": message},
        ],
    )

    parsed: VehicleData = resp.choices[0].message.parsed
    return parsed.model_dump(exclude_none=True)


async def redactar_mensaje_deuda_whatsapp(deuda_item: Dict[str, Any]) -> str:
    """
    Envía al LLM los datos de deuda (un item de 'informacionDepartamental') y
    obtiene un texto corto (3–5 líneas) listo para WhatsApp.
    """
    guia = {
        "placa": deuda_item.get("placa", ""),
        "vigencia": deuda_item.get("vigencia", ""),
        "muniMatr": deuda_item.get("muniMatr", ""),
        "deptoMatr": deuda_item.get("deptoMatr", ""),
        "total": f"${format_cop(deuda_item.get('total', 0))}",
        "sancion": f"${format_cop(deuda_item.get('sancion', 0))}",
        "interes": f"${format_cop(deuda_item.get('interes', 0))}",
        "fechaLim": format_ddmmyyyy(deuda_item.get("fechaLim", "")),
    }

    user_text = (
        "Datos de liquidación (usa SOLO lo que veas, no inventes):\n"
        + json.dumps({**deuda_item, "_guia_formato": guia}, ensure_ascii=False)
    )

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[
            {"role": "system", "content": WHATSAPP_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
    )

    msg = (resp.choices[0].message.content or "").strip()
    return msg if msg else ""


# =========================
# Funciones principales (chat)
# =========================

async def chat_message_info(message: str) -> Dict[str, Any]:
    """
    Flujo para el primer mensaje del usuario:
      1) Extrae la placa del texto (LLM).
      2) Si no hay placa → retorna el mensaje de bienvenida pidiendo la placa.
      3) Consulta deuda por placa (API).
      4) Redacta el mensaje de WhatsApp con el resumen de deuda (LLM).
    Retorna: {"message": <texto_para_usuario>, "response": <item_deuda>}  o  {"message": INITIAL_MESSAGE}
    """
    data = await extract_vehicle_data_chat(message)

    placa = (data or {}).get("placa")
    if not placa:
        return {"message": INITIAL_MESSAGE}

    deuda = await consultar_deuda(placa)
    items = (deuda or {}).get("informacionDepartamental") or []
    if not items:
        return {"message": f"No encontré información de deuda para la placa {placa}. ¿Deseas intentar con otra placa?"}

    item = items[0]

    texto = await redactar_mensaje_deuda_whatsapp(item)
    if not texto:
        texto = (
            f"Hola, tu vehículo con placa {item.get('placa','')} tiene una vigencia hasta {item.get('vigencia','')}.\n"
            f"Matrícula: {item.get('muniMatr','')}, {item.get('deptoMatr','')}\n"
            "Importes:\n"
            f"• Sanción: ${format_cop(item.get('sancion', 0))}"
            + (f"\n• Interés: ${format_cop(item.get('interes', 0))}" if int(item.get('interes', 0)) > 0 else "")
            + (f"\n• Descuento: ${format_cop(item.get('descuento', 0))}" if int(item.get('descuento', 0)) > 0 else "")
            + (f"\n• Descuento sanción: ${format_cop(item.get('descSancion', 0))}" if int(item.get('descSancion', 0)) > 0 else "")
            + (f"\n• Descuento interés: ${format_cop(item.get('descInteres', 0))}" if int(item.get('descInteres', 0)) > 0 else "")
            + f"\n• Total: ${format_cop(item.get('total', 0))}\n"
            f"Fecha límite: {format_ddmmyyyy(item.get('fechaLim',''))}\n"
            "¡No olvides realizarlo a tiempo!\n"
        )

    return {"message": texto, "response": item}


async def chat_message_url(deuda_item: Dict[str, Any]) -> str:
    """
    Dado un item de 'informacionDepartamental' (placa, total, declaracion, etc.),
    crea la transacción y devuelve un mensaje con el enlace de pago.
    """
    res = await crear_transaccion(deuda_item)

    placa = deuda_item.get("placa", "")
    ref = res.get("paymentReference", "")
    tx  = res.get("transactionId", "")
    url = res.get("url", "")
    url_message = (
        f"¡Perfecto! Ya generé tu enlace de pago para la placa {placa}.\n"
        f"Referencia de pago: {ref}\n"
        f"Transacción: {tx}\n"
        f"Paga en línea aquí: {url}\n"
        "Gracias por usar nuestro servicio."
    )
    return url_message


async def validate_message(id_user: str, id_message: str) -> bool:
    """
    Retorna True si existe un mensaje con ese id para el usuario dado.
    Equivale a: chatMessages.findOne({ idUser, "messages.id": idMessage })
    """
    doc = await ChatMessages.find_one(
        {"idUser": id_user, "messages.id": id_message},
        {"_id": 1}  
    )
    return doc is not None
    
async def add_chat_messages(id_user: str, data_message: Dict[str, Any]) -> Dict[str, Any]:
    """
    Equivale a:
      - calcular dailyDate = (UTC - 5h).toISOString().split('T')[0]
      - si existe doc {idUser, date: dailyDate}: push message
      - si no existe: crear doc con messages=[message], date=dailyDat
    Retorna el documento guardado (dict).
    """
    message = dict(data_message)
    now_utc = datetime.utcnow()
    now_bog = now_utc - timedelta(hours=5)
    daily_date = now_bog.date().isoformat()
    existing = await ChatMessages.find_one({"idUser": id_user, "date": daily_date}, {"_id": 1})

    if existing:
        return existing  
    
    doc = ChatMessages(
        idUser = id_user,
        messages = [message],   
        date = daily_date
    )
    await doc.insert()
    return doc



async def create_report(id_user: str, payload: dict) -> Report:
    now_utc = datetime.utcnow()
    now_bog = now_utc - timedelta(hours=5)
    doc = Report(idUser=id_user, report=payload, date=now_bog)   
    await doc.insert()                              
    return doc

async def get_last_report_by_user(id_user: str) -> Optional[Report]:
    items = await (Report.find(Report.idUser == id_user)
                   .sort(-Report.date)  
                   .limit(1)
                   .to_list())
    return items[0] if items else None


async def send_message(business_phone_number_id: str, recipient_phone_number: str, text: str) -> Dict[str, Any]:
    """
    POST {GRAPH_API_URL}/{business_phone_number_id}/messages (requests, sync)
    Retorna:
      - {"dataMessage": <payload_enviado>, "sendMessage": <json_respuesta>} si OK
      - {"isError": True} si falla
    """
    url = f"{GRAPH_API_URL.rstrip('/')}/{business_phone_number_id}/messages"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GRAPH_API_TOKEN}",
    }
    data: Dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": recipient_phone_number,
        "type": "text",
        "text": {"body": text},
    }

    try:
        resp = requests.post(url, json=data, headers=headers, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text}
        return {"dataMessage": data, "sendMessage": body}
    except Exception:
        return {"isError": True}

async def send_message_info(business_phone_number_id: str, recipient_phone_number: str, text: str) -> Dict[str, Any]:
    """
    POST {GRAPH_API_URL}/{business_phone_number_id}/messages (requests, sync)
    Retorna:
      - {"dataMessage": <payload_enviado>, "sendMessage": <json_respuesta>} si OK
      - {"isError": True} si falla
    """
    url = f"{GRAPH_API_URL.rstrip('/')}/{business_phone_number_id}/messages"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GRAPH_API_TOKEN}",
    }
    data = {
        "messaging_product": "whatsapp",
        "to": recipient_phone_number,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": text
            },
            "footer": {
                "text": "¿Deseas generar el pago ahora?"
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "0",
                            "title": "❌"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "1",
                            "title": "✅"
                        }
                    }
                ]
            }
        }
    }

    try:
        resp = requests.post(url, json=data, headers=headers, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text}
        return {"dataMessage": data, "sendMessage": body}
    except Exception:
        return {"isError": True}




# --------------------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------------------

async def handle_text(message: Dict[str, Any], business_phone_number_id: str):
    info = await chat_message_info(message["text"]["body"])
    resp = info.get("response")
    text = info.get("message")
    if resp:
        await send_message_info(
        business_phone_number_id,
        message.get("from"),
        text
        )
        await create_report(message.get("from"), resp)
    else:
        await send_message(
            business_phone_number_id,
            message.get("from"),
            text
        )
     
    
async def handle_interactive(message: Dict[str, Any], business_phone_number_id: str):
    if message["interactive"]["button_reply"]["id"] == "1":
        report =  await get_last_report_by_user(message.get("from"))
        message_url = await chat_message_info(report["report"])
        await send_message(
            business_phone_number_id,
            message.get("from"),
            message_url
        )
    else:
        await send_message(
            business_phone_number_id,
            message.get("from"),
            "Hecho. ¿Quieres hacer otra consulta?"
        )


async def handle_audio(message: Dict[str, Any], business_phone_number_id: str):
    await send_message(
            business_phone_number_id,
            message.get("from"),
            "Por ahora no podemos procesar audios 🙏. Envíame tu consulta en texto por favor"
        )

async def handle_default(message: Dict[str, Any], business_phone_number_id: str):
    await send_message(
        business_phone_number_id, 
        message.get("from"),
        "¿En qué más te puedo ayudar? 🤔"
    )
    
# --------------------------------------------------------------------------------------
# Export: igual a tu objeto messageHandlers de Node
# --------------------------------------------------------------------------------------

message_handlers = {
    "text": handle_text,
    "interactive": handle_interactive,
    "audio": handle_audio,
    "default": handle_default,
}


