FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/models

# tesseract (+ Hindi/Marathi packs) for OCR, ffmpeg for audio, espeak-ng + libsndfile for Kokoro
RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-mar \
      ffmpeg espeak-ng libsndfile1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only PyTorch first (much smaller than the default CUDA wheel). For GPU, remove the --index-url flag.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt requirements-tts.txt ./
RUN pip install -r requirements.txt -r requirements-tts.txt

COPY . .
RUN useradd -m app && mkdir -p /data /models && chown -R app:app /app /data /models
USER app

EXPOSE 8000
# Migrations run on start-up of the API container; the worker overrides CMD (see docker-compose.yml)
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
