"""API: /api/v1/versions — история версий факта (material × property)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.versioning_service import VersioningService

router = APIRouter()


@router.get("/{material_code}/{property_code}")
async def fact_history(material_code, property_code, limit: int = Query(50, ge=1, le=200)):
    """Возвращает все версии измерения свойства для материала,
    отсортированные от новейшего к самому старому. is_current=true — актуальная.
    """
    return VersioningService().history(material_code, property_code, limit=limit)
