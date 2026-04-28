from __future__ import annotations

from pydantic import BaseModel


class DataCompletenessWarning(BaseModel):
    field: str
    message: str
    severity: str = "warning"


class ApiMessage(BaseModel):
    message: str
