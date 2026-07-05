"""Loader онлайн-ресурсов через trafilatura (лучше BeautifulSoup для основного текста)."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from loguru import logger

from app.config import settings


def url_hash(url):
    return hashlib.sha1(url.strip().encode("utf-8")).hexdigest()


def stable_web_id(url):
    return "WEB-" + url_hash(url)[:12].upper()


def fetch_and_extract(url, timeout=15):
    """Скачивает URL, вытаскивает основной текст. Возвращает {url, title, text}
    или None при ошибке."""
    try:
        import trafilatura
    except ImportError:
        logger.warning("trafilatura not installed")
        return None
    try:
        downloaded = trafilatura.fetch_url(url, no_ssl=False)
        if not downloaded:
            logger.warning(f"Failed to fetch {url}")
            return None
        # extract вернёт основной текст без навигации / рекламы
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
        # metadata: title, author, date
        meta = trafilatura.extract_metadata(downloaded)
        title = (meta.title if meta else None) or url
        return {"url": url, "title": title, "text": text or ""}
    except Exception as e:
        logger.warning(f"trafilatura failed for {url}: {e}")
        return None


def load_web_resource(url):
    """Возвращает документ-подобную структуру (совместимо с documents.iter_chunks)."""
    r = fetch_and_extract(url)
    if not r or not r.get("text"):
        return None
    return {
        "doc_id": stable_web_id(url),
        "file_path": url,
        "title": r["title"],
        "kind": "web",
        "url": url,
        "pages": [(1, r["text"])],
    }


def iter_web_resources(corpus_dir):
    """Читает `data/corpus/web_urls.txt` (по одному URL в строке, # для комментов)
    и отдаёт документы."""
    p = Path(corpus_dir) / "web_urls.txt"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        url = line.strip()
        if not url or url.startswith("#"):
            continue
        doc = load_web_resource(url)
        if doc:
            yield doc
