"""Synthesizer: подграф экспериментов + чанки документов → стримящийся ответ LLM."""

from __future__ import annotations

from loguru import logger

from app.prompts import synthesizer as syn_prompts
from app.services.llm_service import LLMService
from app.services.rag_service import RAGService


class Synthesizer:
    def __init__(self, llm: LLMService, rag: RAGService):
        self.llm = llm
        self.rag = rag

    async def synthesize_stream(self, question, intent, experiments, top_chunks=5):
        """Возвращает (chunks_used, async-генератор токенов ответа)."""
        # Для «Обзор…»-запросов расширяем контекст: 8 чанков вместо 5 —
        # обзор нельзя написать по одному фрагменту.
        intent_kind = (intent or {}).get("intent")
        if intent_kind == "literature_review":
            top_chunks = 10
        elif intent_kind == "comparison":
            top_chunks = 8

        chunks = []
        try:
            # Всегда сначала — глобальный семантический поиск. doc_filter по
            # экспериментам мешал: когда structural-match возвращал ~30 нерелевантных
            # экспериментов, filter отсекал именно те чанки, которые реально
            # нужны. Экспериментальные doc_id используем как boost, но не как
            # обязательный фильтр.
            chunks = self.rag.search_chunks(question, top_k=top_chunks)
        except Exception as e:
            logger.warning(f"RAG search failed: {e}")

        # Ранний выход: если ни экспериментов, ни чанков — LLM всё равно
        # не сможет ничего сказать, кроме галлюцинаций и сырых ID (видели
        # такое в проде). Отдаём короткое честное сообщение, не дёргаем модель.
        no_context = not experiments and not chunks
        if no_context:
            msg = (
                "В корпусе не нашлось релевантных экспериментов и фрагментов "
                "документов по этому запросу. Уточните формулировку — например, "
                "укажите материал (медный концентрат, никелевый штейн), процесс "
                "(выщелачивание, плавка, флотация) или измеряемое свойство "
                "(извлечение, содержание, прочность)."
            )

            async def empty_stream():
                yield msg

            return chunks, empty_stream

        prompt = syn_prompts.build_prompt(question, experiments, chunks, intent)

        async def token_stream():
            async for tok in self.llm.generate_stream(prompt, system=syn_prompts.SYSTEM):
                yield tok

        return chunks, token_stream
