FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash app \
    && mkdir -p /data \
    && chown app:app /data

COPY --chown=app:app pyproject.toml ./
COPY --chown=app:app src ./src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e .

USER app

EXPOSE 8000

CMD ["uvicorn", "auto_remediation.main:app", "--host", "0.0.0.0", "--port", "8000"]
