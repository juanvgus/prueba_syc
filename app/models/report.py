# models/chat_messages.py
from __future__ import annotations
from datetime import datetime
from typing import Any, Optional, List, Dict
from beanie import Document
from pydantic import Field

class Report(Document):
    idUser: Optional[str] = None
    report: Dict[str, Any] = Field(default_factory=dict)
    date: Optional[datetime] = None