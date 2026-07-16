# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AGENTOPS_LLM_PROVIDER=fake

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps -e .

EXPOSE 8000

# Defaults to the offline deterministic LLM provider (AGENTOPS_LLM_PROVIDER=fake)
# so the container is usable out of the box with no API keys or external
# services. Set ANTHROPIC_API_KEY/OPENAI_API_KEY + AGENTOPS_LLM_PROVIDER to
# use a real model, and AGENTOPS_REDIS_URL to persist runs in Redis instead
# of the in-process store.
CMD ["uvicorn", "agentops_sentinel.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
