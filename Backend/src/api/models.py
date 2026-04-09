from typing import Optional
from pydantic import BaseModel


class ResetRequest(BaseModel):
    confirmation: str
    secret_key: Optional[str] = None


class AiSettingsUpdate(BaseModel):
    enabled: bool


class BorrowRequest(BaseModel):
    amount: int


class OverrideRequest(BaseModel):
    session_id: int
    override: bool
    secret_key: Optional[str] = None


class PrismaSettingsUpdate(BaseModel):
    ensemble_enabled: bool

class AuditTriggerRequest(BaseModel):
    journee: Optional[int] = None
    secret_key: Optional[str] = None
