FROM alpine/git:v2.52.0 AS download

WORKDIR /app

# Installing git-xet (HuggingFace's custom GIT-LFS replacement)
RUN curl --proto '=https' --tlsv1.2 -sSf https://raw.githubusercontent.com/huggingface/xet-core/refs/heads/main/git_xet/install.sh | sh

# Pre-downloading HuggingFace Model to save time when backend service starts
RUN git clone https://huggingface.co/ProsusAI/finbert finbert


FROM python:3.11-slim AS production

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    chromium \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Copying HuggingFace model from the "download" stage into this stage
COPY --from=download /app/finbert /app/finbert

# Install uv to speed up pip installation
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY requirements-runtime.txt requirements-api.txt requirements-analysis.txt \
    requirements-scraper.txt requirements-dev.txt .

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV UV_LINK_MODE=copy

# Installs the same pinned versions as the split Lambda requirements files
# (requirements-api/analysis/scraper/runtime.txt), plus local-only extras
# (uvicorn, alembic) — see requirements-dev.txt. This keeps local dev from
# drifting away from what actually deploys.
#
# torch is installed separately from the CPU-only wheel index first (matching
# Dockerfile.analysis) so `uv pip install -r requirements-dev.txt` doesn't
# resolve the much larger default CUDA-enabled wheel from PyPI.
RUN --mount=type=cache,target=/root/.cache/uv uv pip install --system \
    --index-url https://download.pytorch.org/whl/cpu \
    torch==2.13.0
RUN --mount=type=cache,target=/root/.cache/uv uv pip install --system -r requirements-dev.txt

# RapidOCR declares desktop OpenCV, which expects X11 libraries this slim
# image doesn't have. Replace it with the headless wheel (matching
# Dockerfile.analysis) so `import cv2` doesn't fail at runtime.
RUN --mount=type=cache,target=/root/.cache/uv uv pip uninstall --system opencv-python \
    && uv pip install --system --no-deps opencv-python-headless==5.0.0.93

RUN --mount=type=cache,target=/root/.cache/ms-playwright playwright install chromium

COPY . .

FROM production AS testing

COPY requirements-testing.txt .

# Using cache to reduce build time incase requirements change
RUN --mount=type=cache,target=/root/.cache/uv uv pip install --system -r requirements-testing.txt
