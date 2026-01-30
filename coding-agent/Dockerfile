FROM python:3.12-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY coding-agent/pyproject.toml .
RUN pip install --no-cache-dir .

ENV PYTHONPATH=/app

COPY shared/ shared/
COPY coding-agent/app app/

EXPOSE 80

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]