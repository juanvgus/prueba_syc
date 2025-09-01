# prueba\_syc – API de asistencia vehicular (FastAPI + WhatsApp + SCI TOTAL)

Asistente para consulta de deudas vehiculares y generación de enlaces de pago. Orquesta:

* **FastAPI** como backend (async)
* **WhatsApp Cloud API** para mensajería (texto e **botón CTA URL**)
* **SCI TOTAL** (Autenticación y **CrearTransacción**)
* **MongoDB + Beanie** para persistencia
* **Nginx** como reverse proxy + **Certbot** para HTTPS

---

## TL;DR

* Recibe mensajes por **webhook** de WhatsApp
* Extrae/valida datos (placa, deuda, etc.)
* Llama a SCI TOTAL → genera **transacción** y obtiene **URL de pago**
* Envía al usuario un **mensaje interactivo** con **botón “Pagar ahora”**
* Guarda **conversaciones** y **reportes** en MongoDB

---

## Arquitectura

```
Usuario WA  →  WhatsApp Cloud API →  /api/webhookMeta/webhookMessage (GET/POST)
                                          │
                                          ▼
                                       FastAPI
                                 ┌────────┴─────────┐
                                 │  Controllers     │
                                 │  message_handlers│
                                 └────────┬─────────┘
                                          │
                 ┌─────────────────────────┼─────────────────────────┐
                 ▼                         ▼                         ▼
           SCI TOTAL API             MongoDB/Beanie            WhatsApp Send API
        (Autenticación,             (ChatMessages,            (CTA URL / Templates)
        CrearTransacción)             Report, ShortLink)
```

---

## Tech stack

* Python 3.11+, FastAPI, Uvicorn, httpx/requests
* MongoDB 6+, Motor + Beanie (ODM)
* Nginx (reverse proxy) + Certbot (Let’s Encrypt)
* Docker / Docker Compose

---

## Variables de entorno (.env)

Ejemplo recomendado:

```bash
# === App ===
APP_ENV=prod
HTTP_TIMEOUT=15
TZ=America/Bogota

# === MongoDB ===
MONGODB_URI=mongodb://mongodb:27017
DB_NAME=prueba_syc

# === WhatsApp Cloud API ===
GRAPH_API_URL=https://graph.facebook.com/v22.0
GRAPH_API_TOKEN=<TOKEN_LARGO_O_DE_DESARROLLO>
BUSINESS_PHONE_NUMBER_ID=<PHONE_NUMBER_ID>

# === SCI TOTAL ===
NEXT_PUBLIC_TOTAL_SCI_API_URL=http://pagossi.sycpruebas.com/SCITOTAL

# === Nginx/Certbot (deploy) ===
DOMAIN=chatbotbga.online
EMAIL=tu-correo@dominio.com
```

> Nota: para WhatsApp usa un **token de larga duración** (rotación cada \~60 días) o un mecanismo de refresco.

---

## Estructura del proyecto (sugerida)

```
app/
  main.py
  routes/
    meta_route.py
  controllers/
    meta_controller.py
  utilities/
    functions.py              # validate_message, add_chat_messages, message_handlers, senders
  models/
    ChatMessages.py
    report.py

nginx/
  nginx.conf                  # reverse proxy a backend:8000

certbot/
  # webroot para desafíos ACME (.well-known)

docker-compose.yml
requirements.txt
README.md
```

---

## Modelos (MongoDB + Beanie)

### ChatMessages

Guarda el historial de mensajes por usuario.

```python
# models/ChatMessages.py
from __future__ import annotations
from datetime import datetime
from typing import Any, Optional, List, Dict
from beanie import Document
from pydantic import Field

class ChatMessages(Document):
    idUser: Optional[str] = None
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    date: Optional[datetime] = None
```

### Report

Guarda payloads de resultado (p.ej. deuda, totales, link, etc.).

```python
# models/report.py
from __future__ import annotations
from datetime import datetime
from typing import Any, Optional, Dict
from beanie import Document
from pydantic import Field

class Report(Document):
    idUser: Optional[str] = None
    report: Dict[str, Any] = Field(default_factory=dict)
    date: Optional[datetime] = None  
```

**Payload de ejemplo** (deuda):

```json
{
  "placa": "HHO137",
  "declaracion": 108818889,
  "vigencia": 2025,
  "codiMuniMatr": "307",
  "codiDeptoMatr": "68",
  "muniMatr": "GIRON",
  "deptoMatr": "SANTANDER",
  "avaluo": 49116000,
  "impto": 737000,
  "sancion": 184000,
  "interes": 0,
  "saldoPagar": 921000,
  "total": 954688,
  "codiMuniDest": "655",
  "codiDeptoDest": "68",
  "muniDest": "SABANA DE TORRES",
  "deptoDest": "SANTANDER",
  "valorMuni": 184200,
  "valorDepto": 736800,
  "fechaLim": "2025-09-01T00:00:00"
}
```

**Respuesta de transacción (ejemplo real recortado):**

```json
{
  "transactionId": "40037",
  "url": "https://backendpruebas.vepay.com.co/...",
  "paymentId": "40037",
  "sciPaymentId": 5562812,
  "sciTransactionId": 20566,
  "paymentReference": "127-196629",
  "response": {"errors": 0, "description": ["SCI: OK", "Pasarela:  - OK", "Dispersion: @OK"]}
}
```

---

## Nginx + Certbot (deploy)

* **Nginx**: proxy a `backend:8000`, sirve `/.well-known/acme-challenge/` desde un `webroot` para Certbot.
* **Certbot**: `certonly --webroot` con `-w /var/www/certbot -d $DOMAIN`.
* Asegura **DNS A** apuntando a tu EC2 y **Security Group** con 80/443 abiertos.

**docker-compose.yml (ejemplo mínimo)**

```yamlservices:
  backend:
    build: .
    container_name: prueba_syc-backend
    restart: unless-stopped
    env_file:
      - .env
    depends_on:
      - mongodb
    environment:
      - MONGODB_URI=${MONGODB_URI:-mongodb://mongodb:27017/chatbotCB}
      - MONGODB_DB=${MONGODB_DB:-chatbotCB}
      - PORTAPI=${PORTAPI:-8000}
      - PYTHONPATH=/usr/src/app
    expose:
      - "8000"
    command: uvicorn app.main:app --host 0.0.0.0 --port ${PORTAPI:-8000}
    

  nginx:
    image: nginx:alpine
    container_name: prueba_syc-nginx
    depends_on:
      - backend
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    environment:
      - DOMAIN=${DOMAIN}          
    volumes:
      - ./nginx/default.conf.template:/etc/nginx/templates/default.conf.template:ro
      - certbot_webroot:/var/www/certbot
      - letsencrypt:/etc/letsencrypt

  certbot:
    image: certbot/certbot:latest
    container_name: prueba_syc-certbot
    volumes:
      - certbot_webroot:/var/www/certbot
      - letsencrypt:/etc/letsencrypt

  mongodb:
    image: mongo:6
    container_name: prueba_syc-mongodb
    restart: unless-stopped
    ports:
      - "127.0.0.1:27017:27017"
    volumes:
      - mongo_data:/data/db
    command: ["--bind_ip_all"]

volumes:
  letsencrypt:
  certbot_webroot:
  mongo_data:

```

**Comandos útiles**

```bash
docker compose up -d --build
docker compose logs -f backend
# emitir cert inicialmente
docker compose run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  -d "$DOMAIN" --email "$EMAIL" --agree-tos --no-eff-email
```

---
