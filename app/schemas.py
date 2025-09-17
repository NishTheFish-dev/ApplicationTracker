from __future__ import annotations
from typing import Optional
from datetime import date
from pydantic import BaseModel, ConfigDict
from .domain import Status


class JobApplicationCreate(BaseModel):
    title: str
    employer: str
    source_url: str
    status: Status = Status.applied
    date_applied: Optional[date] = None


class JobApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    employer: str
    status: Status
    date_applied: Optional[date]
    source_url: str
