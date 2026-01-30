FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY reviewer-agent/pyproject.toml .
RUN pip install --no-cache-dir .

ENV PYTHONPATH=/app

COPY shared/ shared/
COPY reviewer-agent/app app/

EXPOSE 8081

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081"]
