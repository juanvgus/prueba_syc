from __future__ import annotations
from datetime import datetime
from typing import Optional
from beanie import Document
from pydantic import Field

class User(Document):
    idUser: Optional[str] = None
    uid: Optional[str] = None
    