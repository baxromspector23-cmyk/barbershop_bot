# Stage 1: Build & Runtime
FROM python:3.12-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 appuser

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Ensure entrypoint is executable and set ownership
RUN chmod +x docker-entrypoint.sh scripts/*.py \
    && chown -R appuser:appuser /app

USER appuser

# Serverless & container environment variables
ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    HOST=0.0.0.0

EXPOSE 8080

ENTRYPOINT ["./docker-entrypoint.sh"]
