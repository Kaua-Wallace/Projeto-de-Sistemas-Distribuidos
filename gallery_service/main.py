"""Serviço de Galeria (porta 8001): autenticação, metadados, armazenamento e histórico."""

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from common import log_evento, middleware_logs
from common.constantes import TAMANHO_MAX, TIPOS_ACEITOS
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

# define as regras de validacao dos usernames e os limites de segurança do armazenamento
USERNAME_REGEX = re.compile(r"[A-Za-z0-9_.-]{3,30}")
MARGEM_MULTIPART = 64 * 1024
TAMANHO_MAX_NOME = 120
LOCK_USUARIOS = threading.Lock()  # evita alteraçoes simultaneas conflitantes nos usuarios e nos metadados
LOCK_METADADOS = threading.Lock()


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
    try:
        yield
    finally:
        await app.state.processing_client.aclose()

MENSAGENS_PROCESSAMENTO = {
    413: "Arquivo maior que 5 MB",
    415: "Tipo de imagem não aceito",
    422: "Arquivo inválido, corrompido ou diferente do formato declarado",
}

app = FastAPI(
    title="Serviço de Galeria",
    lifespan=lifespan
)

# rejeita uploads com tamnho declarado acima do limite antes de processar o multipart
@app.middleware("http")
async def limitar_tamanho(request, call_next):
    if request.method == "POST" and request.url.path == "/images":
        declarado = request.headers.get("content-length", "").strip()
        if declarado.isdigit() and int(declarado) > TAMANHO_MAX + MARGEM_MULTIPART:
            return JSONResponse(
                status_code=413,
                content={"detail": "Arquivo maior que 5 MB"},
            )
    return await call_next(request)


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

# aceita somente usernames dentro do padrao definido e impede nmes iniciados por ponto
def username_valido(username: str) -> bool:
    return bool(USERNAME_REGEX.fullmatch(username)) and not username.startswith(".")

# garante que o caminho final permaneça detro da pasta de armazenamento esperada
def caminho_no_storage(subpasta: str, usuario: str, nome_arquivo: str) -> Path:
    partes = (usuario, nome_arquivo)
    if (
        any(parte in ("", ".", "..") for parte in partes)
        or any(sep in parte for parte in partes for sep in ("/", "\\"))
    ):
        raise HTTPException(422, "Caminho de armazenamento inválido")
    raiz = (STORAGE / subpasta).resolve()
    destino = (STORAGE / subpasta / usuario / nome_arquivo).resolve()
    if destino.parent.parent != raiz:
        raise HTTPException(422, "Caminho de armazenamento inválido")
    return destino

# remove componentes de caminho e caracteres inadequados do nome original do arquivo
def nome_seguro(nome_bruto: str | None, padrao: str) -> str:
    nome = (nome_bruto or "").replace("\\", "/")
    nome = os.path.basename(nome)
    nome = "".join(c for c in nome if c.isprintable()).strip()
    if nome in ("", ".", ".."):
        nome = padrao
    if len(nome) > TAMANHO_MAX_NOME:
        base, extensao = os.path.splitext(nome)
        nome = base[: max(1, TAMANHO_MAX_NOME - len(extensao))] + extensao
    return nome

# gera nomes de exibiçao diferetes para arquivos com o mesmo nome enviados pelo usuario
def nome_exibicao_unico(usuario: str, nome: str) -> str:
    existentes = {i["nome"] for i in imagens.values() if i["autor"] == usuario}
    if nome not in existentes:
        return nome
    base, extensao = os.path.splitext(nome)
    sufixo = re.fullmatch(r"(.+) \(\d+\)", base)
    if sufixo:
        base = sufixo.group(1)
    contador = 2
    candidato = f"{base} ({contador}){extensao}"
    while candidato in existentes:
        contador += 1
        candidato = f"{base} ({contador}){extensao}"
    return candidato


# Autenticação

@app.post("/auth/register", status_code=201)
def cadastrar(c: Credenciais):
    if len(c.password) < 6:
        raise HTTPException(422, "password: mínimo 6 caracteres")
    if not username_valido(c.username):
        raise HTTPException(
            422,
            "username: 3-30 caracteres, apenas letras, números, '.', '-' e '_', sem iniciar com ponto",
        )
    senha_hash = hash_senha(c.password)
    #mantem a verificaçao e a criaçao do usuario na mesma regiao protegida contra concorrencia
    with LOCK_USUARIOS:
        if c.username in usuarios:
            raise HTTPException(409, "Usuário já existe")
        usuarios[c.username] = senha_hash
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
            if r.status_code in MENSAGENS_PROCESSAMENTO
            else 502
        )

        raise HTTPException(
            codigo,
            MENSAGENS_PROCESSAMENTO.get(codigo, "Falha ao gerar miniatura")
        )

    # Armazenamento dos arquivos

    img_id = str(uuid.uuid4())

    caminho_o = caminho_no_storage(
        "originals", usuario, f"{img_id}.{TIPOS_ACEITOS[file.content_type]}"
    )
    caminho_t = caminho_no_storage("thumbnails", usuario, f"{img_id}.jpg")

    try:
        await run_in_threadpool(
            persistir_arquivos,
            caminho_o,
            caminho_t,
            dados,
            r.content,
        )
    except OSError as erro:
        log_evento(
            "falha_armazenamento",
            servico="gallery",
            usuario=usuario,
            erro=repr(erro)
        )
        raise HTTPException(500, "Falha ao gravar a imagem no armazenamento") from erro

    # Registro dos metadados

    nome_solicitado = nome_seguro(file.filename, img_id)

    try:
        metadados = await run_in_threadpool(
            registrar_upload,
            img_id,
            usuario,
            nome_solicitado,
            file.content_type,
            len(dados),
            caminho_o,
            caminho_t,
        )
    except Exception as erro:
        await run_in_threadpool(remover_arquivos, caminho_o, caminho_t)
        log_evento(
            "falha_registro",
            servico="gallery",
            usuario=usuario,
            id=img_id,
            erro=repr(erro)
        )
        raise HTTPException(500, "Falha ao registrar a imagem") from erro

    log_evento(
        "upload_concluido",
        servico="gallery",
        usuario=usuario,
        id=img_id,
        tamanho=len(dados)
    )

    return publica(metadados)

