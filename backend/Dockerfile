# HindiDub backend - runs as-is on a free Hugging Face Docker Space (CPU),
# or anywhere with Docker (add --gpus all and HD_DEVICE=cuda for a GPU box).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    COQUI_TOS_AGREED=1 \
    HF_HOME=/home/user/.cache/huggingface \
    TORCH_HOME=/home/user/.cache/torch \
    HD_DATA_DIR=/home/user/data

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg rubberband-cli libsndfile1 git build-essential \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces run the container as uid 1000.
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
RUN pip install torch==2.5.1 torchaudio==2.5.1 --index-url ${TORCH_INDEX}
COPY requirements.txt .
RUN pip install -r requirements.txt \
    && pip install --no-deps demucs==4.0.1 \
    && pip install dora-search==0.1.12 einops julius==0.2.7 lameenc openunmix==1.3.0 pyyaml tqdm

COPY --chown=user app ./app
COPY --chown=user scripts ./scripts
USER user

# Download all free models into the image so the first job starts immediately.
ARG PREFETCH=1
RUN if [ "$PREFETCH" = "1" ]; then python scripts/prefetch_models.py; fi

EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--timeout-keep-alive", "120"]
