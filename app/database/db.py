import os
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from app.models.user import User
from app.models.ChatMessages import ChatMessages

MONGO_DB_URI = os.getenv("MONGO_DB_URI")

_client: AsyncIOMotorClient | None = None

async def init_db() -> None:
    """
    Conecta a MongoDB y prepara Beanie.
    Lanza excepción si no puede conectarse.
    """
    global _client
    _client = AsyncIOMotorClient(MONGO_DB_URI)

    db = _client.get_default_database()
    # Verifica conexión (equivalente a un "ping")
    await db.command("ping")

    # Registra tus modelos Beanie
    await init_beanie(database=db, document_models=[User, ChatMessages])

    print("Connected database")

async def close_db() -> None:
    global _client
    if _client:
        _client.close()
        _client = None
