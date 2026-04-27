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
    && rm -rf /var/lib/apt/lists/*

# Copying HuggingFace model from the "download" stage into this stage
COPY --from=download /app/finbert /app/finbert

# Install uv to speed up pip installation
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY requirements.txt .

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Use uv to install requirements (improves parallelism)
# Using cache to reduce build time incase requirements change
RUN --mount=type=cache,target=/root/.cache/uv uv pip install --system -r requirements.txt
RUN --mount=type=cache,target=/root/.cache/ms-playwright playwright install chromium

COPY . .

FROM production AS testing

COPY requirements-testing.txt .

# Using cache to reduce build time incase requirements change
RUN --mount=type=cache,target=/root/.cache/uv uv pip install --system -r requirements-testing.txt
