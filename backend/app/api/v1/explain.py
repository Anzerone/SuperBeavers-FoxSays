"""API: POST /api/v1/explain/edge — LLM-объяснение ребра (SSE)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.prompts import explain as prompts
from app.services.llm_service import LLMService

router = APIRouter()


class ExplainEdgeRequest(BaseModel):
    src: dict
    dst: dict
    edge_type: str
    extra: dict | None = None


@router.post("/edge")
async def explain_edge(req: ExplainEdgeRequest):
    llm = LLMService()
    prompt = prompts.build_prompt(req.edge_type, req.src, req.dst, extra=req.extra)

    async def stream():
        try:
            async for tok in llm.generate_stream(prompt, system=prompts.SYSTEM):
                safe = tok.replace("\r", "").replace("\n", "\\n")
                yield f"data: {safe}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            await llm.close()

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/availability")
async def availability():
    llm = LLMService()
    try:
        return {"available": await llm.is_available()}
    finally:
        await llm.close()
