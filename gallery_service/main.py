
"""Serviço de Galeria (porta 8001): autenticação, metadados, armazenamento e histórico."""

import hashlib
import hmac
import os
import secrets
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from common import log_evento, middleware_logs
from gallery_service import db
from contextlib import asynccontextmanager
from starlette.concurrency import run_in_threadpool

PROCESSING_URL = os.getenv(
    "PROCESSING_URL",
    "http://localhost:8002"
).rstrip("/")
PROCESSING_TIMEOUT_SECONDS = float(
    os.getenv("PROCESSING_TIMEOUT_SECONDS", "10")
)
RAIZ = Path(__file__).resolve().parents[1]
STORAGE = Path(
    os.getenv("STORAGE_ROOT", RAIZ / "storage")
)

def criar_cliente_processamento():
    """
    Cria o cliente HTTP assíncrono que será reutilizado
    durante toda a execução
    """
    return httpx.AsyncClient(
        timeout=PROCESSING_TIMEOUT_SECONDS
    )


def usuario_para_log(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:].strip()
    return usuario_do_token(token)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.processing_client = criar_cliente_processamento()
    db.iniciar(STORAGE / "galeria.db")
    carregar_estado()
    try:
        yield
    finally:
        await app.state.processing_client.aclose()
        db.fechar()

TIPOS_ACEITOS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
}
TAMANHO_MAX = 5 * 1024 * 1024  # 5 MB

app = FastAPI(
    title="Serviço de Galeria",
    lifespan=lifespan
)

@app.middleware("http")
async def logs_http(request, call_next):
    return await middleware_logs(
        request, call_next, servico="gallery", resolver_usuario=usuario_para_log
    )

@app.get("/health")
def health():
    return {"status": "ok", "service": "gallery"}

# Estado central (em memória)

usuarios = {}  # username -> hash da senha
tokens = {}  # token -> username
imagens = {}  # id -> metadados da imagem
historico = []  # uploads: {usuario, image_id, nome, data}

tokens_expira = {}  # token -> instante de expiração (epoch)

TOKEN_TTL_SEGUNDOS = int(os.getenv("TOKEN_TTL_SEGUNDOS", str(24 * 3600)))


def carregar_estado() -> None:
    """Repovoa a memória a partir do SQLite (chamado na inicialização)."""
    u, t, i, h = db.carregar(time.time())
    usuarios.clear(); usuarios.update(u)
    tokens.clear(); tokens_expira.clear()
    for token, (usuario, expira) in t.items():
        tokens[token] = usuario
        tokens_expira[token] = expira
    imagens.clear(); imagens.update(i)
    historico[:] = h

class Credenciais(BaseModel):
    username: str
    password: str


ITERACOES_PBKDF2 = 200_000


def hash_senha(senha: str) -> str:
    sal = secrets.token_bytes(16)
    derivado = hashlib.pbkdf2_hmac(
        "sha256", senha.encode(), sal, ITERACOES_PBKDF2
    )
    return f"pbkdf2_sha256${ITERACOES_PBKDF2}${sal.hex()}${derivado.hex()}"


def verificar_senha(senha: str, armazenado: str | None) -> bool:
    if not armazenado:
        return False
    try:
        _, iteracoes, sal, esperado = armazenado.split("$")
        derivado = hashlib.pbkdf2_hmac(
            "sha256", senha.encode(), bytes.fromhex(sal), int(iteracoes)
        )
    except ValueError:
        return False
    return hmac.compare_digest(derivado.hex(), esperado)


def usuario_do_token(token: str) -> str | None:
    """Resolve um token de sessão para o nome de usuário, se ainda válido."""
    usuario = tokens.get(token)
    if usuario is None:
        return None
    if tokens_expira.get(token, 0) < time.time():
        tokens.pop(token, None)
        tokens_expira.pop(token, None)
        db.remover_token(token)
        return None
    return usuario


