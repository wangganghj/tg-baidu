FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8082

WORKDIR /app

# Install system build dependencies needed for C/Cython extensions (baidupcs-py, aget, cffi)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    python3-dev \
    libffi-dev \
    ca-certificates \
    tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# Pre-install pip, setuptools, wheel, and Cython (required by baidupcs-py)
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir Cython

# Copy dependencies and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code and configs
COPY pyproject.toml .
COPY config.example.yaml ./config.example.yaml
COPY src/ ./src/

# Install the package
RUN pip install --no-cache-dir -e .

# Create data directory for SQLite & runtime storage
RUN mkdir -p /app/data

EXPOSE 8082

VOLUME ["/app/data"]

CMD ["python", "-m", "tg_baidu.main"]
