"""API: POST /api/v1/compare — сравнение двух опций."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.compare_service import CompareService

router = APIRouter()


class Option(BaseModel):
    kind: str  # 'material' | 'mode'
    code: str


class CompareRequest(BaseModel):
    a: Option
    b: Option


@router.post("")
def compare(req: CompareRequest):
    svc = CompareService()
    return svc.compare_options(req.a.model_dump(), req.b.model_dump())