def usuario_logado(authorization: str = Header(default="")) -> str:
    """Dependência: devolve o usuário do token Bearer ou responde 401."""
    token = authorization.removeprefix("Bearer ").strip()
    usuario = usuario_do_token(token)
    if usuario is None:
        raise HTTPException(401, "Não autenticado")
    return usuario


# Autenticação

@app.post("/auth/register", status_code=201)
def cadastrar(c: Credenciais):
    if not (3 <= len(c.username) <= 30) or len(c.password) < 6:
        raise HTTPException(422, "username: 3-30 caracteres; password: mínimo 6")
    if c.username in usuarios:
        raise HTTPException(409, "Usuário já existe")
    senha_hash = hash_senha(c.password)
    if not db.salvar_usuario(c.username, senha_hash):
        raise HTTPException(409, "Usuário já existe")
    usuarios[c.username] = senha_hash
    return {"username": c.username}


@app.post("/auth/login")
def login(c: Credenciais):
    if not verificar_senha(c.password, usuarios.get(c.username)):
        log_evento("login_falhou", servico="gallery", usuario=c.username)
        raise HTTPException(401, "Credenciais inválidas")
    token = secrets.token_urlsafe(24)
    expira = time.time() + TOKEN_TTL_SEGUNDOS
    tokens[token] = c.username
    tokens_expira[token] = expira
    db.salvar_token(token, c.username, expira)
    return {"token": token}

@app.post("/auth/logout", status_code=204)
def logout(
    authorization: str = Header(default=""),
    _: str = Depends(usuario_logado),
):
    token = authorization.removeprefix("Bearer ").strip()
    tokens.pop(token, None)
    tokens_expira.pop(token, None)
    db.remover_token(token)

# Imagens

@app.post("/images", status_code=201)
async def upload(
    file: UploadFile = File(...),
    usuario: str = Depends(usuario_logado)
):

    # Validação do tipo de arquivo
    
    if file.content_type not in TIPOS_ACEITOS:
        raise HTTPException(
            415,
            f"Tipo não aceito. Use: {list(TIPOS_ACEITOS)}"
        )

    # Leitura assíncrona do arquivo

    dados = await file.read(TAMANHO_MAX + 1)

    if not dados:
        raise HTTPException(400, "Arquivo vazio")

    if len(dados) > TAMANHO_MAX:
        raise HTTPException(413, "Arquivo maior que 5 MB")

    # Chamada assíncrona ao Serviço de Processamento

    inicio_processamento = time.perf_counter()

    try:

        r = await app.state.processing_client.post(
            f"{PROCESSING_URL}/internal/thumbnail",
            headers={"X-User-Context": usuario},
            files={
                "file": (
                    file.filename,
                    dados,
                    file.content_type
                )
            }
        )

    except httpx.RequestError:

        log_evento(
            "chamada_processamento",
            servico="gallery",
            status=None,
            duracao_ms=round(
                (time.perf_counter() - inicio_processamento) * 1000,
                2
            )
        )

        log_evento(
            "falha_miniatura",
            servico="gallery",
            usuario=usuario,
            motivo="indisponivel"
        )

        raise HTTPException(
            503,
            "Serviço de Processamento indisponível"
        )

    log_evento(
        "chamada_processamento",
        servico="gallery",
        status=r.status_code,
        duracao_ms=round(
            (time.perf_counter() - inicio_processamento) * 1000,
            2
        )
    )

    # Tratamento dos erros retornados pelo Processamento

    if r.status_code != 200:

        log_evento(
            "falha_miniatura",
            servico="gallery",
            usuario=usuario,
            status=r.status_code
        )

        codigo = (
            r.status_code
            if r.status_code in (415, 422)
            else 502
        )

        raise HTTPException(
            codigo,
            "Falha ao gerar miniatura"
        )

    # Armazenamento dos arquivos

    img_id = str(uuid.uuid4())

    pasta_o = STORAGE / "originals" / usuario
    pasta_t = STORAGE / "thumbnails" / usuario

    caminho_o = pasta_o / f"{img_id}.{TIPOS_ACEITOS[file.content_type]}"
    caminho_t = pasta_t / f"{img_id}.jpg"

    await run_in_threadpool(
        persistir_arquivos,
        caminho_o,
        caminho_t,
        dados,
        r.content,
    )

    # Registro dos metadados

    agora = datetime.now().isoformat(timespec="seconds")

    nome = os.path.basename(file.filename or img_id)

    registro = {
        "id": img_id,
        "autor": usuario,
        "data": agora,
        "nome": nome,
        "tipo": file.content_type,
        "tamanho": len(dados),
        "caminho_original": str(caminho_o),
        "caminho_miniatura": str(caminho_t),
        "url_miniatura": f"/images/{img_id}/thumbnail",
    }

    envio = {
        "usuario": usuario,
        "image_id": img_id,
        "nome": nome,
        "data": agora
    }

    await run_in_threadpool(db.salvar_imagem, registro, envio)
    imagens[img_id] = registro
    historico.append(envio)

    log_evento(
        "upload_concluido",
        servico="gallery",
        usuario=usuario,
        id=img_id,
        tamanho=len(dados)
    )

    return publica(imagens[img_id])

