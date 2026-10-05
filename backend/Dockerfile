FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /tmp/requirements.txt
# CPU-only torch first. The default PyPI wheel on aarch64 pulls in several GB of CUDA
# libraries this GPU-less host can never use (the image was 10.8 GB); FinBERT runs on
# CPU either way. requirements.txt then sees torch already satisfied.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch>=2.2,<3" \
 && pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend /app/backend
COPY data_pipeline /app/data_pipeline
COPY models /app/models
COPY tests /app/tests
COPY .env.example /app/.env.example

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
