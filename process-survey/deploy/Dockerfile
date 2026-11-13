# Образ опроса «Карта процессов Balkan» для Linux-сервера.
# Код НЕ запекается: монтируется из /opt/balkan-opros (обновление кода = rsync + restart).
FROM python:3.12-slim

# poppler-utils: pdftotext/pdftoppm для PDF без текстового слоя pypdf.
# Код ищет их по пути Homebrew (/opt/homebrew/bin) — даём симлинки, код не меняем.
RUN apt-get update \
 && apt-get install -y --no-install-recommends poppler-utils curl \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /opt/homebrew/bin \
 && ln -s /usr/bin/pdftotext /opt/homebrew/bin/pdftotext \
 && ln -s /usr/bin/pdftoppm /opt/homebrew/bin/pdftoppm

# Версии — как на Mac (Python 3.12 Framework), где проект отлажен.
RUN pip install --no-cache-dir certifi==2025.8.3 openpyxl==3.1.5 pandas==2.3.2 pypdf==6.9.2 \
    python-docx==1.2.0 xlrd==2.0.2

RUN useradd -u 10001 -M -d /app -s /usr/sbin/nologin survey
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
USER survey
CMD ["python3", "/deploy/run.py"]
