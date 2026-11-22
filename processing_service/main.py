"""Serviço de Processamento (porta 8002): gera thumbnails. Chamado só pela Galeria."""
import io

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from common import log_evento, middleware_logs
from starlette.concurrency import run_in_threadpool

app = FastAPI(title="Serviço de Processamento")


@app.middleware("http")
async def logs_http(request, call_next):
    return await middleware_logs(request, call_next, servico="processing")

TIPOS_ACEITOS = {"image/jpeg", "image/png", "image/gif", "image/webp"}
TAMANHO_MAX = 5 * 1024 * 1024  # 5 MB
LADO_THUMB = 256  # px

def processar_imagem(dados: bytes) -> bytes:
    """
    Processa a imagem usando Pillow.

    Essa função é síncrona e será executada em uma thread
    separada para não bloquear o event loop.
    """

    with Image.open(io.BytesIO(dados)) as original:
        img = original.convert("RGB")

    img.thumbnail((LADO_THUMB, LADO_THUMB))
    saida = io.BytesIO()
    img.save(saida, "JPEG")
    return saida.getvalue()

@app.get("/health")
def health():
    return {"status": "ok", "service": "processing"}


@app.post("/internal/thumbnail")
async def gerar_thumbnail(file: UploadFile = File(...)):
    log_evento(
        "thumbnail_entrada",
        servico="processing",
        arquivo=file.filename
    )
    if file.content_type not in TIPOS_ACEITOS:
        raise HTTPException(
            415,
            "Tipo de imagem não aceito"
        )
    dados = await file.read()
    if not dados:
        raise HTTPException(
            400,
            "Arquivo vazio"
        )
    if len(dados) > TAMANHO_MAX:
        raise HTTPException(
            413,
            "Arquivo maior que 5 MB"
        )
    try:
        # Executa o processamento do Pillow em uma thread separada
        
        resultado = await run_in_threadpool(
            processar_imagem,
            dados
        )
    except (UnidentifiedImageError, OSError):
        raise HTTPException(
            422,
            "Arquivo não é uma imagem válida"
        )
    log_evento(
        "thumbnail_resultado",
        servico="processing",
        status=200,
        tamanho=len(resultado)
    )
    return Response(
        resultado,
        media_type="image/jpeg"
    )