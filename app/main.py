import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from prueba_syc.app.routes.meta_route import router as meta_router
from prueba_syc.app.database.db import init_db, close_db

# -------- Env & logging --------
PORT = int(os.getenv("PORTAPI", "8000"))

# "120/minute", "100/second", "1000/day", etc.
DEFAULT_LIMIT = os.getenv("RATE_LIMIT_DEFAULT", "120/minute").strip()

# Coma-separado o "*"
ALLOWED_ORIGINS_ENV = os.getenv("ALLOWED_ORIGINS", "*").strip()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="TOTAL WhatsApp Webhook (FastAPI)")

# -------- Startup / Shutdown --------
@app.on_event("startup")
async def on_startup():
    await init_db()  # imprime "Connected database" si OK

@app.on_event("shutdown")
async def on_shutdown():
    await close_db()

# -------- Rate limiting --------
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[DEFAULT_LIMIT] if DEFAULT_LIMIT else None
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# -------- CORS --------
if ALLOWED_ORIGINS_ENV == "*":
    allow_origins = ["*"]
    allow_credentials = False  # con "*" no se debe permitir credenciales
else:
    allow_origins = [o.strip() for o in ALLOWED_ORIGINS_ENV.split(",") if o.strip()]
    allow_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------- Rutas --------
app.include_router(meta_router, prefix="/api")
