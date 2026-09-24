# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# FASHN VTON v1.5 for PAI-EAS.
#
# Base image note: the brief suggested `12.1.1-runtime`, and this uses
# `12.1.1-cudnn8-runtime` instead. onnxruntime-gpu links against system cuDNN
# (unlike torch, which bundles its own), and DWPose pose estimation runs on
# ONNX Runtime -- on the plain runtime image every request fails at
# `CUDAExecutionProvider` load with a missing libcudnn. If you move to
# onnxruntime-gpu >= 1.20, switch this tag to `cudnn9-runtime` to match.
#
# Two stages: a builder that resolves wheels and pre-fetches the human-parser
# weights, and a slim runtime that carries neither pip cache nor build tools.
# ---------------------------------------------------------------------------
ARG CUDA_IMAGE=nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

FROM ${CUDA_IMAGE} AS builder

ARG FASHN_VTON_REF=main
ARG TORCH_VERSION=2.4.1
ARG TORCHVISION_VERSION=0.19.1
ARG ORT_VERSION=1.18.1

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3.10-venv python3-pip git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN python3.10 -m venv "$VIRTUAL_ENV" && pip install --upgrade pip setuptools wheel

# Torch first, from the cu121 index, so nothing downstream can pull a wheel
# built against a different CUDA minor.
RUN pip install \
        --index-url https://download.pytorch.org/whl/cu121 \
        "torch==${TORCH_VERSION}" "torchvision==${TORCHVISION_VERSION}"

# Pinned before fashn-vton, whose own constraint (>=1.14.0) is satisfied by
# this and so leaves it untouched.
RUN pip install "onnxruntime-gpu==${ORT_VERSION}"

# The serving layer. httpx does the URL fetches, python-multipart the uploads.
RUN pip install \
        "fastapi==0.115.6" \
        "uvicorn[standard]==0.34.0" \
        "pydantic==2.10.4" \
        "httpx==0.28.1" \
        "python-multipart==0.0.20"

# fashn-vton is installed from the tagged source rather than PyPI so the ref is
# explicit and reproducible; override FASHN_VTON_REF with a commit SHA to pin
# harder than a moving branch.
RUN pip install "git+https://github.com/fashn-AI/fashn-vton-1.5.git@${FASHN_VTON_REF}"

# Bake the human-parser weights (~244 MB) into the image.
#
# This is the single most important line for scale-to-zero economics. The
# parser downloads itself from the Hub on first use, so without this every
# cold-started replica would reach out to huggingface.co before it could serve
# -- adding latency, and turning an external outage into a hard dependency of
# your own service. The 2 GB of VTON + DWPose weights stay on OSS (too large to
# want in every image pull); this 244 MB does not.
ENV HF_HOME=/opt/hf
RUN python -c "\
from huggingface_hub import snapshot_download; \
snapshot_download('fashn-ai/fashn-human-parser'); \
print('human-parser weights cached')"


# --------------------------------------------------------------- runtime
FROM ${CUDA_IMAGE} AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    WEIGHTS_DIR=/mnt/models \
    PORT=8000 \
    OMP_NUM_THREADS=8 \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# libgl1/libglib2.0-0 are opencv-python's runtime shared libraries; without
# them `import cv2` fails inside the pipeline. libgomp1 is for torch's OpenMP.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 libgl1 libglib2.0-0 libgomp1 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin vton

COPY --from=builder --chown=root:root /opt/venv /opt/venv
COPY --from=builder --chown=root:root /opt/hf /opt/hf

WORKDIR /app
COPY --chown=root:root app.py /app/app.py

# Read-only code and weights, owned by root, executed as an unprivileged user.
RUN chmod -R a-w /app /opt/venv /opt/hf
USER 10001

EXPOSE 8000

# Informational for `docker run`; EAS applies its own probe against the
# container port and ignores this directive.
HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# Uvicorn directly, single worker: one process owns the GPU and the pipeline.
# Weights load in the lifespan handler, so the socket does not accept until the
# model is ready -- which is what makes the EAS port probe meaningful.
ENTRYPOINT ["uvicorn", "app:app", \
    "--host", "0.0.0.0", \
    "--port", "8000", \
    "--workers", "1", \
    "--timeout-keep-alive", "620", \
    "--no-access-log"]