def publica(img: dict) -> dict:
    """Remove os caminhos internos do disco antes de responder ao cliente."""
    return {k: v for k, v in img.items() if not k.startswith("caminho")}

# registra os metadados e o historico de forma sincronizada entre uploads simultaneos
def registrar_upload(
    img_id: str,
    usuario: str,
    nome_solicitado: str,
    tipo: str,
    tamanho: int,
    caminho_original: Path,
    caminho_miniatura: Path,
) -> dict:
    with LOCK_METADADOS:
        nome = nome_exibicao_unico(usuario, nome_solicitado)
        agora = datetime.now().isoformat(timespec="seconds")
        metadados = {
            "id": img_id,
            "autor": usuario,
            "data": agora,
            "nome": nome,
            "tipo": tipo,
            "tamanho": tamanho,
            "caminho_original": str(caminho_original),
            "caminho_miniatura": str(caminho_miniatura),
            "url_miniatura": f"/images/{img_id}/thumbnail",
        }
        imagens[img_id] = metadados
        try:
            historico.append({
                "usuario": usuario,
                "image_id": img_id,
                "nome": nome,
                "data": agora,
            })
        except BaseException:
            imagens.pop(img_id, None)
            raise
        return metadados


def _remover_silencioso(caminho: Path) -> None:
    try:
        os.remove(caminho)
    except FileNotFoundError:
        pass
    except OSError as erro:
        log_evento(
            "falha_limpeza",
            servico="gallery",
            caminho=str(caminho),
            erro=repr(erro)
        )

# remove os arquivos relacionados a um upload quando ocorre uma falha no processo
def remover_arquivos(*caminhos: Path) -> None:
    for caminho in caminhos:
        _remover_silencioso(caminho)


def _caminho_temporario(destino: Path) -> Path:
    return destino.with_name(f".{destino.name}.{uuid.uuid4().hex}.tmp")


def _gravar_exclusivo(caminho: Path, conteudo: bytes, criados: list) -> None:
    with open(caminho, "xb") as arquivo:
        criados.append(caminho)
        arquivo.write(conteudo)
        arquivo.flush()
        os.fsync(arquivo.fileno())

# grava os arquivos temporariamente e publica os destinos somente apos concluir as gravaçoes
def persistir_arquivos(
    caminho_original: Path,
    caminho_miniatura: Path,
    original: bytes,
    miniatura: bytes,
) -> None:
    temporarios: list[Path] = []
    publicados: list[Path] = []
    try:
        caminho_original.parent.mkdir(parents=True, exist_ok=True)
        caminho_miniatura.parent.mkdir(parents=True, exist_ok=True)

        temp_original = _caminho_temporario(caminho_original)
        temp_miniatura = _caminho_temporario(caminho_miniatura)

        _gravar_exclusivo(temp_original, original, temporarios)
        _gravar_exclusivo(temp_miniatura, miniatura, temporarios)

        os.replace(temp_original, caminho_original)
        temporarios.remove(temp_original)
        publicados.append(caminho_original)

        os.replace(temp_miniatura, caminho_miniatura)
        temporarios.remove(temp_miniatura)
        publicados.append(caminho_miniatura)
    except BaseException:
        for temporario in temporarios:
            _remover_silencioso(temporario)
        for publicado in publicados:
            _remover_silencioso(publicado)
        raise


@app.get("/images")
def listar(_: str = Depends(usuario_logado)):
    return [
        {
            "id": i["id"],
            "autor": i["autor"],
            "data": i["data"],
            "nome": i["nome"],
            "url_miniatura": i["url_miniatura"],
        }
        for i in list(imagens.values())
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


# Interface web (HTML/CSS/JS) servida na mesma origem da API: dispensa CORS.
# Fica por último para não sombrear nenhuma rota da API.
app.mount(
    "/app",
    StaticFiles(directory=RAIZ / "frontend", html=True),
    name="frontend",
)