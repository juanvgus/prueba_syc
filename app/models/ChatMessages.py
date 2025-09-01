from __future__ import annotations
from datetime import datetime
from typing import Any, Optional, List, Dict
from beanie import Document
from pydantic import Field

class ChatMessages(Document):
    idUser: Optional[str] = None
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    date: Optional[datetime] = None
