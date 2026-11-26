# Imagem do Serviço de Processamento (porta 8002)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY processing_service/ ./processing_service/
COPY common/ ./common/

EXPOSE 8002

CMD ["uvicorn", "processing_service.main:app", "--host", "0.0.0.0", "--port", "8002"]