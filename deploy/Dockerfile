# CPU-only Laya typed-decision service.
#
# Two deliberate choices:
#   1. torch comes from the CPU wheel index. The default wheel bundles ~2.5 GB of
#      CUDA libraries that can never be used here.
#   2. The checkpoint is baked into the image. Downloading 843 MB on every cold
#      start would dominate startup and make scale-to-zero painful.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf \
    LAYA_DEVICE=cpu

WORKDIR /app

COPY deploy/requirements-cpu.txt .

RUN pip install --no-cache-dir \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements-cpu.txt

# Bake the checkpoint in so cold start does not pay for the download.
ARG LAYA_MODEL=convaiinnovations/laya-typed-decisions
ENV LAYA_MODEL=${LAYA_MODEL}
RUN python -c "from huggingface_hub import snapshot_download; \
    snapshot_download('${LAYA_MODEL}')" && \
    find /opt/hf -name '*.h5' -delete 2>/dev/null || true

COPY deploy/laya_service.py /app/laya_service.py

# Thread caps. Oversubscription measured 2.5x slower than 8 threads on this
# model; the OMP/MKL variables stop the BLAS layer re-expanding underneath torch.
ENV LAYA_CPU_THREADS=8 \
    OMP_NUM_THREADS=8 \
    MKL_NUM_THREADS=8

RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app /opt/hf
USER appuser

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health').status==200 else 1)"

CMD ["uvicorn", "laya_service:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
