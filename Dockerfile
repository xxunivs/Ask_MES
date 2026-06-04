FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY routers ./routers
COPY core ./core
COPY data ./data

ENV PORT=8001
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
