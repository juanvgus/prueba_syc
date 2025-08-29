import os
import requests
from typing import Any, Dict

BASE_URL = os.getenv("NEXT_PUBLIC_TOTAL_SCI_API_URL", "")
UAPI = os.getenv("UAPI", "")
PAPI = os.getenv("PAPI", "")

class SciApiError(Exception):
    pass

def authenticate(username: str | None = None, password: str | None = None) -> str:
    """
    POST /Autenticacion
    Content-Type: application/x-www-form-urlencoded
    Retorna el token (string) o lanza SciApiError si falla.
    """
    username = username or UAPI
    password = password or PAPI

    url = f"{BASE_URL}/Autenticacion"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {"Username": username, "Password": password}

    resp = requests.post(url, headers=headers, data=data, timeout=30)
    resp.raise_for_status()
    body = resp.json()

    token = body.get("token")
    if not token or body.get("response", {}).get("errorCount", 0) != 0 and not token:
        raise SciApiError(f"Fallo autenticación: {body}")
    return token


def crear_transaccion(payload: Dict[str, Any],
                      username: str | None = None,
                      password: str | None = None) -> Dict[str, Any]:
    """
    POST /TotalApp/CrearTransaccion
    Content-Type: application/json
    Llama authenticate() para obtener el Bearer token y crea la transacción.
    payload: debe contener las claves según el API (email, valorTotal, iva, descripcionPago,
             idParametro, idCliente, dispersion[], paymentId, etc.)
    """
    token = authenticate(username, password)
    url = f"{BASE_URL}/TotalApp/CrearTransaccion"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    body = resp.json()

    if body.get("response", {}).get("errorCount", 0) != 0:
        raise SciApiError(f"Error al crear transacción: {body}")
    return body


def consultar_deuda(placa: str,
                    id_cliente: str = "127",
                    username: str | None = None,
                    password: str | None = None) -> Dict[str, Any]:
    """
    POST /TotalApp/DeudaPlaca/127
    Content-Type: application/json
    Llama authenticate() para obtener el Bearer token y consulta la deuda por placa (o DNI).
    """
    token = authenticate(username, password)
    url = f"{BASE_URL}/TotalApp/DeudaPlaca/127"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"idCliente": id_cliente, "placa": placa}

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    body = resp.json()

    if body.get("response", {}).get("errorCount", 0) != 0:
        raise SciApiError(f"Error al consultar deuda: {body}")
    return body

