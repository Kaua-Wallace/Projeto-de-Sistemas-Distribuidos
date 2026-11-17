"""Serviço de Processamento (porta 8002): gera thumbnails. Chamado só pela Galeria."""
import io

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError

app = FastAPI(title="Serviço de Processamento")

TIPOS_ACEITOS = {"image/jpeg", "image/png", "image/gif", "image/webp"}
TAMANHO_MAX = 5 * 1024 * 1024  # 5 MB
LADO_THUMB = 256  # px


@app.get("/health")
def health():
    return {"status": "ok", "service": "processing"}


@app.post("/internal/thumbnail")
async def gerar_thumbnail(file: UploadFile = File(...)):
    if file.content_type not in TIPOS_ACEITOS:
        raise HTTPException(415, "Tipo de imagem não aceito")
    dados = await file.read()
    if not dados:
        raise HTTPException(400, "Arquivo vazio")
    if len(dados) > TAMANHO_MAX:
        raise HTTPException(413, "Arquivo maior que 5 MB")
    try:
        img = Image.open(io.BytesIO(dados)).convert("RGB")
    except (UnidentifiedImageError, OSError):
        raise HTTPException(422, "Arquivo não é uma imagem válida")
    img.thumbnail((LADO_THUMB, LADO_THUMB))
    saida = io.BytesIO()
    img.save(saida, "JPEG")
    return Response(saida.getvalue(), media_type="image/jpeg")
