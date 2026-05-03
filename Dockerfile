# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────────────────
#  Munwan Car Rental — Production Dockerfile
# ─────────────────────────────────────────────────────────────────────────────
#  Multi-stage build:
#    Stage 1 (builder): installs build tools + Python deps into a venv
#    Stage 2 (final):   copies just the venv + app code → smaller image (~180 MB)
#
#  Build:   docker build -t munwan:latest .
#  Run:     docker run -d --env-file .env -p 8000:8000 munwan:latest
#  Compose: docker compose up -d  (uses docker-compose.yml — preferred)
# ─────────────────────────────────────────────────────────────────────────────

# ═════════ Stage 1: builder ═════════
FROM python:3.12.4-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build dependencies for psycopg2 + Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libjpeg-dev \
        zlib1g-dev \
        libpng-dev \
    && rm -rf /var/lib/apt/lists/*

# Create a venv in /opt/venv so we can copy it cleanly into the final stage
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip \
 && pip install -r /tmp/requirements.txt


# ═════════ Stage 2: final runtime image ═════════
FROM python:3.12.4-slim-bookworm AS final

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=drivekenya.settings \
    PORT=8000

# Runtime libraries only — no compilers in production image
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libjpeg62-turbo \
        libpng16-16 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user — never run Django as root in production
RUN useradd --create-home --shell /bin/bash --uid 1000 munwan
WORKDIR /app

# Copy the pre-built venv from the builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY --chown=munwan:munwan . /app

# Pre-create writable dirs for static + media. Gunicorn runs as 'munwan'.
RUN mkdir -p /app/staticfiles /app/media \
 && chown -R munwan:munwan /app

USER munwan

# Collect static files at BUILD time. This bakes /app/staticfiles into the image
# so WhiteNoise can serve them immediately. SECRET_KEY is dummy here because
# collectstatic doesn't need a real one.
RUN DJANGO_SECRET_KEY=build-only-not-used \
    DEBUG=False \
    ALLOWED_HOSTS="*" \
    DATABASE_URL="" \
    python manage.py collectstatic --no-input --clear

# Health check — Docker can use this to detect crashed containers.
# We pass the Host header so DEBUG=False doesn't reject the request as
# DisallowedHost (which used to leak SECRET_KEY via mail_admins emails).
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f -H "Host: munwancarrental.com" http://localhost:${PORT}/ || exit 1

EXPOSE 8000

# Container startup: migrate, then collectstatic (in case build-time staticfiles
# were cleared or the image was restarted with a stale layer), then gunicorn.
# Both migrate and collectstatic are idempotent — safe to run every start.
CMD ["sh", "-c", "python manage.py migrate --no-input && \
     python manage.py collectstatic --no-input && \
     exec gunicorn drivekenya.wsgi \
       --bind 0.0.0.0:${PORT} \
       --workers 3 \
       --threads 2 \
       --timeout 60 \
       --access-logfile - \
       --error-logfile - \
       --log-level info"]