from typing import Optional
from pydantic import BaseModel


class ResetRequest(BaseModel):
    confirmation: str


class AiSettingsUpdate(BaseModel):
    enabled: bool


class BorrowRequest(BaseModel):
    amount: int


class OverrideRequest(BaseModel):
    session_id: int
    override: bool


class PrismaSettingsUpdate(BaseModel):
    ensemble_enabled: bool

class AuditTriggerRequest(BaseModel):
    journee: Optional[int] = None


class ForceTrainingRequest(BaseModel):
    force: bool = True
    steps: Optional[list] = None
