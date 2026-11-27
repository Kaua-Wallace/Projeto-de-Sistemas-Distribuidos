# Imagem do Serviço de Galeria (porta 8001)
FROM python:3.12-slim

# Sem arquivos .pyc e com logs aparecendo na hora no "docker compose logs"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Instala as dependências primeiro: o Docker guarda essa camada em cache
# e só reinstala quando o requirements.txt mudar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia apenas o código deste serviço
COPY gallery_service/ ./gallery_service/
COPY common/ ./common/
# Interface web servida pela Galeria em /app
COPY frontend/ ./frontend/

EXPOSE 8001

# --host 0.0.0.0 é obrigatório: sem ele o serviço só aceita conexões
# de dentro do próprio contêiner. Mantenha 1 worker: o estado é em memória.
CMD ["uvicorn", "gallery_service.main:app", "--host", "0.0.0.0", "--port", "8001"]