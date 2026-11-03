FROM python:3.11.6-slim

# ---------------- SYSTEM DEPENDENCIES ----------------
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        git \
        python3 \
        python3-pip \
        xvfb \
        xauth \
        aria2 \
        ffmpeg \
        mediainfo \
        ca-certificates \
        wget \
        curl \
        unzip \
        fonts-liberation \
        \
        # ---- Playwright / Chromium deps ----
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libgtk-3-0 \
        libx11-xcb1 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        libgbm1 \
        libnss3 \
        libasound2 \
        libdrm2 \
        libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

# ---------------- ENV ----------------
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99

# ---------------- WORKDIR ----------------
WORKDIR /app

# ---------------- PYTHON DEPENDENCIES ----------------
RUN pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir \
        fastapi \
        uvicorn \
        playwright \
        pyrogram==2.0.80 \
        tgcrypto

# ---------------- PLAYWRIGHT ----------------
RUN playwright install chromium

# ---------------- APP DEPENDENCIES ----------------
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# ---------------- COPY APP ----------------
COPY . .

# ---------------- START ----------------
CMD ["sh", "-c", "aria2c --enable-rpc --rpc-listen-all=true --rpc-allow-origin-all --daemon && xvfb-run -a python3 main.py"]
