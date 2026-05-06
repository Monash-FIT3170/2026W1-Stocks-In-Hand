FROM python:3.11-slim

# System deps first — Playwright needs these present before pip install
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    gnupg \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pip install before copying app code — maximises Docker layer cache.
# Rebuilds only re-run from here if requirements.txt changes.
# Install lightweight deps first (fast, rarely change)
COPY requirements.txt .
RUN pip install --no-cache-dir --timeout=300 --retries=5 \
    fastapi==0.111.0 \
    uvicorn==0.29.0 \
    sqlalchemy==2.0.30 \
    psycopg2-binary==2.9.9 \
    playwright==1.44.0 \
    httpx \
    groq==1.1.1 \
    pypdf==4.2.0

# Install heavy ML deps separately — cached unless these lines change
RUN pip install --no-cache-dir --timeout=300 --retries=5 \
    transformers==4.41.0 \
    torch==2.3.0

# Install Playwright's own Chromium (do not mix with apt chromium)
RUN playwright install chromium

# Copy full application — main.py, config.py, scrapers/ package
COPY . .

RUN mkdir -p /app/output

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]