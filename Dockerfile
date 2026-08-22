FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    ca-certificates \
    tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# Copy dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY pyproject.toml .
COPY src/ ./src/

# Install the package in editable or standard mode
RUN pip install --no-cache-dir -e .

# Create data directory for SQLite & runtime storage
RUN mkdir -p /app/data

VOLUME ["/app/data", "/app/config.yaml"]

CMD ["python", "-m", "tg_baidu.main"]
