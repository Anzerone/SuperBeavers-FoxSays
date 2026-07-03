FROM python:3.11-slim

WORKDIR /app

# --- Опциональное ускорение apt через зеркало Debian ---------------------
# Дефолтное deb.debian.org иногда даёт очень медленный узел (35 КБ/с).
# Передай быстрое зеркало:  docker compose build --build-arg APT_MIRROR=https://mirror.yandex.ru
#   RU:  https://mirror.yandex.ru            CN:  https://mirrors.tuna.tsinghua.edu.cn
ARG APT_MIRROR=""
RUN if [ -n "$APT_MIRROR" ]; then \
      sed -i "s|http://deb.debian.org|$APT_MIRROR|g; s|https://deb.debian.org|$APT_MIRROR|g; s|http://security.debian.org|$APT_MIRROR|g" \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
      sed -i "s|http://deb.debian.org|$APT_MIRROR|g; s|http://security.debian.org|$APT_MIRROR|g" \
        /etc/apt/sources.list 2>/dev/null || true; \
    fi

# --- Системные зависимости ----------------------------------------------
#   unar          — .rar и многотомные архивы реального корпуса
#   libreoffice-* — надёжное извлечение старых бинарных .doc / .ppt / .xls
#                   (в т.ч. кириллицы); .xls также читается через xlrd
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        unar \
        libreoffice-writer \
        libreoffice-calc \
        libreoffice-impress \
        fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
# Быстрый индекс pip (pypi.org бывает 15 КБ/с). CN: https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=""
RUN pip install --no-cache-dir ${PIP_INDEX_URL:+--index-url $PIP_INDEX_URL} --upgrade pip && \
    pip install --no-cache-dir ${PIP_INDEX_URL:+--index-url $PIP_INDEX_URL} \
        "fastapi>=0.115.0" \
        "uvicorn[standard]>=0.32.0" \
        "pydantic>=2.9.0" \
        "pydantic-settings>=2.5.0" \
        "httpx>=0.27.0" \
        "neo4j>=5.25.0" \
        "loguru>=0.7.2" \
        "python-multipart>=0.0.12" \
        "qdrant-client>=1.12.0" \
        "fastembed>=0.4.1" \
        "numpy>=1.26.0" \
        "pandas>=2.2.0" \
        "openpyxl>=3.1.5" \
        "xlrd>=2.0.1" \
        "pdfplumber>=0.11.4" \
        "python-docx>=1.1.2" \
        "python-pptx>=1.0.2" \
        "trafilatura>=1.12.2" \
        "rapidfuzz>=3.10.0" \
        "websockets>=13.0" \
        "reportlab>=4.2.0" \
        "rarfile>=4.2" \
        "patool>=2.4.0"

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
