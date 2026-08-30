# Container image for the AutoBuy backend.
#
# render.yaml uses Render's native Python runtime, which needs no image. This
# Dockerfile is the portable alternative for Fly, Railway, Cloud Run, or local
# container runs.

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first: this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user.
RUN useradd --create-home --uid 1000 autobuy && chown -R autobuy:autobuy /app
USER autobuy

EXPOSE 8000

# PORT is provided by most platforms; 8000 is the local default.
CMD ["sh", "-c", "alembic upgrade head && python -m scripts.seed_catalog && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
