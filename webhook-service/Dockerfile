FROM python:3.12-slim

WORKDIR /app

COPY webhook-service/pyproject.toml .
RUN pip install --no-cache-dir .

ENV PYTHONPATH=/app

COPY shared/ shared/
COPY webhook-service/app/ app/

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]