def publica(img: dict) -> dict:
    """Remove os caminhos internos do disco antes de responder ao cliente."""
    return {k: v for k, v in img.items() if not k.startswith("caminho")}


def persistir_arquivos(
    caminho_original: Path,
    caminho_miniatura: Path,
    original: bytes,
    miniatura: bytes,
) -> None:
    caminho_original.parent.mkdir(parents=True, exist_ok=True)
    caminho_miniatura.parent.mkdir(parents=True, exist_ok=True)
    caminho_original.write_bytes(original)
    caminho_miniatura.write_bytes(miniatura)


@app.get("/images")
def listar(
    autor: str | None = None,
    ordem: Literal["data_desc", "data_asc"] = "data_desc",
    limit: int = Query(default=100, ge=1),
    offset: int = Query(default=0, ge=0),
    _: str = Depends(usuario_logado),
):
    selecionadas = (
        imagem for imagem in imagens.values()
        if autor is None or imagem["autor"] == autor
    )
    ordenadas = sorted(
        selecionadas,
        key=lambda imagem: imagem["data"],
        reverse=ordem == "data_desc",
    )
    pagina = ordenadas[offset:offset + limit]
    return [
        {
            "id": i["id"],
            "autor": i["autor"],
            "data": i["data"],
            "nome": i["nome"],
            "tamanho": i["tamanho"],
            "url_miniatura": i["url_miniatura"],
        }
        for i in pagina
    ]


def buscar(img_id: str) -> dict:
    if img_id not in imagens:
        raise HTTPException(404, "Imagem não encontrada")
    return imagens[img_id]


def arquivo_existente(img: dict, chave: str) -> Path:
    caminho = Path(img[chave])
    if not caminho.is_file():
        raise HTTPException(404, "Arquivo da imagem não encontrado no disco")
    return caminho


@app.get("/images/{img_id}/thumbnail")
def previa(img_id: str, _: str = Depends(usuario_logado)):
    caminho = arquivo_existente(buscar(img_id), "caminho_miniatura")
    return FileResponse(caminho, media_type="image/jpeg")


@app.get("/images/{img_id}/download")
def download(img_id: str, _: str = Depends(usuario_logado)):
    img = buscar(img_id)
    caminho = arquivo_existente(img, "caminho_original")
    return FileResponse(caminho, media_type=img["tipo"], filename=img["nome"])


@app.get("/history")
def meu_historico(usuario: str = Depends(usuario_logado)):
    envios = sorted(
        (h for h in historico if h["usuario"] == usuario),
        key=lambda envio: envio["data"],
        reverse=True,
    )
    return [
        {
            **envio,
            "url_miniatura": f"/images/{envio['image_id']}/thumbnail",
        }
        for envio in envios
    ]


# Interface web (HTML/CSS/JS) servida na mesma origem da API: dispensa CORS.
# Fica por último para não sombrear nenhuma rota da API.
app.mount(
    "/app",
    StaticFiles(directory=RAIZ / "frontend", html=True),
    name="frontend",
)
