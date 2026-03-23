FROM python:3.12-slim AS base

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml setup.py* ./
RUN pip install --no-cache-dir .

COPY chronos_mcp/ chronos_mcp/

ENV CHRONOS_TRANSPORT=http
ENV CHRONOS_HOST=::
ENV CHRONOS_PORT=8000

EXPOSE 8000

CMD ["python", "-m", "chronos_mcp"]
