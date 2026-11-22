
"""Serviço de Galeria (porta 8001): autenticação, metadados, armazenamento e histórico."""

import hashlib
import hmac
import os
import secrets
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from common import log_evento, middleware_logs

app = FastAPI(title="Serviço de Galeria")


@app.middleware("http")
async def logs_http(request, call_next):
    return await middleware_logs(
        request, call_next, servico="gallery", resolver_usuario=usuario_do_token
    )


PROCESSING_URL = os.getenv("PROCESSING_URL", "http://localhost:8002")
RAIZ = Path(__file__).resolve().parents[1]
STORAGE = Path(os.getenv("STORAGE_ROOT", RAIZ / "storage"))
TIPOS_ACEITOS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
}
TAMANHO_MAX = 5 * 1024 * 1024  # 5 MB

@app.get("/health")
def health():
    return {"status": "ok", "service": "gallery"}


# Estado central (em memória)

usuarios = {}  # username -> hash da senha
tokens = {}  # token -> username
imagens = {}  # id -> metadados da imagem
historico = []  # uploads: {usuario, image_id, nome, data}


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
    return tokens.get(token)


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
    usuarios[c.username] = hash_senha(c.password)
    return {"username": c.username}


@app.post("/auth/login")
def login(c: Credenciais):
    if not verificar_senha(c.password, usuarios.get(c.username)):
        log_evento("login_falhou", servico="gallery", usuario=c.username)
        raise HTTPException(401, "Credenciais inválidas")
    token = secrets.token_urlsafe(24)
    tokens[token] = c.username
    return {"token": token}


# Imagens

@app.post("/images", status_code=201)
async def upload(file: UploadFile = File(...), usuario: str = Depends(usuario_logado)):
    if file.content_type not in TIPOS_ACEITOS:
        raise HTTPException(415, f"Tipo não aceito. Use: {list(TIPOS_ACEITOS)}")
    dados = await file.read()
    if not dados:
        raise HTTPException(400, "Arquivo vazio")
    if len(dados) > TAMANHO_MAX:
        raise HTTPException(413, "Arquivo maior que 5 MB")

    # chama o Serviço de Processamento para gerar a miniatura
    inicio_processamento = time.perf_counter()
    try:
        r = httpx.post(
            f"{PROCESSING_URL}/internal/thumbnail",
            files={"file": (file.filename, dados, file.content_type)},
            timeout=10,
        )
    except httpx.HTTPError:
        log_evento(
            "chamada_processamento", servico="gallery", status=None,
            duracao_ms=round((time.perf_counter() - inicio_processamento) * 1000, 2),
        )
        log_evento("falha_miniatura", servico="gallery", usuario=usuario, motivo="indisponivel")
        raise HTTPException(503, "Serviço de Processamento indisponível")
    log_evento(
        "chamada_processamento", servico="gallery", status=r.status_code,
        duracao_ms=round((time.perf_counter() - inicio_processamento) * 1000, 2),
    )
    if r.status_code != 200:
        log_evento("falha_miniatura", servico="gallery", usuario=usuario, status=r.status_code)
        codigo = r.status_code if r.status_code in (415, 422) else 502
        raise HTTPException(codigo, "Falha ao gerar miniatura")

    # armazenamento: storage/<originals|thumbnails>/<usuario>/<id>.<ext>
    img_id = str(uuid.uuid4())
    pasta_o = STORAGE / "originals" / usuario
    pasta_t = STORAGE / "thumbnails" / usuario
    pasta_o.mkdir(parents=True, exist_ok=True)
    pasta_t.mkdir(parents=True, exist_ok=True)
    caminho_o = pasta_o / f"{img_id}.{TIPOS_ACEITOS[file.content_type]}"
    caminho_t = pasta_t / f"{img_id}.jpg"
    caminho_o.write_bytes(dados)
    caminho_t.write_bytes(r.content)

    # metadados (dicionário de imagens) e histórico de uploads
    agora = datetime.now().isoformat(timespec="seconds")
    nome = os.path.basename(file.filename or img_id)
    imagens[img_id] = {
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
    historico.append({"usuario": usuario, "image_id": img_id, "nome": nome, "data": agora})
    log_evento("upload_concluido", servico="gallery", usuario=usuario, id=img_id, tamanho=len(dados))
    return publica(imagens[img_id])


def publica(img: dict) -> dict:
    """Remove os caminhos internos do disco antes de responder ao cliente."""
    return {k: v for k, v in img.items() if not k.startswith("caminho")}


@app.get("/images")
def listar(_: str = Depends(usuario_logado)):
    return [
        {"id": i["id"], "autor": i["autor"], "data": i["data"],
         "url_miniatura": i["url_miniatura"]}
        for i in imagens.values()
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
    return [h for h in historico if h["usuario"] == usuario]
