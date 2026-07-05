"""API: /api/v1/export/{format} — экспорт ответа Q&A."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.v1.ask import get_answer
from app.services.export_service import ExportService

router = APIRouter()


class ExportRequest(BaseModel):
    answer_id: str


@router.post("/markdown")
def export_markdown(req: ExportRequest):
    ans = get_answer(req.answer_id)
    if not ans:
        raise HTTPException(status_code=404, detail="Answer not found")
    md = ExportService().to_markdown(ans)
    return Response(
        content=md, media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="answer_{req.answer_id[:12]}.md"'},
    )


@router.post("/jsonld")
def export_jsonld(req: ExportRequest):
    ans = get_answer(req.answer_id)
    if not ans:
        raise HTTPException(status_code=404, detail="Answer not found")
    obj = ExportService().to_jsonld(ans)
    return Response(
        content=json.dumps(obj, ensure_ascii=False, indent=2),
        media_type="application/ld+json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="answer_{req.answer_id[:12]}.jsonld"'},
    )


@router.post("/pdf")
def export_pdf(req: ExportRequest):
    ans = get_answer(req.answer_id)
    if not ans:
        raise HTTPException(status_code=404, detail="Answer not found")
    pdf_bytes = ExportService().to_pdf_stream(ans)
    if not pdf_bytes:
        raise HTTPException(status_code=501, detail="reportlab не установлен")
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="answer_{req.answer_id[:12]}.pdf"'},
    )
