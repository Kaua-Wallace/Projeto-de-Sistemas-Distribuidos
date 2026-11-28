"""Serviço de Processamento (porta 8002): gera thumbnails. Chamado só pela Galeria."""
import io
import threading
import warnings

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
from common import log_evento, middleware_logs
from common.constantes import FORMATO_PARA_MIME, TAMANHO_MAX, TIPOS_ACEITOS
from starlette.concurrency import run_in_threadpool

app = FastAPI(title="Serviço de Processamento")


def usuario_para_log(request: Request) -> str | None:
    return request.headers.get("x-user-context")


@app.middleware("http")
async def logs_http(request, call_next):
    return await middleware_logs(
        request,
        call_next,
        servico="processing",
        resolver_usuario=usuario_para_log,
    )

LADO_THUMB = 256  # px
LIMITE_PIXELS = 40_000_000

# limita a quantidade de pixels para reduzir riscos de imagens com dimensoes excessivas
Image.MAX_IMAGE_PIXELS = LIMITE_PIXELS

_LOCK_ABERTURA = threading.Lock()


class ErroProcessamento(Exception):
    def __init__(self, status: int, mensagem: str):
        super().__init__(mensagem)
        self.status = status
        self.mensagem = mensagem


def abrir_imagem(dados: bytes):
    with _LOCK_ABERTURA:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            return Image.open(io.BytesIO(dados))


def processar_imagem(dados: bytes, tipo_declarado: str | None = None) -> bytes:
    """
    Processa a imagem usando Pillow.

    Essa função é síncrona e será executada em uma thread
    separada para não bloquear o event loop.
    """

    with abrir_imagem(dados) as original:
        # confere o formato real da imagem em vez de confiar somente no MIME informado pelo cliente
        mime_real = FORMATO_PARA_MIME.get(original.format)

        if mime_real is None:
            raise ErroProcessamento(415, "Formato de imagem não aceito")
        if tipo_declarado is not None and tipo_declarado != mime_real:
            raise ErroProcessamento(
                422, "O formato real da imagem não corresponde ao tipo declarado"
            )
        largura, altura = original.size
        if largura * altura > LIMITE_PIXELS:
            raise ErroProcessamento(422, "Imagem com dimensões excessivas")

        orientada = ImageOps.exif_transpose(original)
        if "A" in orientada.getbands() or "transparency" in orientada.info:
            rgba = orientada.convert("RGBA")
            img = Image.new("RGB", rgba.size, (255, 255, 255))
            img.paste(rgba, mask=rgba.getchannel("A"))
        else:
            img = orientada.convert("RGB")

    img.thumbnail((LADO_THUMB, LADO_THUMB))
    saida = io.BytesIO()
    img.save(saida, "JPEG")
    return saida.getvalue()

@app.get("/health")
def health():
    return {"status": "ok", "service": "processing"}


@app.post("/internal/thumbnail")
async def gerar_thumbnail(request: Request, file: UploadFile = File(...)):
    usuario = request.headers.get("x-user-context")
    log_evento(
        "thumbnail_entrada",
        servico="processing",
        arquivo=file.filename,
        usuario=usuario,
    )
    if file.content_type not in TIPOS_ACEITOS:
        raise HTTPException(
            415,
            "Tipo de imagem não aceito"
        )
    dados = await file.read(TAMANHO_MAX + 1)
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

        resultado = await run_in_threadpool( #executa o processamento da imagem fora do event loop para evitar bloqueios
            processar_imagem,
            dados,
            file.content_type
        )
    except ErroProcessamento as erro:
        raise HTTPException(erro.status, erro.mensagem)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(
            422,
            "Imagem com dimensões excessivas"
        )
    # converte falhas de leitura e imagens invalidas em respostas HTTP controladas
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise HTTPException(
            422,
            "Arquivo não é uma imagem válida"
        )
    log_evento(
        "thumbnail_resultado",
        servico="processing",
        status=200,
        tamanho=len(resultado),
        usuario=usuario,
    )
    return Response(
        resultado,
        media_type="image/jpeg"
    )
